"""
通用桌宠 · 养成状态模块（真实时间活动版）

五维状态：
- mood（心情）0-100
- hunger（饥饿）0-100
- affection（好感）0-100
- stamina（体力）0-100   —— 打工/旅行消耗，睡眠与在线缓慢恢复
- coins（灵石）整数     —— 打工赚取，购买食物/玩具，不会随离线衰减

真实时间活动：
- 打工 / 旅行 / 睡觉都需要消耗真实时间，活动期间不能再进行冲突行为。
- 体力过低（<20）时只能睡觉，不能打工/旅行。
- 心情过低（<25）时不能打工。
- 打工/旅行未结束时不能睡觉或反向操作。
- 活动状态持久化到 status.json，离线期间也会计算时间。

背包 inventory：{物品名: 数量} —— 购买后进入背包，可取出喂食/玩耍。
"""
import json
import random
import time
from pathlib import Path


# ---------- 自然衰减/恢复（每分钟）----------
HUNGER_DECAY_PER_MIN = 0.5
MOOD_DECAY_PER_MIN = 0.25
STAMINA_REGEN_AWAKE = 0.12
STAMINA_REGEN_SLEEP = 1.2
HUNGER_LOW_THRESHOLD = 30
HUNGER_LOW_MOOD_PENALTY = 0.4
STAMINA_LOW_THRESHOLD = 20
STAMINA_LOW_MOOD_PENALTY = 0.3
HUNGER_ZERO_AFFECTION_PENALTY = 0.05

# 心情/体力阈值（生活逻辑）
MOOD_TOO_LOW_FOR_WORK = 25
STAMINA_TOO_LOW_FOR_ACTIVITY = 20

# 可选时长（小时）
WORK_DURATIONS = [1, 2, 4, 8]
TRAVEL_DURATIONS = [1, 2, 4, 8]
SLEEP_DURATIONS = [1, 2, 4, 8]
ACTIVITY_MAX_HOURS = 8


def _clamp(v, lo=0, hi=100):
    return max(lo, min(hi, int(round(v))))


# ---------- 打工 ----------
WORK_JOBS = {
    "采药": {"stamina": -25, "mood": -5, "hunger": -5, "coins": 20,
             "bubble": "去后山采药啦，虽辛苦但能换灵石~"},
    "护卫": {"stamina": -40, "mood": -8, "hunger": -8, "coins": 40,
             "bubble": "替人护法，虽累但桌宠很可靠！"},
    "摆摊": {"stamina": -15, "mood": -3, "hunger": -3, "coins": 12,
             "bubble": "摆个小摊卖灵物，轻松赚灵石~"},
}

# 旅行
TRAVEL = {"stamina": -25, "mood": 18, "hunger": -8, "affection": 1,
          "bubble": "出门旅行啦！风好舒服，桌宠最开心~"}

# 商店
SHOP = {
    "灵果": {"cost": 8, "kind": "food", "hunger": 15, "mood": 3, "affection": 1,
             "bubble": "吃灵果，甜丝丝~"},
    "仙桃": {"cost": 18, "kind": "food", "hunger": 30, "mood": 6, "affection": 3,
             "bubble": "仙桃好水灵，喜欢！"},
    "灵膳": {"cost": 25, "kind": "food", "hunger": 45, "mood": 8, "affection": 2,
             "bubble": "吃了一顿灵膳，好满足~"},
    "糕点": {"cost": 6, "kind": "food", "hunger": 10, "mood": 2, "affection": 1,
             "bubble": "吃点糕点，香香的~"},
    "拨浪鼓": {"cost": 10, "kind": "toy", "affection": 4, "mood": 2,
               "bubble": "摇起拨浪鼓，咚咚咚~"},
    "玉如意": {"cost": 20, "kind": "toy", "affection": 8, "mood": 4,
               "bubble": "玉如意真好看，喜欢！"},
    "木剑": {"cost": 14, "kind": "toy", "affection": 5, "mood": 3,
             "bubble": "挥舞小木剑，耍一套剑法~"},
}
PLAY_OUTSIDE = TRAVEL  # 兼容旧别名

