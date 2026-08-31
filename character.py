"""角色包加载器：把"形象"从硬编码 images/ 抽成可替换的角色包目录。

角色包目录约定：
    characters/<character_id>/
        character.json        角色元信息（名称/比例/默认主题/各资源子目录名）
        frames/               常驻动画帧（*.png，透明背景）
        bboxes.json           鼠标点击包围盒（透明 PNG 的不透明像素范围）
        <video>.mp4          常驻动画视频（可选，用于重新抠帧）

向后兼容：若 characters/<id> 不存在，回退到旧版 images/ 目录，保证老工程不崩。
"""
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

DEFAULT_CHARACTER_ID = "su_li"


def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def _resource_dir(name: str) -> Path:
    # 优先用 exe 同目录下的可写副本（用户自定义/抠图写入都落这里），
    # 没有时才回退到打包内的只读 _MEIPASS 副本。
    app = _app_dir() / name
    if app.exists():
        return app
    if getattr(sys, "frozen", False):
        meipass = Path(getattr(sys, "_MEIPASS", ""))
        cand = meipass / name
        if cand.exists():
            return cand
    return app


def characters_root() -> Path:
    return _resource_dir("characters")


def list_characters() -> List[Dict[str, str]]:
    """列出所有可用角色包（含默认苏璃）。"""
    out: List[Dict[str, str]] = []
    root = characters_root()
    if root.exists():
        for d in sorted(root.iterdir()):
            if d.is_dir():
                meta = load_meta(d.name)
                out.append({
                    "id": d.name,
                    "name": meta.get("display_name", meta.get("name", d.name)),
                    "path": str(d),
                })
    if not out:
        # 回退：老工程没有 characters/，把 images 当默认角色
        out.append({"id": DEFAULT_CHARACTER_ID, "name": "苏璃", "path": str(_resource_dir("images"))})
    return out


def character_dir(character_id: str = DEFAULT_CHARACTER_ID) -> Path:
    d = characters_root() / character_id
    if d.exists():
        return d
    return _resource_dir("images")  # 旧版回退


def load_meta(character_id: str = DEFAULT_CHARACTER_ID) -> Dict:
    p = character_dir(character_id) / "character.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def resolve(character_id: str = DEFAULT_CHARACTER_ID) -> Dict:
    """解析角色包各资源路径。缺失时回退到旧 images/。"""
    d = character_dir(character_id)
    meta = load_meta(character_id)

    def path(key: str, default: str) -> Path:
        return d / meta.get(key, default)

    return {
        "id": character_id,
        "dir": d,
        "name": meta.get("name", "苏璃"),
        "display_name": meta.get("display_name", meta.get("name", "苏璃")),
        "ratio": meta.get("ratio", "3:4"),
        "default_theme": meta.get("default_theme", {}),
        "human_frames": path("frames", "frames"),
        "bboxes": path("bboxes", "bboxes.json"),
        "video": path("video", "苏璃动画-常驻.mp4"),
    }
