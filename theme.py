"""主题引擎：把硬编码的 UI 配色抽成可切换的主题。

设计要点
--------
- 默认主题色与旧版硬编码值完全一致，因此不切主题时外观零变化（零回归）。
- 所有 `setStyleSheet("...")` 调用经由 `recolor()` 把旧 hex 映射成当前主题色。
  映射由 `_BASE_MAP` 维护：旧硬编码 hex -> 主题键。
- 换肤 = 修改全局 `THEME` 后重建相关对话框即可（启动器/设置工具会提示重启或即时重建）。
"""

import re
from dataclasses import dataclass, field
from typing import Dict, Optional


# 旧硬编码 hex（已归一化为 6 位）-> 主题键。recolor 只会把这里收录的色换成当前主题色，
# 其余语义色（状态条/天气蓝/悬停变体/固定棕字 #4a2c3a 等）保持原样，避免误伤或改变默认外观。
_BASE_MAP: Dict[str, str] = {
    "#d6336c": "accent",
    "#a61e4d": "accent_dark",
    "#ffd6e7": "accent_light",
    "#ffc2dc": "accent_hover",
    "#fff0f6": "panel_bg",
    "#333333": "text",
    "#999999": "text_secondary",
    "#ff9ec2": "border",
}

# 默认苏璃配色（红色系，适配狐妖少女形象）
DEFAULT_THEME_COLORS: Dict[str, str] = {
    "accent": "#e03131",
    "accent_dark": "#b02525",
    "accent_light": "#ffc9c9",
    "accent_hover": "#ffa8a8",
    "panel_bg": "#fff5f5",
    "text": "#333333",
    "text_secondary": "#999999",
    "border": "#ffa8a8",
    "input_bg": "#ffffff",
}

# 设置工具里可编辑的主题键（其余键自动派生于这些）
EDITABLE_KEYS = ("accent", "accent_dark", "panel_bg", "text", "border")


@dataclass
class Theme:
    name: str = "silver_moon"
    colors: Dict[str, str] = field(default_factory=lambda: dict(DEFAULT_THEME_COLORS))

    def get(self, key: str, default: str = "#000000") -> str:
        return self.colors.get(key, default)

    def set(self, key: str, value: str) -> None:
        self.colors[key] = value

    def to_dict(self) -> dict:
        return {"name": self.name, "colors": dict(self.colors)}

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "Theme":
        if not isinstance(d, dict):
            return cls()
        name = d.get("name", "custom")
        colors = dict(DEFAULT_THEME_COLORS)
        if isinstance(d.get("colors"), dict):
            colors.update({k: str(v) for k, v in d["colors"].items()})
        t = cls(name=name)
        t.colors = colors
        return t


# 全局当前主题（main.py 在 load_config 时按配置覆盖）
THEME = Theme()


def set_theme(theme: Theme) -> None:
    """替换全局主题。之后新创建的控件样式自动套用新主题色。"""
    global THEME
    THEME = theme


_HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}")


def _norm(h: str) -> str:
    """归一化 3 位简写：#abc -> #aabbcc。"""
    h = h.lower()
    if len(h) == 4:
        h = "#" + "".join(c * 2 for c in h[1:])
    return h


def recolor(style: str) -> str:
    """把样式串里收录的旧硬编码 hex 换成当前主题对应色。

    按独立 hex token 匹配（正则），不会把 '#333' 当成 '#333333' 的子串来替换，
    因此不会产生非法颜色或误伤其它色值。
    """
    if not isinstance(style, str):
        return style

    def _repl(m):
        key = _BASE_MAP.get(_norm(m.group(0)))
        if key is None:
            return m.group(0)
        return THEME.get(key, m.group(0))

    return _HEX_RE.sub(_repl, style)