# 随机见闻
WORK_FLAVORS = {
    "采药": ["采到一株百年灵芝", "发现一片灵草丛", "遇见一只搬松果的小松鼠"],
    "护卫": ["护送商队平安抵达", "击退几只低阶妖兽", "结识一位有趣的散修"],
    "摆摊": ["卖掉不少手作香囊", "遇到一位大方的客人", "摊位前围了几个小朋友"],
}
TRAVEL_FLAVORS = [
    "山脚的桃花开得正好", "在溪边喝了一口清甜的泉水", "遇见几只彩色的灵蝶",
    "捡到一片漂亮的枫叶", "听到远处传来悠扬的琴声", "云朵像棉花糖一样软",
]


class PetStatus:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.mood = 80
        self.hunger = 85
        self.affection = 40
        self.stamina = 100
        self.coins = 20
        self.sleeping = False
        self.inventory = {}
        self.last_ts = time.time()
        # 真实时间活动
        self.activity_kind = None   # None / "work" / "travel" / "sleep"
        self.activity_job = None    # 仅 work 用
        self.activity_start = 0.0
        self.activity_end = 0.0
        self.load()

    # ---------- 持久化 ----------
    def load(self):
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.mood = float(data.get("mood", self.mood))
                self.hunger = float(data.get("hunger", self.hunger))
                self.affection = float(data.get("affection", self.affection))
                self.stamina = float(data.get("stamina", self.stamina))
                self.coins = int(data.get("coins", self.coins))
                self.sleeping = bool(data.get("sleeping", False))
                inv = data.get("inventory", {})
                self.inventory = {k: int(v) for k, v in inv.items() if int(v) > 0}
                self.last_ts = float(data.get("last_ts", time.time()))
                self.activity_kind = data.get("activity_kind") or None
                self.activity_job = data.get("activity_job") or None
                self.activity_start = float(data.get("activity_start", 0))
                self.activity_end = float(data.get("activity_end", 0))
                # 离线补算
                elapsed_min = (time.time() - self.last_ts) / 60.0
                if elapsed_min > 0:
                    self._apply_decay(elapsed_min)
                    # 离线期间可能完成活动
                    self.check_and_finish()
            except Exception:
                pass

    def save(self):
        self.last_ts = time.time()
        try:
            self.path.write_text(
                json.dumps(
                    {
                        "mood": self.mood,
                        "hunger": self.hunger,
                        "affection": self.affection,
                        "stamina": self.stamina,
                        "coins": self.coins,
                        "sleeping": self.sleeping,
                        "inventory": self.inventory,
                        "last_ts": self.last_ts,
                        "activity_kind": self.activity_kind,
                        "activity_job": self.activity_job,
                        "activity_start": self.activity_start,
                        "activity_end": self.activity_end,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception:
            pass

    # ---------- 好感增益因子 ----------
    def _aff_factor(self) -> float:
        a = self.affection
        if a >= 90:
            return 0.25
        if a >= 70:
            return 0.5
        return 1.0

    # ---------- 衰减 ----------
    def _apply_decay(self, minutes: float):
        if self.activity_kind in ("work", "travel"):
            # 出门在外：饥饿缓慢下降，其它不变（消耗已在开始时结算）
            self.hunger = _clamp(self.hunger - 0.05 * minutes)
            return
        if self.sleeping:
            self.stamina = _clamp(self.stamina + STAMINA_REGEN_SLEEP * minutes)
            self.mood = _clamp(self.mood + 0.3 * minutes)
            self.hunger = _clamp(self.hunger - 0.15 * minutes)
            return
        self.hunger = _clamp(self.hunger - HUNGER_DECAY_PER_MIN * minutes)
        self.mood = _clamp(self.mood - MOOD_DECAY_PER_MIN * minutes)
        self.stamina = _clamp(self.stamina + STAMINA_REGEN_AWAKE * minutes)
        if self.hunger < HUNGER_LOW_THRESHOLD:
            self.mood = _clamp(self.mood - HUNGER_LOW_MOOD_PENALTY * minutes)
        if self.stamina < STAMINA_LOW_THRESHOLD:
            self.mood = _clamp(self.mood - STAMINA_LOW_MOOD_PENALTY * minutes)
        if self.hunger <= 0:
            self.affection = _clamp(self.affection - HUNGER_ZERO_AFFECTION_PENALTY * minutes)

    def tick(self, minutes: float = 1.0) -> str:
        """在线定时衰减（默认每分钟调用一次）。若有活动结束，返回结束气泡文案。"""
        self._apply_decay(minutes)
        bubble = self.check_and_finish()
        self.save()
        return bubble

    # ---------- 真实时间活动 ----------
    def is_busy(self) -> bool:
        return self.activity_kind is not None and time.time() < self.activity_end

    def busy_text(self) -> str:
        mapping = {"work": "打工", "travel": "旅行", "sleep": "睡觉"}
        return mapping.get(self.activity_kind, "忙碌")

    def remaining_minutes(self) -> int:
        if not self.is_busy():
            return 0
        return max(0, int((self.activity_end - time.time()) / 60))

    def activity_status_text(self) -> str:
        if not self.is_busy():
            return ""
        kind = self.busy_text()
        if self.activity_kind == "work" and self.activity_job:
            kind = f"{self.activity_job}"
        return f"{kind}中（还剩 {self.remaining_minutes()} 分钟）"

    def _check_can_start(self, kind: str) -> tuple[bool, str]:
        """检查是否能开始某类活动，返回 (可开始, 原因)。"""
        if self.is_busy():
            return False, f"桌宠正在{self.busy_text()}，等回来再{('睡' if kind == 'sleep' else '出发')}吧"
        if kind in ("work", "travel"):
            if self.stamina < STAMINA_TOO_LOW_FOR_ACTIVITY:
                return False, "桌宠太累了，先睡一觉恢复体力吧"
            if kind == "work" and self.mood < MOOD_TOO_LOW_FOR_WORK:
                return False, "桌宠心情不好，没精神打工，先哄哄她吧"
        return True, ""

    def start_activity(self, kind: str, hours: int, job: str = None) -> tuple[bool, str, any]:
        """开始一个真实时间活动。kind: work/travel/sleep。"""
        hours = max(1, min(ACTIVITY_MAX_HOURS, int(hours)))
        ok, reason = self._check_can_start(kind)
        if not ok:
            return False, f"（{reason}）", None

        now = time.time()
        self.activity_kind = kind
        self.activity_job = job if kind == "work" else None
        self.activity_start = now
        self.activity_end = now + hours * 3600

        if kind == "work":
            j = WORK_JOBS.get(job)
            if j is None:
                self._clear_activity()
                return False, "（没有这种差事哦）", None
            # 预先扣除消耗
            self.stamina = _clamp(self.stamina + j["stamina"] * hours)
            self.mood = _clamp(self.mood + j["mood"] * hours)
            self.hunger = _clamp(self.hunger + j["hunger"] * hours)
            self.save()
            return (True, f"主人，桌宠去{job}啦，预计 {hours} 小时后回来赚灵石~", job)

        if kind == "travel":
            self.stamina = _clamp(self.stamina + TRAVEL["stamina"] * hours)
            self.hunger = _clamp(self.hunger + TRAVEL["hunger"] * hours)
            self.save()
            return (True, f"主人，桌宠出门旅行啦，预计 {hours} 小时后回来~", None)

        if kind == "sleep":
            self.sleeping = True
            self.save()
            return (True, f"桌宠去睡啦，预计 {hours} 小时后醒来~", None)

        self._clear_activity()
        return False, "（未知活动）", None

    def check_and_finish(self) -> str:
        """检查当前活动是否结束，若结束则结算并返回结束气泡文案。"""
        if not self.activity_kind or time.time() < self.activity_end:
            return ""
        return self.finish_activity()

    def finish_activity(self) -> str:
        """结算当前活动（不检查时间，调用方确保已到期），返回结束气泡文案。"""
        kind = self.activity_kind
        job = self.activity_job
        hours = max(1.0, (self.activity_end - self.activity_start) / 3600.0)
        self._clear_activity()

        if kind == "work":
            j = WORK_JOBS.get(job, WORK_JOBS["采药"])
            gain = int(round(j["coins"] * hours))
            self.coins += gain
            flavor = random.choice(WORK_FLAVORS.get(job, [""]))
            extra = f"，{flavor}" if flavor else ""
            self.save()
            return f"{j['bubble']}{extra}（打工 {int(hours)} 小时，获得 {gain} 灵石）"

        if kind == "travel":
            self.mood = _clamp(self.mood + TRAVEL["mood"] * hours)
            self.affection = _clamp(self.affection + self._aff_factor() * TRAVEL["affection"] * hours)
            flavor = random.choice(TRAVEL_FLAVORS)
            self.save()
            return f"{TRAVEL['bubble']}，{flavor}（旅行 {int(hours)} 小时）"

        if kind == "sleep":
            self.sleeping = False
            self.save()
            return "睡醒啦，精神满满~"

        return ""

    def cancel_activity(self) -> tuple[bool, str]:
        """取消当前活动（仅睡觉可主动唤醒，打工/旅行已在路上不能取消）。"""
        if not self.is_busy():
            return False, "（桌宠没在忙呀）"
        if self.activity_kind == "sleep":
            self._clear_activity()
            self.sleeping = False
            self.save()
            return True, "（桌宠揉揉眼睛醒来了~）"
        return False, f"（桌宠正在{self.busy_text()}，已经在路上了，等回来吧）"

    def _clear_activity(self):
        self.activity_kind = None
        self.activity_job = None
        self.activity_start = 0.0
        self.activity_end = 0.0

    # ---------- 基础互动 ----------
    def _busy_guard(self) -> tuple[bool, str]:
        if self.is_busy():
            return True, f"（桌宠正在{self.busy_text()}，等回来再互动吧）"
        return False, ""

    def pet(self):
        self.mood = _clamp(self.mood + 1)
        self.save()

    def play(self):
        busy, msg = self._busy_guard()
        if busy:
            return False, msg, None
        self.mood = _clamp(self.mood + 2)
        self.affection = _clamp(self.affection + self._aff_factor() * 1)
        self.hunger = _clamp(self.hunger - 2)
        self.stamina = _clamp(self.stamina - 3)
        self.save()
        return True, "", None

    def feed(self, hunger_gain: int, affection_gain: int = 0, mood_gain: int = 0):
        busy, msg = self._busy_guard()
        if busy:
            return False, msg, None
        self.hunger = _clamp(self.hunger + hunger_gain)
        self.affection = _clamp(self.affection + self._aff_factor() * affection_gain)
        self.mood = _clamp(self.mood + mood_gain)
        self.save()
        return True, "", None

    def reward(self, affection: int = 0, mood: int = 0):
        if mood:
            self.mood = _clamp(self.mood + mood)
        if affection:
            self.affection = _clamp(self.affection + self._aff_factor() * affection)
        self.save()

    # ---------- 经济玩法：商店与背包 ----------
    def buy(self, item: str):
        s = SHOP.get(item)
        if s is None:
            return False, "（店里没有这件东西哦）", None
        if self.coins < s["cost"]:
            return False, f"（灵石不够啦，还差 {s['cost'] - self.coins} 颗）", None
        self.coins -= s["cost"]
        self.inventory[item] = self.inventory.get(item, 0) + 1
        self.save()
        return True, f"把「{item}」放进了背包（花费 {s['cost']} 灵石）", item

    def use_item(self, item: str):
        busy, msg = self._busy_guard()
        if busy:
            return False, msg, None
        if self.inventory.get(item, 0) <= 0:
            return False, "（背包里没有这个哦）", None
        s = SHOP.get(item)
        if s is None:
            return False, "（不认识这件东西）", None
        if s.get("kind") == "food":
            self.hunger = _clamp(self.hunger + s.get("hunger", 0))
            self.mood = _clamp(self.mood + s.get("mood", 0))
            self.affection = _clamp(self.affection + self._aff_factor() * s.get("affection", 0))
            bubble = s.get("bubble", f"吃了{item}~")
        else:
            self.mood = _clamp(self.mood + s.get("mood", 0))
            self.affection = _clamp(self.affection + self._aff_factor() * s.get("affection", 0))
            bubble = s.get("bubble", f"玩了{item}~")
        self.inventory[item] -= 1
        if self.inventory[item] <= 0:
            del self.inventory[item]
        self.save()
        return True, bubble, item

    def set_sleeping(self, value: bool):
        """兼容旧调用：直接设置睡眠状态（会取消当前活动）。"""
        if value:
            # 默认睡 1 小时
            return self.start_activity("sleep", 1)
        return self.cancel_activity()

    # ---------- 文本/展示 ----------
    def summary_text(self) -> str:
        inv = "，".join(f"{k}×{v}" for k, v in self.inventory.items()) if self.inventory else "空"
        parts = [
            f"心情 {_clamp(self.mood)}/100",
            f"饥饿 {_clamp(self.hunger)}/100",
            f"好感 {_clamp(self.affection)}/100",
            f"体力 {_clamp(self.stamina)}/100",
            f"灵石 {self.coins}",
        ]
        if self.is_busy():
            parts.append(self.activity_status_text())
        return "，".join(parts) + f"；背包：{inv}"

    def inventory_text(self) -> str:
        if not self.inventory:
            return "背包空空的，去商店买点东西吧~"
        lines = []
        for item, cnt in self.inventory.items():
            s = SHOP.get(item, {})
            kind = "食物" if s.get("kind") == "food" else "玩具"
            lines.append(f"{item}（{kind}）×{cnt}")
        return "背包里有：" + "、".join(lines)

    def status_hint(self) -> str:
        mood = _clamp(self.mood)
        hunger = _clamp(self.hunger)
        aff = _clamp(self.affection)
        stam = _clamp(self.stamina)
        parts = []
        if self.is_busy():
            parts.append(f"你正在{self.busy_text()}，预计还剩 {self.remaining_minutes()} 分钟")
        if hunger < 30:
            parts.append("你现在有点饿，可以撒娇向主人要吃的或去逛逛商店")
        elif hunger > 80:
            parts.append("你吃得饱饱的，很满足")
        if mood < 30:
            parts.append("你现在心情不太好，说话有点蔫蔫的、想被哄")
        elif mood > 80:
            parts.append("你现在心情超级好，活泼爱撒娇")
        if aff > 80:
            parts.append("你非常喜欢主人，语气可以更亲昵黏人")
        elif aff < 30:
            parts.append("你对主人还不太熟，语气可以礼貌但保持距离")
        if stam < 20:
            parts.append("你很疲惫，说话有气无力，想休息")
        if self.coins <= 0:
            parts.append("你身上没有灵石了，可以出去打工赚一点")
        elif self.coins >= 50:
            parts.append("你攒了不少灵石，可以买喜欢的东西")
        if self.inventory:
            parts.append("背包里有点好东西，可以拿出来吃或玩")
        if self.sleeping and not self.is_busy():
            parts.append("你正在睡觉，被叫醒会有点迷糊")
        return "；".join(parts) if parts else "你状态平和"

    def bars(self):
        return (_clamp(self.mood), _clamp(self.hunger), _clamp(self.affection), _clamp(self.stamina))
