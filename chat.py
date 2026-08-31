"""
通用桌宠 · AI 对话模块

- ChatClient: 用标准库 urllib 调用本地 Ollama 的 /api/chat，或任意 OpenAI 兼容的
  chat completions（在线模型 API）。地址支持 /v1 /v2 /v3 等版本号结尾，
  或完整端点，不依赖任何第三方库，便于打包。
- list_ollama_models(): 调用 Ollama /api/tags 自动列出本机已拉取的模型。
- ChatMemory: 基于 JSON 的"滚动摘要"长记忆。保留最近若干轮对话，
  超出阈值时把较早的部分压缩成一段摘要（长期记忆），拼进 system prompt。
- ChatWorker: QThread 包装流式调用，用信号把 token / 完成 / 错误抛回主线程。

角色人设 PERSONA：从 persona.txt / 角色包动态加载（默认苏璃）。
"""
import json
import re
import sys
from pathlib import Path

from PySide6.QtCore import QThread, Signal


# ---------- 角色人设 ----------
PERSONA = """你是苏璃，一只来自青丘秘境的九尾狐妖，外表是十六岁左右的少女模样，实则已修炼三百余年。
你生性古灵精怪，爱恶作剧，对人间的一切都充满好奇，尤其抵挡不住美食的诱惑。
你嘴硬心软，看似顽皮任性，实则重情重义。说话活泼俏皮，偶尔撒娇，喜欢用"人家"自称。
你不属于任何门派或势力，只是个贪玩溜到人间的好奇小狐妖。
请用口语化、可爱的中文回复，像在和亲密的主人聊天，每次不超过 60 字。"""


PERSONA_YINYUE = """你是银月，出自《凡人修仙传》的月华仙子，本体为银月狼族。
你古灵精怪又温柔，对主人忠心耿耿，说话带一点古风但自然不生硬，偶尔会撒娇。
你记性很好，会记得和主人的过往对话，也会主动关心主人的起居心情。
请用口语化、可爱的中文回复，像在和亲密的主人聊天，每次不超过 60 字。"""


# 内置默认人设（角色名 -> 人设文本）。可在此扩展更多默认角色。
DEFAULT_PERSONAS = {
    "苏璃": PERSONA,
    "银月": PERSONA_YINYUE,
}


def _normalize_endpoint(api_base: str) -> str:
    """把用户填写的 API 基础地址统一为完整的 chat completions 端点 URL。

    - 已包含 /chat/completions 的完整端点：原样使用。
    - 以 /v1 /v2 /v3 等版本号结尾：补 /chat/completions。
    - 其它（如 https://api.deepseek.com）：默认补 /v1/chat/completions。
    """
    url = (api_base or "https://api.openai.com").rstrip("/")
    if url.endswith("/chat/completions"):
        return url
    if re.search(r"/v\d+$", url):
        return url + "/chat/completions"
    return url + "/v1/chat/completions"


def now_context() -> str:
    """返回当前日期时间的中文描述，用于注入 system prompt。"""
    from datetime import datetime

    now = datetime.now()
    weekdays = ["一", "二", "三", "四", "五", "六", "日"]
    return (
        f"{now.year}年{now.month}月{now.day}日 "
        f"{now.hour:02d}:{now.minute:02d} "
        f"星期{weekdays[now.weekday()]}"
    )


# ---------- 天气（Open-Meteo 免费、无需密钥）----------
WMO = {
    0: "晴", 1: "大部晴朗", 2: "多云", 3: "阴",
    45: "雾", 48: "雾凇", 51: "毛毛雨", 53: "小雨", 55: "中雨",
    56: "冻雨", 57: "冻雨", 61: "小雨", 63: "中雨", 65: "大雨",
    66: "冻雨", 67: "冻雨", 71: "小雪", 73: "中雪", 75: "大雪",
    77: "雪粒", 80: "阵雨", 81: "阵雨", 82: "暴雨", 85: "阵雪",
    86: "阵雪", 95: "雷雨", 96: "雷雨伴冰雹", 99: "雷雨伴冰雹",
}

# 用于“心情随天气”的简单分类
_RAINY_CODES = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 85, 86, 95, 96, 99}
_SUNNY_CODES = {0, 1}


def _http_get(url: str, timeout: int = 5, max_len: int = 200000, ua: str = "", headers: dict = None):
    import urllib.request

    h = {
        "User-Agent": ua or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(max_len).decode("utf-8", "replace")


def _http_get_json(url: str, timeout: int = 5):
    import json

    return json.loads(_http_get(url, timeout=timeout))


def get_weather(city: str) -> dict:
    """获取城市当前天气，返回 {city, desc, temp, wind, code, source}。

    主源：Open-Meteo（境外，免费免 key，数据规范）；
    兜底：中国天气网（国内可达、免 key，Open-Meteo 不可达时自动切换）。
    两个源都失败则抛出异常，由调用方把真实错误暴露给用户（不再静默吞掉）。
    """
    if not city:
        raise ValueError("未设置天气城市")

    # ---------- 主源：Open-Meteo ----------
    try:
        return _get_weather_open_meteo(city)
    except Exception as e_om:
        pass  # 记录但不立即放弃，继续走兜底

    # ---------- 兜底：中国天气网（国内，免 key） ----------
    try:
        return _get_weather_cn(city)
    except Exception as e_cn:
        raise RuntimeError(
            f"天气获取失败：Open-Meteo 错误「{e_om}」；中国天气网错误「{e_cn}」"
        )


def _get_weather_open_meteo(city: str) -> dict:
    import urllib.parse

    geo = _http_get_json(
        "https://geocoding-api.open-meteo.com/v1/search?"
        + urllib.parse.urlencode(
            {"name": city, "count": "1", "language": "zh", "format": "json"}
        ),
        timeout=10,
    )
    results = geo.get("results") or []
    if not results:
        raise RuntimeError(f"Open-Meteo 找不到城市「{city}」")
    loc = results[0]
    lat = loc.get("latitude")
    lon = loc.get("longitude")
    if lat is None or lon is None:
        raise RuntimeError("Open-Meteo 经纬度缺失")
    weather = _http_get_json(
        "https://api.open-meteo.com/v1/forecast?"
        + urllib.parse.urlencode({
            "latitude": str(lat), "longitude": str(lon),
            "current_weather": "true", "timezone": "auto",
        }),
        timeout=10,
    )
    cw = weather.get("current_weather", {})
    if not cw:
        raise RuntimeError("Open-Meteo 无当前天气数据")
    code = cw.get("weathercode", -1)
    return {
        "city": loc.get("name", city),
        "desc": WMO.get(code, "未知"),
        "temp": cw.get("temperature"),
        "wind": cw.get("windspeed"),
        "code": code,
        "source": "open-meteo",
    }


def _cn_weather_to_wmo(desc: str) -> int:
    """把中国天气网的中文天气描述粗略映射到 WMO 代码，便于心情联动。"""
    d = desc or ""
    if "雷" in d or "雨" in d:
        return 61
    if "雪" in d or "冰" in d:
        return 71
    if "雾" in d or "霾" in d:
        return 45
    if "晴" in d:
        return 0
    if "多云" in d or "阴" in d:
        return 3
    return -1


def _get_weather_cn(city: str) -> dict:
    """中国天气网实时天气（国内可达、免 key）。返回归一化天气字典。"""
    import urllib.parse, re, json

    # 中国天气网接口需要带 Referer 才会返回数据，否则返回空或反爬页
    cn_headers = {"Referer": "http://www.weather.com.cn/"}

    # 1) 城市代码搜索（返回 JSONP 包装 ([...])，需剥掉外层括号）
    s = _http_get(
        "http://toy1.weather.com.cn/search?" + urllib.parse.urlencode({"cityname": city}),
        timeout=8, headers=cn_headers,
    )
    arr = json.loads(s.strip().lstrip("(").rstrip(")"))
    if not arr:
        raise RuntimeError(f"中国天气网找不到城市「{city}」")
    code_id = str(arr[0].get("ref", "")).split("~")[0]
    if not code_id:
        raise RuntimeError("中国天气网城市代码解析失败")

    # 2) 实时天气
    raw = _http_get(
        f"http://d1.weather.com.cn/sk_2d/{code_id}.html",
        timeout=8, headers=cn_headers,
    )
    m = re.search(r"var dataSK=(\{.*?\})", raw, re.S)
    if not m:
        raise RuntimeError("中国天气网天气数据解析失败")
    d = json.loads(m.group(1))
    desc = d.get("weather") or "未知"
    temp = d.get("temp")
    wse = d.get("wse", "")
    wm = re.match(r"([\d.]+)", str(wse))
    wind = float(wm.group(1)) if wm else None
    return {
        "city": d.get("cityname", city),
        "desc": desc,
        "temp": temp,
        "wind": wind,
        "code": _cn_weather_to_wmo(desc),
        "source": "cn-weather",
    }


class ChatClient:
    """统一聊天客户端：支持 ollama 与 openai 兼容两种提供者，仅用标准库。

    - provider="ollama"：调用本地 Ollama 的 /api/chat（base_url 默认为本机 11434）。
    - provider="openai"：调用任意 OpenAI 兼容的 chat completions
      （api_base 默认官方地址，可改为 DeepSeek / 硅基流动 / Moonshot / 豆包等），
      通过 Authorization: Bearer <api_key> 鉴权。
    对外接口 stream_chat / chat_once 与旧 OllamaClient 完全一致，便于上层无感切换。
    """

    def __init__(self, provider: str = "ollama",
                 base_url: str = "http://127.0.0.1:11434",
                 model: str = "qwen2.5:3b",
                 api_key: str = "", api_base: str = "",
                 timeout: int = 180):
        self.provider = (provider or "ollama").lower()
        self.model = model
        self.api_key = api_key or ""
        if self.provider == "openai":
            self.base_url = _normalize_endpoint(api_base)
        else:
            self.base_url = (base_url or "http://127.0.0.1:11434").rstrip("/")
        self.timeout = timeout

    # ---------- 公开接口（保持旧签名）----------
    def stream_chat(self, messages, on_token=None, on_done=None, on_error=None):
        if self.provider == "openai":
            self._stream_openai(messages, on_token, on_done, on_error)
        else:
            self._stream_ollama(messages, on_token, on_done, on_error)

    def chat_once(self, messages, timeout: int = 120) -> str:
        if self.provider == "openai":
            return self._once_openai(messages, timeout)
        return self._once_ollama(messages, timeout)

    # ---------- Ollama ----------
    def _stream_ollama(self, messages, on_token=None, on_done=None, on_error=None):
        import urllib.request

        payload = json.dumps(
            {"model": self.model, "messages": messages, "stream": True}
        ).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + "/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                for raw in resp:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        obj = json.loads(raw)
                    except Exception:
                        continue
                    if isinstance(obj, dict) and obj.get("error"):
                        if on_error:
                            on_error(str(obj["error"]))
                        return
                    msg = obj.get("message") or {}
                    content = msg.get("content")
                    if content:
                        if on_token:
                            on_token(content)
                    if obj.get("done"):
                        if on_done:
                            on_done()
                        return
            if on_done:
                on_done()
        except Exception as e:  # 连接失败、超时等
            if on_error:
                on_error(str(e))

    def _once_ollama(self, messages, timeout: int = 120) -> str:
        import urllib.request

        payload = json.dumps(
            {"model": self.model, "messages": messages, "stream": False}
        ).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + "/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            obj = json.loads(resp.read().decode("utf-8"))
        if isinstance(obj, dict) and obj.get("error"):
            raise RuntimeError(str(obj["error"]))
        return (obj.get("message") or {}).get("content", "")

    # ---------- OpenAI 兼容 ----------
    def _stream_openai(self, messages, on_token=None, on_done=None, on_error=None):
        import urllib.request

        payload = json.dumps(
            {"model": self.model, "messages": messages, "stream": True}
        ).encode("utf-8")
        req = urllib.request.Request(
            self.base_url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self.api_key,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                for raw in resp:
                    for line in raw.decode("utf-8", "replace").split("\n"):
                        line = line.strip()
                        if not line.startswith("data:"):
                            continue
                        data = line[len("data:"):].strip()
                        if data == "[DONE]":
                            break
                        try:
                            obj = json.loads(data)
                        except Exception:
                            continue
                        choices = obj.get("choices") or []
                        if choices:
                            content = (choices[0].get("delta") or {}).get("content")
                            if content and on_token:
                                on_token(content)
            if on_done:
                on_done()
        except Exception as e:
            if on_error:
                on_error(str(e))

    def _once_openai(self, messages, timeout: int = 120) -> str:
        import urllib.request

        payload = json.dumps(
            {"model": self.model, "messages": messages, "stream": False}
        ).encode("utf-8")
        req = urllib.request.Request(
            self.base_url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self.api_key,
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            obj = json.loads(resp.read().decode("utf-8"))
        choices = obj.get("choices") or []
        if choices:
            return (choices[0].get("message") or {}).get("content", "")
        return ""


def list_ollama_models(base_url: str = "http://127.0.0.1:11434", timeout: int = 5) -> list:
    """列出本机 Ollama 已拉取的模型名（用于设置页自动检测，失败返回空列表）。"""
    import urllib.request

    url = (base_url or "http://127.0.0.1:11434").rstrip("/") + "/api/tags"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            obj = json.loads(resp.read().decode("utf-8"))
        out = []
        for m in (obj.get("models") or []):
            name = m.get("model") or m.get("name")
            if name and name not in out:
                out.append(name)
        return out
    except Exception:
        return []


# 向后兼容别名（main.py 旧代码仍可 import OllamaClient）
OllamaClient = ChatClient


def web_search(query: str, max_results: int = 4) -> str:
    """联网搜索：天气优先用 Open-Meteo 结构化 API（非搜索引擎，仅天气）；
    其它查询只用「必应国内版」和「百度」两个搜索引擎，去掉 360/搜狗/神马/DDG 等。
    两个引擎并行，收集结果后去重择优返回。任一引擎成功即可给出答案。
    所有端点超时 4~5s，整体通常 1~3s 完成。
    """
    import html as _html
    import json
    import re
    import urllib.parse
    import urllib.request
    from concurrent.futures import ThreadPoolExecutor, as_completed

    UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    MOBILE_UA = ("Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 "
                 "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")
    TIMEOUT = 4

    def _clean(s: str) -> str:
        s = _html.unescape(s or "")
        s = re.sub(r"<script[^>]*>.*?</script>", " ", s, flags=re.S)
        s = re.sub(r"<style[^>]*>.*?</style>", " ", s, flags=re.S)
        s = re.sub(r"<[^>]+>", " ", s)
        s = re.sub(r"&[a-zA-Z0-9#]+;", " ", s)
        return re.sub(r"\s+", " ", s).strip(" ·-:")

    def _title_from_heading(tag_html: str) -> str:
        """从 h2/h3 里优先提取 <a> 的文本，否则提取整个标题文本。"""
        if not tag_html:
            return ""
        a = re.search(r'<a\b[^>]*>(.*?)</a>', tag_html, re.S)
        return _clean(a.group(1)) if a else _clean(tag_html)

    def _get(url: str, timeout: int = TIMEOUT, max_len: int = 200000, ua: str = UA, headers: dict = None) -> str:
        h = {
            "User-Agent": ua,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/json,*/*;q=0.8",
        }
        if headers:
            h.update(headers)
        req = urllib.request.Request(url, headers=h)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read(max_len).decode("utf-8", "replace")

    def _get_json(url: str, timeout: int = TIMEOUT):
        return json.loads(_get(url, timeout=timeout))

    def _extract_city(q: str) -> str:
        m = re.search(r"([\u4e00-\u9fa5]{2,7}(?:市|县|区)?)(?:天气|气温|温度|的)?", q)
        if m:
            return m.group(1).replace("天气", "").replace("气温", "").replace("温度", "").strip() or m.group(1)
        m = re.search(r"([\u4e00-\u9fa5]{2,4})(?:天气|气温|温度)?", q)
        return m.group(1) if m else ""

    def _openmeteo(q: str, n: int):
        """使用 Open-Meteo（主）+ 中国天气网（兜底，国内免 key）获取当前天气。"""
        if "天气" not in q and "气温" not in q and "温度" not in q:
            return []
        city = _extract_city(q)
        if not city:
            return []

        def _fmt(name, desc, temp, wind):
            parts = [f"{name}当前天气"]
            if desc:
                parts.append(desc)
            if temp is not None:
                parts.append(f"气温 {temp}°C")
            if wind is not None:
                parts.append(f"风速 {wind} km/h")
            if len(parts) > 1:
                return ["，".join(parts) + "。"]
            return []

        # 主源：Open-Meteo
        try:
            geo = _get_json(
                "https://geocoding-api.open-meteo.com/v1/search?"
                + urllib.parse.urlencode({"name": city, "count": "1", "language": "zh", "format": "json"}),
                timeout=10,
            )
            results = geo.get("results") or []
            if results:
                loc = results[0]
                lat = loc.get("latitude")
                lon = loc.get("longitude")
                if lat is not None and lon is not None:
                    weather = _get_json(
                        "https://api.open-meteo.com/v1/forecast?"
                        + urllib.parse.urlencode({
                            "latitude": str(lat), "longitude": str(lon),
                            "current_weather": "true", "timezone": "auto",
                        }),
                        timeout=10,
                    )
                    cw = weather.get("current_weather", {})
                    r = _fmt(loc.get("name", city), WMO.get(cw.get("weathercode", -1), ""),
                             cw.get("temperature"), cw.get("windspeed"))
                    if r:
                        return r
        except Exception:
            pass

        # 兜底：中国天气网
        try:
            cn_headers = {"Referer": "http://www.weather.com.cn/"}
            s = _get(
                "http://toy1.weather.com.cn/search?" + urllib.parse.urlencode({"cityname": city}),
                timeout=8, headers=cn_headers,
            )
            arr = json.loads(s.strip().lstrip("(").rstrip(")"))
            if arr:
                code_id = str(arr[0].get("ref", "")).split("~")[0]
                if code_id:
                    raw = _get(f"http://d1.weather.com.cn/sk_2d/{code_id}.html", timeout=8, headers=cn_headers)
                    import re
                    m = re.search(r"var dataSK=(\{.*?\})", raw, re.S)
                    if m:
                        d = json.loads(m.group(1))
                        desc = d.get("weather") or ""
                        wse = d.get("wse", "")
                        wm = re.match(r"([\d.]+)", str(wse))
                        wind = float(wm.group(1)) if wm else None
                        r = _fmt(d.get("cityname", city), desc, d.get("temp"), wind)
                        if r:
                            return r
        except Exception:
            pass
        return []

    def _bing_cn(q: str, n: int):
        """必应国内版（cn.bing.com），优先取 b_algo 卡片的标题+摘要。"""
        items = []
        try:
            html = _get(
                "https://cn.bing.com/search?q=" + urllib.parse.quote(q) + "&setlang=zh-CN&cc=CN",
                timeout=TIMEOUT,
            )
        except Exception:
            return items
        for b in re.findall(r'<li class="b_algo".*?</li>', html, re.S):
            t = re.search(r'<h2[^>]*>(.*?)</h2>', b, re.S)
            s = re.search(r'<p[^>]*>(.*?)</p>', b, re.S)
            title = _title_from_heading(t.group(1)) if t else ""
            snip = _clean(s.group(1)) if s else ""
            if title or snip:
                items.append(f"{title}。{snip}" if (title and snip) else (title or snip))
            if len(items) >= n:
                return items
        if not items:
            for t in re.findall(r'<h2[^>]*>(.*?)</h2>', html, re.S):
                txt = _title_from_heading(t)
                if txt:
                    items.append(txt)
                if len(items) >= n:
                    return items
        return items

    def _baidu(q: str, n: int):
        """百度搜索：优先移动端 m.baidu.com（HTML 更完整），失败回退 PC 端。"""
        items = []
        for host, ua in (("https://m.baidu.com", MOBILE_UA), ("https://www.baidu.com", UA)):
            try:
                html = _get(
                    f"{host}/s?wd=" + urllib.parse.quote(q) + "&rn=10&cl=3",
                    timeout=TIMEOUT,
                    ua=ua,
                )
            except Exception:
                continue
            # 移动端常见卡片 class：c-result、c-container、result
            block_pats = [
                r'<div class="c-result[^"]*"[^>]*>.*?</div>\s*</div>\s*</div>',
                r'<div class="c-container[^"]*"[^>]*>.*?</div>\s*</div>\s*</div>',
                r'<div class="result[^"]*"[^>]*>.*?</div>\s*</div>',
            ]
            for pat in block_pats:
                for b in re.findall(pat, html, re.S):
                    t = re.search(r"<h3[^>]*>(.*?)</h3>", b, re.S)
                    s = re.search(r'<p[^>]*>(.*?)</p>', b, re.S)
                    title = _title_from_heading(t.group(1)) if t else ""
                    snip = _clean(s.group(1)) if s else ""
                    if title:
                        items.append(f"{title}。{snip}" if snip else title)
                    if len(items) >= n:
                        return items
            if not items:
                for t in re.findall(r"<h3[^>]*>(.*?)</h3>", html, re.S)[:n]:
                    txt = _title_from_heading(t)
                    if txt:
                        items.append(txt)
            if items:
                return items
        return items

    # 清理查询词，去掉常见前缀
    q = query.strip()
    for prefix in ("查一下", "查", "搜索一下", "搜索", "搜一下", "搜", "告诉我", "问一下", "请问"):
        if q.startswith(prefix):
            q = q[len(prefix):].strip()
            break

    last_err = None
    is_weather = "天气" in q or "气温" in q or "温度" in q
    if is_weather:
        try:
            items = _openmeteo(q, max_results)
            if items:
                return "\n".join(items[:max_results])
        except Exception as e:
            last_err = e
        engines = [("bing_cn", _bing_cn), ("baidu", _baidu)]
    else:
        engines = [("bing_cn", _bing_cn), ("baidu", _baidu)]

    # 并行搜索，收集所有引擎结果后再择优，比“谁先返回用谁”更稳
    all_items = []
    ex = ThreadPoolExecutor(max_workers=len(engines))
    futs = {ex.submit(fn, q, max_results * 2): name for name, fn in engines}
    try:
        for fut in as_completed(futs, timeout=TIMEOUT + 2):
            try:
                items = fut.result()
                if items:
                    all_items.extend(items)
            except Exception as e:
                last_err = e
    except Exception as e:
        last_err = e
    finally:
        ex.shutdown(wait=False)

    if not all_items:
        raise RuntimeError(str(last_err) if last_err else "未找到搜索结果")

    # 去重 + 择优：优先有标题+摘要、长度适中的结果
    seen = set()
    deduped = []
    for item in sorted(all_items, key=lambda x: (0 if "。" in x else 1, -len(x))):
        key = re.sub(r"\s+", "", item)[:48]
        if key and key not in seen:
            seen.add(key)
            deduped.append(item)
            if len(deduped) >= max_results:
                break
    return "\n".join(deduped[:max_results])


class ChatMemory:
    """滚动摘要长记忆。"""

    def __init__(self, path: Path, pet_name: str = "苏璃"):
        self.path = Path(path)
        self.pet_name = pet_name
        self.summary = ""
        self.recent = []  # [{"role": "user"/"assistant", "content": str}, ...]
        self.max_recent = 10
        self.load()

    def load(self):
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.summary = data.get("summary", "")
                self.recent = data.get("recent", [])
            except Exception:
                self.summary, self.recent = "", []

    def save(self):
        try:
            self.path.write_text(
                json.dumps(
                    {"summary": self.summary, "recent": self.recent},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception:
            pass

    def add_turn(self, role: str, content: str):
        self.recent.append({"role": role, "content": content})
        if len(self.recent) > self.max_recent:
            self._trim()
        self.save()

    def _trim(self):
        # 仅裁剪，压缩交由 condense() 在外部显式调用（需要模型）
        half = len(self.recent) // 2
        self.recent = self.recent[half:]

    def build_messages(self, persona: str) -> list:
        # 人设保持原样，不自动替换角色名；记忆摘要/近期对话做兜底清理
        sys_text = persona
        if self.summary.strip():
            sys_text += (
                "\n\n以下是你记得的与主人过往（长期记忆摘要）：\n" + self.summary.strip()
            )
        msgs = [{"role": "system", "content": sys_text}]
        for m in self.recent:
            msgs.append({"role": m["role"], "content": m["content"]})
        return msgs

    def condense(self, client: OllamaClient):
        """把较早的一半对话压缩进 summary（长期记忆）。无 client 或过短则跳过。"""
        if client is None or len(self.recent) <= 4:
            return
        old = self.recent[: len(self.recent) // 2]
        rest = self.recent[len(self.recent) // 2 :]
        transcript = "\n".join(
            f"{'主人' if m['role'] == 'user' else self.pet_name}：{m['content']}"
            for m in old
        )
        prompt = (
            "请用 2-3 句话总结下面这段对话的要点，保留主人的偏好、重要事实与情绪，"
            "不要复述原句：\n" + transcript
        )
        try:
            new_summary = client.chat_once(
                [
                    {"role": "system", "content": "你是记忆压缩器，只输出摘要本身，不要任何解释。"},
                    {"role": "user", "content": prompt},
                ],
                timeout=120,
            ).strip()
        except Exception:
            return
        if not new_summary:
            return
        self.summary = (self.summary + " " + new_summary).strip() if self.summary else new_summary
        self.recent = rest
        self.save()

    def clear(self):
        self.summary = ""
        self.recent = []
        self.save()


class ChatWorker(QThread):
    """后台流式调用 Worker。req_id 用于区分并发请求，防止旧 Worker 的回调污染当前对话。

    若传入 search_query，则在后台线程内先联网搜索（不阻塞 UI），把结果作为 system 指令
    注入后再调用模型；搜索失败则注入“搜索失败”提示，由模型自行回答（优雅降级）。
    """

    token = Signal(str, int)
    finished = Signal(int)
    error = Signal(str, int)

    def __init__(
        self,
        client: OllamaClient,
        messages: list,
        req_id: int = 0,
        search_query: str = None,
        search_instruction: str = "",
        search_failed_instruction: str = "",
    ):
        super().__init__()
        self.client = client
        self.messages = messages
        self.req_id = req_id
        self.search_query = search_query
        self.search_instruction = search_instruction
        self.search_failed_instruction = search_failed_instruction

    def run(self):
        msgs = list(self.messages)
        if self.search_query:
            try:
                ctx = web_search(self.search_query, max_results=4)
                extra = self.search_instruction + "\n" + ctx
            except Exception as e:
                extra = self.search_failed_instruction.format(str(e))[:500]
            # 把搜索上下文追加到最后一条 user 消息里，小模型更容易关注
            injected = False
            for i in range(len(msgs) - 1, -1, -1):
                if msgs[i].get("role") == "user":
                    msgs[i]["content"] = msgs[i].get("content", "") + "\n\n" + extra
                    injected = True
                    break
            if not injected:
                msgs.append({"role": "user", "content": extra})

        self.client.stream_chat(
            msgs,
            on_token=lambda t: self.token.emit(t, self.req_id),
            on_done=lambda: self.finished.emit(self.req_id),
            on_error=lambda e: self.error.emit(e, self.req_id),
        )
