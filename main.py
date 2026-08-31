"""
通用桌面宠物工具箱 (Universal Desktop Pet Toolbox)
基于 PySide6 的 Windows 桌面宠物程序。

功能：
- 透明无边框窗口、始终置顶（用 Win32 SetWindowPos 切换，不重建窗口）
- 使用角色动画视频的逐帧动作作为常驻循环动画（乒乓循环）
- 左键拖动位置
- 点击角色触发跳跃 / 压扁回弹 / 左右抖动
- 互动时随机弹出中文对话气泡
- 右键菜单：置顶开关、调整大小、设置（透明度/缩放）、退出
- 单实例：重复打开不会留下多余气泡
- 程序关闭时记忆窗口位置、大小、透明度、置顶状态
"""
import ctypes
import json
import random
import re
import shutil
import sys
import winreg
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRect,
    QSequentialAnimationGroup,
    Qt,
    QThread,
    QTimer,
    Signal,
)
from PySide6.QtGui import QAction, QColor, QCursor, QFont, QIcon, QMouseEvent, QPainter, QPixmap, QRegion
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QSystemTrayIcon,
    QPushButton,
    QMessageBox,
    QProgressBar,
    QSlider,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from chat import (ChatMemory, ChatClient, list_ollama_models, ChatWorker, PERSONA,
                   DEFAULT_PERSONAS, now_context, web_search, get_weather)
from status import (PetStatus, WORK_JOBS, PLAY_OUTSIDE, SHOP,
                    WORK_DURATIONS, TRAVEL_DURATIONS, SLEEP_DURATIONS)
from games import launch_game

# ---------- 通用桌宠工具箱：主题引擎 + 角色包 ----------
from theme import recolor, THEME, set_theme, Theme
import character
from character import DEFAULT_CHARACTER_ID

APP_NAME = "通用桌宠"                 # 内部品牌/注册表/单实例标识
APP_WINDOW_TITLE = "通用桌面宠物"      # 主窗口标题（单实例匹配用，保持稳定）

# 全局换肤：所有 setStyleSheet 自动经过 recolor，实现零侵入主题切换（默认主题色=原色，零回归）
try:
    _QWidget = QWidget
    _orig_setStyleSheet = _QWidget.setStyleSheet
    def _themed_setStyleSheet(self, style):
        return _orig_setStyleSheet(self, recolor(style))
    _QWidget.setStyleSheet = _themed_setStyleSheet
except Exception:
    pass

# ---------- 配置 ----------
BASE_WIDTH = 240
BASE_HEIGHT = 320
MIN_SCALE = 0.4
MAX_SCALE = 2.5
MIN_OPACITY = 0.2
MAX_OPACITY = 1.0
FRAME_INTERVAL_MS = 33        # 约 30fps



def _app_dir() -> Path:
    """程序目录：打包后放在 exe 旁边，保证配置/记忆能持久化。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def _resource_dir(name: str) -> Path:
    """资源目录：打包后优先取 PyInstaller 解压目录(_MEIPASS)，否则取程序目录。"""
    if getattr(sys, "frozen", False):
        meipass = Path(getattr(sys, "_MEIPASS", ""))
        cand = meipass / name
        if cand.exists():
            return cand
    return _app_dir() / name


CONFIG_FILE = _app_dir() / "config.json"
STATUS_FILE = _app_dir() / "status.json"


def _memory_file(character_id: str = "") -> Path:
    """每个角色拥有独立的记忆文件，切换角色时互不干扰。"""
    name = (character_id or "default").strip() or "default"
    # 去掉可能的特殊字符，避免非法文件名
    name = re.sub(r'[<>:"/\\|?*\s]+', "_", name).strip("_") or "default"
    return _app_dir() / f"chat_memory_{name}.json"


def _migrate_old_memory(character_id: str):
    """首次启用独立记忆时，仅把旧版 chat_memory.json 迁移给默认角色，避免污染新角色。"""
    if character_id != DEFAULT_CHARACTER_ID:
        return
    old = _app_dir() / "chat_memory.json"
    new = _memory_file(character_id)
    if old.exists() and not new.exists():
        try:
            shutil.copy2(old, new)
        except Exception:
            pass
# 旧版 images/ 仅作为回退资源（角色包缺失时兜底）。各帧目录现在由 character.resolve() 动态给出，
# 见 _resolve_character()。FALLBACK_IMAGE 用于角色包没有任何帧时的最后兜底。
IMAGE_DIR = _resource_dir("images")
FALLBACK_IMAGE = IMAGE_DIR / "01.png"

# AI 对话默认配置（可在设置/右键里扩展，这里给默认值）
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5:3b"

PERSONA_FILE = _app_dir() / "persona.txt"


def load_persona() -> str:
    """读取自定义角色设定；未设置时返回 chat.py 里的默认人设。

    人设文件内容保持原样，不自动替换角色名，方便用户手动修改。
    """
    if PERSONA_FILE.exists():
        try:
            text = PERSONA_FILE.read_text(encoding="utf-8").strip()
            if text:
                return text
        except Exception:
            pass
    return PERSONA


def save_persona(text: str):
    try:
        PERSONA_FILE.write_text(text.strip(), encoding="utf-8")
    except Exception as e:
        print(f"保存角色设定失败: {e}")


BUBBLES = [
    "主人，今天也要开心呀~",
    "{pet_name}在陪着你呢！",
    "戳我干嘛，痒痒的~",
    "要不要一起修仙？",
    "嘿嘿，抓不到我~",
    "快看，我的尾巴会摇！",
    "再戳我就要生气啦~",
    "注意休息，别太累哦~",
    "{pet_name}饿了，想吃点灵石~",
    "今天运势：大吉！",
    "主人好厉害，{pet_name}崇拜你~",
    "嘿嘿，我可是最可爱的桌宠呀！",
]

IDLE_BUBBLES = [
    "发呆中...",
    "好无聊呀~",
    "{pet_name}在守护着桌面~",
    "修仙之路漫漫...",
]

MUTEX_NAME = "SilverMoonPet_SingleInstance_Mutex"

# 热重载请求标记：launcher 写入该文件后，正在运行的桌宠会重新读取配置并即时切换角色/名称/配色
RELOAD_FLAG = Path(__file__).resolve().parent / "reload_request.flag"


# ---------- Win32 置顶（稳定，不重建窗口） ----------
def set_window_topmost(hwnd: int, topmost: bool) -> bool:
    """直接调用 SetWindowPos 切换置顶，避免 Qt setWindowFlags 重建窗口导致隐藏。"""
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_NOACTIVATE = 0x0010
        SWP_SHOWWINDOW = 0x0040
        HWND_TOPMOST = -1
        HWND_NOTOPMOST = -2
        flag = HWND_TOPMOST if topmost else HWND_NOTOPMOST
        user32 = ctypes.windll.user32
        user32.SetWindowPos(
            wintypes.HWND(int(hwnd)),
            wintypes.HWND(flag),
            0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW,
        )
        return True
    except Exception as e:
        print(f"SetWindowPos 失败: {e}")
        return False


def _screen_geo(pet_rect: QRect) -> QRect:
    """取得“宠物所在屏幕”的可视区域。

    多显示器下，必须按宠物中心所在的屏幕来定位气泡/面板/对话框，
    否则会被 QApplication.primaryScreen() 拉回主屏（这就是之前“角色能去副屏、
    但其它框还留在原屏”的根因）。
    """
    try:
        screen = QApplication.screenAt(pet_rect.center())
    except Exception:
        screen = None
    if screen is None:
        screen = QApplication.primaryScreen()
    if screen is not None:
        return screen.availableGeometry()
    return QRect(0, 0, 1920, 1080)


# 用于“心情随天气”的简单分类
_RAINY_CODES = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 85, 86, 95, 96, 99}
_SUNNY_CODES = {0, 1}


class _IOThread(QThread):
    """后台执行一个可能阻塞的 IO 函数（抓网页 / 读文件），结果/异常通过信号回传。"""
    got = Signal(object)
    failed = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.got.emit(self.fn())
        except Exception as e:
            self.failed.emit(str(e))


class BubbleLabel(QLabel):
    """对话气泡标签（独立顶层窗口，但由主窗口统一管理生命周期与置顶）"""

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        self.setStyleSheet(
            "QLabel {"
            "  background-color: #ffffff;"
            "  color: #333333;"
            "  border: 2px solid #ff9ec2;"
            "  border-radius: 14px;"
            "  padding: 8px 12px;"
            "}"
        )
        self.hide()

    def show_text(self, text: str, pet_rect: QRect, scale: float):
        self.setText(text)
        font = self.font()
        font.setPointSize(max(8, int(11 * scale)))
        self.setFont(font)
        self.adjustSize()

        x = pet_rect.center().x() - self.width() // 2
        y = pet_rect.top() - self.height() - int(10 * scale)
        screen_geo = _screen_geo(pet_rect)
        x = max(screen_geo.x(), min(x, screen_geo.x() + screen_geo.width() - self.width()))
        y = max(screen_geo.y(), y)
        self.move(x, y)
        self.show()


class StatusTooltip(QWidget):
    """鼠标悬停时显示在角色上方的透明状态框（独立顶层窗口）。
    采用与聊天面板一致的真实 QProgressBar，风格统一、对齐整齐。"""

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # 让鼠标穿透，避免挡住角色、误触发 leaveEvent
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )

        self.container = QWidget(self)
        self.container.setStyleSheet(
            "QWidget{background:rgba(255,244,249,0.95);border:1.5px solid #ff9ec2;border-radius:12px;}"
            "QLabel{color:#4a2c3a;background:transparent;border:none;}"
            "QProgressBar{background:#ffe3ee;border:1px solid #ffd6e7;border-radius:4px;height:8px;}"
            "QProgressBar::chunk{border-radius:4px;}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.container)

        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        # 顶部：灵石
        self.coin_label = QLabel("💎 灵石 0")
        self.coin_label.setFont(QFont("Microsoft YaHei", 10, QFont.Weight.Bold))
        self.coin_label.setStyleSheet("color:#d6336c;background:transparent;border:none;")
        layout.addWidget(self.coin_label)

        # 天气（悬停状态框内显示）
        self.weather_label = QLabel()
        self.weather_label.setFont(QFont("Microsoft YaHei", 9))
        self.weather_label.setStyleSheet("color:#1c7ed6;background:transparent;border:none;")
        layout.addWidget(self.weather_label)

        # 2x2 进度条网格
        grid = QGridLayout()
        grid.setSpacing(8)
        self.bar_mood, self.val_mood = self._make_bar("#ff6b9d")
        self.bar_hunger, self.val_hunger = self._make_bar("#ffa94d")
        self.bar_aff, self.val_aff = self._make_bar("#ffd43b")
        self.bar_stamina, self.val_stamina = self._make_bar("#69db7c")
        grid.addLayout(self._bar_col("心情", self.bar_mood, self.val_mood), 0, 0)
        grid.addLayout(self._bar_col("饥饿", self.bar_hunger, self.val_hunger), 0, 1)
        grid.addLayout(self._bar_col("好感", self.bar_aff, self.val_aff), 1, 0)
        grid.addLayout(self._bar_col("体力", self.bar_stamina, self.val_stamina), 1, 1)
        layout.addLayout(grid)

        # 底部：活动状态
        self.activity_label = QLabel()
        self.activity_label.setFont(QFont("Microsoft YaHei", 9))
        self.activity_label.setStyleSheet("color:#666;background:transparent;border:none;")
        layout.addWidget(self.activity_label)

        self.hide()

    @staticmethod
    def _make_bar(color: str):
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setTextVisible(False)
        bar.setFixedHeight(8)
        bar.setStyleSheet(
            f"QProgressBar{{background:#ffe3ee;border:1px solid #ffd6e7;border-radius:4px;height:8px;}}"
            f"QProgressBar::chunk{{background:{color};border-radius:4px;}}"
        )
        val = QLabel("0")
        val.setStyleSheet(
            "color:#666;background:transparent;border:none;font-size:10px;"
        )
        val.setFixedWidth(22)
        val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return bar, val

    @staticmethod
    def _bar_col(label: str, bar: QProgressBar, val: QLabel):
        col = QVBoxLayout()
        col.setSpacing(2)
        top = QHBoxLayout()
        lab = QLabel(label)
        lab.setStyleSheet("color:#4a2c3a;background:transparent;border:none;font-size:11px;")
        top.addWidget(lab)
        top.addWidget(val)
        col.addLayout(top)
        col.addWidget(bar)
        return col

    def show_status(self, status, pet_rect: QRect, scale: float, weather=None):
        self.coin_label.setText(f"💎 灵石 {status.coins}")
        self.bar_mood.setValue(max(0, min(100, int(round(status.mood)))))
        self.val_mood.setText(str(self.bar_mood.value()))
        self.bar_hunger.setValue(max(0, min(100, int(round(status.hunger)))))
        self.val_hunger.setText(str(self.bar_hunger.value()))
        self.bar_aff.setValue(max(0, min(100, int(round(status.affection)))))
        self.val_aff.setText(str(self.bar_aff.value()))
        self.bar_stamina.setValue(max(0, min(100, int(round(status.stamina)))))
        self.val_stamina.setText(str(self.bar_stamina.value()))

        if status.is_busy():
            self.activity_label.setText(f"⏳ {status.activity_status_text()}")
            self.activity_label.show()
        elif status.sleeping:
            self.activity_label.setText("😴 睡觉中")
            self.activity_label.show()
        else:
            self.activity_label.hide()

        if weather:
            parts = [f"🌤 {weather.get('city', '')} {weather.get('desc', '')}".strip()]
            if weather.get("temp") is not None:
                parts.append(f"{weather['temp']}°C")
            if weather.get("wind") is not None:
                parts.append(f"风{weather['wind']}km/h")
            self.weather_label.setText("　".join(p for p in parts if p))
            self.weather_label.show()
        else:
            self.weather_label.hide()

        self.adjustSize()
        x = pet_rect.center().x() - self.width() // 2
        y = pet_rect.top() - self.height() - int(10 * scale)
        screen_geo = _screen_geo(pet_rect)
        x = max(screen_geo.x(), min(x, screen_geo.x() + screen_geo.width() - self.width()))
        y = max(screen_geo.y(), y)
        self.move(x, y)
        self.show()


class _ModelDetectThread(QThread):
    """后台检测本机 Ollama 模型列表，避免阻塞 UI。"""
    done = Signal(list)

    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url

    def run(self):
        self.done.emit(list_ollama_models(self.base_url, timeout=5))


class SettingsDialog(QDialog):
    """设置对话框：透明度、大小、置顶、AI 模型（本地 Ollama / 在线 API）与重置"""

    def __init__(self, pet: "SilverMoonPet", parent=None):
        super().__init__(parent)
        self.pet = pet
        self.setWindowTitle(f"{getattr(self.pet, 'pet_name', '桌宠')}桌宠 · 设置")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        container = QWidget(self)
        container.setStyleSheet(
            "QWidget{background:#fff0f6;border:2px solid #ff9ec2;border-radius:16px;}"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(container)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)

        title = QLabel(f"{getattr(self.pet, 'pet_name', '桌宠')}桌宠 · 设置")
        title.setFont(QFont("Microsoft YaHei", 13, QFont.Weight.Bold))
        title.setStyleSheet("color:#d6336c;background:transparent;border:none;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # 透明度
        op_row = QHBoxLayout()
        op_label = QLabel("透明度")
        op_label.setStyleSheet("color:#333;background:transparent;border:none;")
        self.op_value = QLabel()
        self.op_value.setStyleSheet("color:#333;background:transparent;border:none;")
        op_row.addWidget(op_label)
        op_row.addStretch(1)
        op_row.addWidget(self.op_value)
        layout.addLayout(op_row)

        self.op_slider = QSlider(Qt.Orientation.Horizontal)
        self.op_slider.setRange(int(MIN_OPACITY * 100), int(MAX_OPACITY * 100))
        self.op_slider.setValue(int(pet.opacity * 100))
        layout.addWidget(self.op_slider)
        self._update_op_label(self.op_slider.value())
        self.op_slider.valueChanged.connect(self._on_opacity_changed)

        # 缩放
        sc_row = QHBoxLayout()
        sc_label = QLabel("大小")
        sc_label.setStyleSheet("color:#333;background:transparent;border:none;")
        self.sc_value = QLabel()
        self.sc_value.setStyleSheet("color:#333;background:transparent;border:none;")
        sc_row.addWidget(sc_label)
        sc_row.addStretch(1)
        sc_row.addWidget(self.sc_value)
        layout.addLayout(sc_row)

        self.sc_slider = QSlider(Qt.Orientation.Horizontal)
        self.sc_slider.setRange(int(MIN_SCALE * 100), int(MAX_SCALE * 100))
        self.sc_slider.setValue(int(pet.scale * 100))
        layout.addWidget(self.sc_slider)
        self._update_sc_label(self.sc_slider.value())
        self.sc_slider.valueChanged.connect(self._on_scale_changed)

        # 置顶
        self.top_check = QCheckBox("始终置顶")
        self.top_check.setChecked(pet.is_topmost)
        self.top_check.setStyleSheet("color:#333;background:transparent;border:none;")
        self.top_check.toggled.connect(self._on_topmost_toggled)
        layout.addWidget(self.top_check)

        # ---------- AI 模型设置 ----------
        sep = QLabel("— AI 模型 —")
        sep.setStyleSheet("color:#d6336c;background:transparent;border:none;font-weight:bold;")
        layout.addWidget(sep)

        prov_row = QHBoxLayout()
        prov_label = QLabel("类型")
        prov_label.setStyleSheet("color:#333;background:transparent;border:none;")
        self.provider_combo = QComboBox()
        self.provider_combo.addItems([
            "本地 Ollama", "在线 API (OpenAI 兼容)",
        ])
        self.provider_combo.setCurrentIndex(0 if pet.model_provider == "ollama" else 1)
        self.provider_combo.setStyleSheet(
            "background:#fff;border:1px solid #ffd6e7;border-radius:8px;padding:2px 6px;color:#333;")
        prov_row.addWidget(prov_label)
        prov_row.addWidget(self.provider_combo, 1)
        layout.addLayout(prov_row)

        # 在线平台预设（仅在线 API 时有效，选平台自动填入地址）
        plat_row = QHBoxLayout()
        plat_label = QLabel("平台")
        plat_label.setStyleSheet("color:#333;background:transparent;border:none;")
        self.platform_combo = QComboBox()
        self.platform_combo.addItems([
            "自定义", "DeepSeek", "OpenAI", "Moonshot(Kimi)",
            "硅基流动", "智谱 GLM", "阿里云百炼", "豆包（火山引擎）",
        ])
        self.platform_combo.setStyleSheet(
            "background:#fff;border:1px solid #ffd6e7;border-radius:8px;padding:2px 6px;color:#333;")
        plat_row.addWidget(plat_label)
        plat_row.addWidget(self.platform_combo, 1)
        layout.addLayout(plat_row)

        self._api_presets = {
            "DeepSeek": "https://api.deepseek.com",
            "OpenAI": "https://api.openai.com/v1",
            "Moonshot(Kimi)": "https://api.moonshot.cn/v1",
            "硅基流动": "https://api.siliconflow.cn/v1",
            "智谱 GLM": "https://open.bigmodel.cn/api/paas/v4",
            "阿里云百炼": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "豆包（火山引擎）": "https://ark.cn-beijing.volces.com/api/v3",
        }
        self.platform_combo.currentTextChanged.connect(self._on_platform_changed)

        ol_row = QHBoxLayout()
        ol_label = QLabel("Ollama 地址")
        ol_label.setStyleSheet("color:#333;background:transparent;border:none;")
        self.ollama_url_edit = QLineEdit(pet.ollama_url)
        self.ollama_url_edit.setStyleSheet(
            "background:#fff;border:1px solid #ffd6e7;border-radius:8px;padding:2px 6px;color:#333;")
        ol_row.addWidget(ol_label)
        ol_row.addWidget(self.ollama_url_edit, 1)
        layout.addLayout(ol_row)

        m_row = QHBoxLayout()
        m_label = QLabel("模型")
        m_label.setStyleSheet("color:#333;background:transparent;border:none;")
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.setMinimumWidth(120)
        self.model_combo.addItem(pet.model)
        self.model_combo.setCurrentText(pet.model)
        self.model_combo.setStyleSheet(
            "background:#fff;border:1px solid #ffd6e7;border-radius:8px;padding:2px 6px;color:#333;")
        self.detect_btn = QPushButton("检测")
        self.detect_btn.setStyleSheet(
            "QPushButton{background:#ffd6e7;color:#333;border:none;border-radius:8px;padding:4px 10px;}"
            " QPushButton:hover{background:#ffc2dc;}")
        m_row.addWidget(m_label)
        m_row.addWidget(self.model_combo, 1)
        m_row.addWidget(self.detect_btn)
        layout.addLayout(m_row)

        ab_row = QHBoxLayout()
        ab_label = QLabel("API 地址")
        ab_label.setStyleSheet("color:#333;background:transparent;border:none;")
        self.api_base_edit = QLineEdit(pet.api_base)
        self.api_base_edit.setPlaceholderText("https://api.openai.com")
        self.api_base_edit.setStyleSheet(
            "background:#fff;border:1px solid #ffd6e7;border-radius:8px;padding:2px 6px;color:#333;")
        ab_row.addWidget(ab_label)
        ab_row.addWidget(self.api_base_edit, 1)
        layout.addLayout(ab_row)

        ak_row = QHBoxLayout()
        ak_label = QLabel("API Key")
        ak_label.setStyleSheet("color:#333;background:transparent;border:none;")
        self.api_key_edit = QLineEdit(pet.api_key)
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("sk-...（仅存本地）")
        self.api_key_edit.setStyleSheet(
            "background:#fff;border:1px solid #ffd6e7;border-radius:8px;padding:2px 6px;color:#333;")
        ak_row.addWidget(ak_label)
        ak_row.addWidget(self.api_key_edit, 1)
        layout.addLayout(ak_row)

        tip = QLabel("在线 API Key 仅保存在本机配置文件中。")
        tip.setStyleSheet("color:#999;background:transparent;border:none;font-size:10px;")
        layout.addWidget(tip)

        self.provider_combo.currentTextChanged.connect(self._on_provider_changed)
        self.ollama_url_edit.editingFinished.connect(self._apply)
        self.model_combo.currentTextChanged.connect(self._apply)
        self.api_base_edit.editingFinished.connect(self._on_api_base_edited)
        self.api_key_edit.editingFinished.connect(self._apply)
        self.detect_btn.clicked.connect(self._on_detect)

        self._sync_platform_combo()
        self._on_provider_changed(self.provider_combo.currentText())
        if pet.model_provider != "openai":
            self._on_detect()

        # ---------- 通用设置 ----------
        sep2 = QLabel("— 通用 —")
        sep2.setStyleSheet("color:#d6336c;background:transparent;border:none;font-weight:bold;")
        layout.addWidget(sep2)

        w_row = QHBoxLayout()
        w_label = QLabel("天气城市")
        w_label.setStyleSheet("color:#333;background:transparent;border:none;")
        self.weather_city_edit = QLineEdit(pet.weather_city)
        self.weather_city_edit.setPlaceholderText("如 北京")
        self.weather_city_edit.setStyleSheet(
            "background:#fff;border:1px solid #ffd6e7;border-radius:8px;padding:2px 6px;color:#333;")
        self.weather_query_btn = QPushButton("查询")
        self.weather_query_btn.setStyleSheet(
            "QPushButton{background:#fff0f5;color:#d6336c;border:1px solid #ffd6e7;border-radius:8px;"
            "padding:4px 12px;} QPushButton:hover{background:#ffd6e7;}"
        )
        w_row.addWidget(w_label)
        w_row.addWidget(self.weather_city_edit, 1)
        w_row.addWidget(self.weather_query_btn)
        layout.addLayout(w_row)

        self.weather_enabled_check = QCheckBox("启用天气（悬停状态栏显示 + 心情联动）")
        self.weather_enabled_check.setChecked(pet.weather_enabled)
        self.weather_enabled_check.setStyleSheet("color:#333;background:transparent;border:none;")
        layout.addWidget(self.weather_enabled_check)

        self.autostart_check = QCheckBox("开机自动启动")
        self.autostart_check.setChecked(pet.get_autostart())
        self.autostart_check.setStyleSheet("color:#333;background:transparent;border:none;")
        layout.addWidget(self.autostart_check)

        hint = QLabel("全局热键：Ctrl+Alt+S 显隐，Ctrl+Alt+C 唤起聊天")
        hint.setStyleSheet("color:#999;background:transparent;border:none;font-size:10px;")
        layout.addWidget(hint)

        self.weather_city_edit.editingFinished.connect(self._on_weather_changed)
        self.weather_enabled_check.toggled.connect(self._on_weather_changed)
        self.weather_query_btn.clicked.connect(self._on_weather_query_clicked)
        self.autostart_check.toggled.connect(lambda c: self.pet.set_autostart(c))

        # 按钮行
        btn_row = QHBoxLayout()
        reset_btn = QPushButton("重置默认")
        reset_btn.setStyleSheet(
            "QPushButton{background:#ffd6e7;color:#333;border:none;border-radius:10px;"
            "padding:8px 12px;} QPushButton:hover{background:#ffc2dc;}"
        )
        reset_btn.clicked.connect(self._on_reset)
        close_btn = QPushButton("关闭")
        close_btn.setStyleSheet(
            "QPushButton{background:#ff9ec2;color:#fff;border:none;border-radius:10px;"
            "padding:8px 12px;} QPushButton:hover{background:#ff85b3;}"
        )
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(reset_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _update_op_label(self, val: int):
        self.op_value.setText(f"{val}%")

    def _update_sc_label(self, val: int):
        self.sc_value.setText(f"{val / 100:.2f}x")

    def _on_opacity_changed(self, val: int):
        self._update_op_label(val)
        self.pet.set_opacity(val / 100)

    def _on_scale_changed(self, val: int):
        self._update_sc_label(val)
        self.pet.set_scale(val / 100)

    def _on_topmost_toggled(self, checked: bool):
        self.pet.set_topmost(checked)

    def _on_reset(self):
        self.op_slider.setValue(int(MAX_OPACITY * 100))
        self.sc_slider.setValue(100)
        self.top_check.setChecked(True)

    def accept(self):
        """关闭设置对话框前确保所有改动已应用并保存。"""
        self._apply()
        self.pet.save_config()
        super().accept()

    def _on_provider_changed(self, text: str):
        is_online = text.startswith("在线")
        self.api_base_edit.setEnabled(is_online)
        self.api_key_edit.setEnabled(is_online)
        self.platform_combo.setEnabled(is_online)
        self.ollama_url_edit.setEnabled(not is_online)
        self.detect_btn.setEnabled(not is_online)
        if is_online:
            self._sync_platform_combo()
        self._apply()

    def _on_platform_changed(self, name: str):
        if name == "自定义":
            return
        url = self._api_presets.get(name)
        if not url:
            return
        self.api_base_edit.setText(url)
        self._apply()

    def _on_api_base_edited(self):
        self._sync_platform_combo()
        self._apply()

    def _sync_platform_combo(self):
        url = self.api_base_edit.text().strip().rstrip("/")
        matched = "自定义"
        for name, u in self._api_presets.items():
            if url and url == u.rstrip("/"):
                matched = name
                break
        idx = self.platform_combo.findText(matched)
        if idx >= 0:
            self.platform_combo.setCurrentIndex(idx)

    def _apply(self):
        p = self.pet
        p.model_provider = "openai" if self.provider_combo.currentText().startswith("在线") else "ollama"
        p.ollama_url = self.ollama_url_edit.text().strip() or DEFAULT_OLLAMA_URL
        p.model = self.model_combo.currentText().strip() or DEFAULT_MODEL
        p.api_base = self.api_base_edit.text().strip()
        p.api_key = self.api_key_edit.text().strip()
        # 通用设置（对话框构造早期 _on_provider_changed 也可能触发 _apply，此时天气控件尚未创建）
        if hasattr(self, "weather_city_edit"):
            p.weather_city = self.weather_city_edit.text().strip() or "北京"
            p.weather_enabled = self.weather_enabled_check.isChecked()
        p.apply_model_config()

    def _on_weather_changed(self):
        self._apply()
        self.pet.apply_weather_config()
        self.pet.save_config()

    def _on_weather_query_clicked(self):
        """设置页点击「查询」：立即测试天气接口并弹窗提示结果。"""
        city = self.weather_city_edit.text().strip() or "北京"
        self.weather_query_btn.setEnabled(False)
        self.weather_query_btn.setText("查询中")
        QApplication.processEvents()
        try:
            w = get_weather(city)
            if w:
                txt = f"「{w.get('city', city)} {w.get('desc', '')}"
                if w.get("temp") is not None:
                    txt += f"，{w['temp']}°C"
                if w.get("wind") is not None:
                    txt += f"，风{w['wind']}km/h"
                txt += f"」（来源：{w.get('source', '未知')}）"
                QMessageBox.information(self, "天气查询成功", f"成功获取到天气信息：\n{txt}")
            else:
                QMessageBox.warning(self, "天气查询失败", f"未能获取到「{city}」的天气信息，请检查城市名称或网络连接。")
        except Exception as e:
            QMessageBox.critical(self, "天气查询失败", f"查询「{city}」时出错：\n{str(e)[:200]}")
        finally:
            self.weather_query_btn.setEnabled(True)
            self.weather_query_btn.setText("查询")

    def _on_detect(self):
        if self.provider_combo.currentText().startswith("在线"):
            return
        self.detect_btn.setEnabled(False)
        self.detect_btn.setText("检测中")
        self._detect_thread = _ModelDetectThread(
            self.ollama_url_edit.text().strip() or DEFAULT_OLLAMA_URL
        )
        self._detect_thread.done.connect(self._on_detect_done)
        self._detect_thread.start()

    def _on_detect_done(self, models):
        self.detect_btn.setEnabled(True)
        self.detect_btn.setText("检测")
        if not self.isVisible():
            return
        if models:
            current = self.model_combo.currentText().strip()
            self.model_combo.clear()
            self.model_combo.addItems(models)
            if current and current in models:
                self.model_combo.setCurrentText(current)
            elif self.model_combo.count() > 0:
                self.model_combo.setCurrentIndex(0)
            self._apply()
        else:
            self.detect_btn.setToolTip("未检测到模型，请确认 Ollama 已启动")

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() == Qt.MouseButton.LeftButton and getattr(self, "_drag_pos", None) is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()


class PersonaDialog(QDialog):
    """角色设定编辑器：可随时修改角色的人设。"""

    def __init__(self, pet: "SilverMoonPet", parent=None):
        super().__init__(parent)
        self.pet = pet
        self.setWindowTitle(f"{getattr(self.pet, 'pet_name', '桌宠')}桌宠 · 角色设定")
        self.setFixedSize(400, 340)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        container = QWidget(self)
        container.setStyleSheet(
            "QWidget{background:#fff0f6;border:2px solid #ff9ec2;border-radius:16px;}"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(container)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)

        title = QLabel(f"{getattr(self.pet, 'pet_name', '桌宠')} · 角色设定")
        title.setFont(QFont("Microsoft YaHei", 13, QFont.Weight.Bold))
        title.setStyleSheet("color:#d6336c;background:transparent;border:none;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        tip = QLabel("修改后即刻生效，下次启动仍会保留。")
        tip.setStyleSheet("color:#666;background:transparent;border:none;font-size:11px;")
        tip.setWordWrap(True)
        layout.addWidget(tip)

        self.edit = QTextEdit()
        self.edit.setPlainText(pet.persona)
        self.edit.setStyleSheet(
            "QTextEdit{background:#ffffff;border:1px solid #ffd6e7;border-radius:10px;"
            "padding:8px;color:#333;font-size:12px;}"
        )
        layout.addWidget(self.edit, 1)

        btn_row = QHBoxLayout()
        reset_suli_btn = QPushButton("恢复苏璃默认")
        reset_suli_btn.setStyleSheet(
            "QPushButton{background:#ffd6e7;color:#333;border:none;border-radius:10px;"
            "padding:8px 12px;} QPushButton:hover{background:#ffc2dc;}"
        )
        reset_suli_btn.clicked.connect(lambda: self._on_reset_default("苏璃"))
        reset_yinyue_btn = QPushButton("恢复银月默认")
        reset_yinyue_btn.setStyleSheet(
            "QPushButton{background:#ffd6e7;color:#333;border:none;border-radius:10px;"
            "padding:8px 12px;} QPushButton:hover{background:#ffc2dc;}"
        )
        reset_yinyue_btn.clicked.connect(lambda: self._on_reset_default("银月"))
        save_btn = QPushButton("保存")
        save_btn.setStyleSheet(
            "QPushButton{background:#ff9ec2;color:#fff;border:none;border-radius:10px;"
            "padding:8px 12px;} QPushButton:hover{background:#ff85b3;}"
        )
        save_btn.clicked.connect(self._on_save)
        close_btn = QPushButton("取消")
        close_btn.setStyleSheet(
            "QPushButton{background:#ffe0ec;color:#333;border:none;border-radius:10px;"
            "padding:8px 12px;} QPushButton:hover{background:#ffd0e0;}"
        )
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(reset_suli_btn)
        btn_row.addWidget(reset_yinyue_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _on_reset_default(self, name: str = "苏璃"):
        """恢复指定角色的默认人设文本（保持原样，不替换当前 pet_name）。"""
        self.edit.setPlainText(DEFAULT_PERSONAS.get(name, PERSONA))

    def _on_save(self):
        text = self.edit.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "提示", "角色设定不能为空哦~")
            return
        save_persona(text)
        self.pet.persona = text
        self.accept()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() == Qt.MouseButton.LeftButton and getattr(self, "_drag_pos", None) is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()


class ShopDialog(QDialog):
    """商店：用灵石购买食物/玩具，购买后直接进入背包。"""

    def __init__(self, pet: "SilverMoonPet", parent=None):
        super().__init__(parent)
        self.pet = pet
        self.setWindowTitle(f"{getattr(self.pet, 'pet_name', '桌宠')}桌宠 · 商店")
        self.setFixedSize(300, 380)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        container = QWidget(self)
        container.setStyleSheet(
            "QWidget{background:#fff5fa;border:2px solid #ff9ec2;border-radius:16px;}"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(container)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        top = QHBoxLayout()
        title = QLabel("🏪 商店")
        title.setFont(QFont("Microsoft YaHei", 13, QFont.Weight.Bold))
        title.setStyleSheet("color:#d6336c;background:transparent;border:none;")
        top.addWidget(title)
        top.addStretch(1)
        self.coin_label = QLabel(f"💎 {pet.status.coins}")
        self.coin_label.setStyleSheet(
            "color:#e8590c;background:transparent;border:none;font-size:12px;font-weight:bold;"
        )
        top.addWidget(self.coin_label)
        layout.addLayout(top)

        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(
            "QListWidget{background:#fff;border:1px solid #ffd6e7;border-radius:10px;"
            "padding:4px;color:#333;font-size:12px;outline:none;}"
            "QListWidget::item{border:none;background:transparent;padding:2px;}"
            "QListWidget::item:selected{border:none;background:transparent;}"
        )
        self.list_widget.setFrameShape(QListWidget.Shape.NoFrame)
        layout.addWidget(self.list_widget, 1)

        close_btn = QPushButton("关闭")
        close_btn.setStyleSheet(
            "QPushButton{background:#ff9ec2;color:#fff;border:none;border-radius:10px;"
            "padding:6px 12px;} QPushButton:hover{background:#ff85b3;}"
        )
        close_btn.clicked.connect(self.reject)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)

        self.refresh()

    def refresh(self):
        self.list_widget.clear()
        self.coin_label.setText(f"💎 {self.pet.status.coins}")
        foods = [(n, i) for n, i in SHOP.items() if i.get("kind") == "food"]
        toys = [(n, i) for n, i in SHOP.items() if i.get("kind") != "food"]

        def add_header(text: str):
            header = QListWidgetItem(text)
            header.setFlags(header.flags() & ~Qt.ItemFlag.ItemIsEnabled & ~Qt.ItemFlag.ItemIsSelectable)
            header.setBackground(Qt.GlobalColor.transparent)
            self.list_widget.addItem(header)

        def add_items(items: list, kind_name: str):
            if not items:
                return
            add_header(kind_name)
            for idx, (name, info) in enumerate(items):
                row = QWidget()
                row.setStyleSheet("background:transparent;border:none;")
                rlay = QHBoxLayout(row)
                rlay.setContentsMargins(6, 4, 6, 4)
                rlay.setSpacing(6)
                bg_color = "#fff0f6" if idx % 2 == 0 else "#ffffff"
                effect = f"饥饿+{info.get('hunger',0)} 心情+{info.get('mood',0)} 好感+{info.get('affection',0)}" if info.get("kind") == "food" else f"心情+{info.get('mood',0)} 好感+{info.get('affection',0)}"
                lab = QLabel(f"{name}\n{effect}")
                lab.setStyleSheet(f"color:#333;background:{bg_color};border-radius:6px;padding:4px 6px;font-size:11px;")
                lab.setWordWrap(True)
                buy_btn = QPushButton(f"{info['cost']}灵石")
                buy_btn.setFixedSize(56, 28)
                buy_btn.setStyleSheet(
                    "QPushButton{background:#69db7c;color:#fff;border:none;border-radius:8px;"
                    "font-size:10px;font-weight:bold;} QPushButton:hover{background:#51cf66;}"
                )
                buy_btn.clicked.connect(lambda checked, n=name: self._buy(n))
                rlay.addWidget(lab, 1)
                rlay.addWidget(buy_btn)
                item = QListWidgetItem()
                item.setSizeHint(row.sizeHint())
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                self.list_widget.addItem(item)
                self.list_widget.setItemWidget(item, row)

        add_items(foods, "🍎 食物")
        add_items(toys, "🧸 玩具")

    def _buy(self, name: str):
        ok, bubble, _ = self.pet.status.buy(name)
        self.pet.show_bubble(bubble)
        if ok:
            self.pet.animate_squash()
        self.pet._refresh_chat_status()
        self.refresh()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() == Qt.MouseButton.LeftButton and getattr(self, "_drag_pos", None) is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()


class BackpackDialog(QDialog):
    """背包：列出已购物品，可取出喂食 / 玩耍。"""

    def __init__(self, pet: "SilverMoonPet", parent=None):
        super().__init__(parent)
        self.pet = pet
        self.setWindowTitle(f"{getattr(self.pet, 'pet_name', '桌宠')}桌宠 · 背包")
        self.setFixedSize(300, 340)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        container = QWidget(self)
        container.setStyleSheet(
            "QWidget{background:#fff5fa;border:2px solid #ff9ec2;border-radius:16px;}"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(container)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        title = QLabel("🎒 背包")
        title.setFont(QFont("Microsoft YaHei", 13, QFont.Weight.Bold))
        title.setStyleSheet("color:#d6336c;background:transparent;border:none;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(
            "QListWidget{background:#fff;border:1px solid #ffd6e7;border-radius:10px;"
            "padding:4px;color:#333;font-size:12px;outline:none;}"
            "QListWidget::item{border:none;background:transparent;padding:2px;}"
            "QListWidget::item:selected{border:none;background:transparent;}"
        )
        self.list_widget.setFrameShape(QListWidget.Shape.NoFrame)
        layout.addWidget(self.list_widget, 1)

        btn_row = QHBoxLayout()
        refresh_btn = QPushButton("刷新")
        refresh_btn.setStyleSheet(
            "QPushButton{background:#ffe0ec;color:#333;border:none;border-radius:10px;"
            "padding:6px 12px;} QPushButton:hover{background:#ffd0e0;}"
        )
        refresh_btn.clicked.connect(self.refresh)
        close_btn = QPushButton("关闭")
        close_btn.setStyleSheet(
            "QPushButton{background:#ff9ec2;color:#fff;border:none;border-radius:10px;"
            "padding:6px 12px;} QPushButton:hover{background:#ff85b3;}"
        )
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(refresh_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self.refresh()

    def refresh(self):
        self.list_widget.clear()
        inv = self.pet.status.inventory
        if not inv:
            item = QListWidgetItem("（背包空空的，去商店买点东西吧~）")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.list_widget.addItem(item)
            return

        # ---- 商店物品（可喂食 / 玩耍） ----
        if inv:
            header = QListWidgetItem("🎒 物品")
            header.setFlags(header.flags() & ~(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable))
            header.setForeground(Qt.GlobalColor.gray)
            self.list_widget.addItem(header)
            for idx, (name, cnt) in enumerate(inv.items()):
                s = SHOP.get(name, {})
                kind = "食物" if s.get("kind") == "food" else "玩具"
                verb = "喂食" if kind == "food" else "玩耍"
                row = QWidget()
                row.setStyleSheet("background:transparent;border:none;")
                rlay = QHBoxLayout(row)
                rlay.setContentsMargins(6, 4, 6, 4)
                rlay.setSpacing(8)
                bg_color = "#fff0f6" if idx % 2 == 0 else "#ffffff"
                lab = QLabel(f"{name}（{kind}）×{cnt}")
                lab.setStyleSheet(f"color:#333;background:{bg_color};border-radius:6px;padding:4px 6px;")
                use_btn = QPushButton(verb)
                use_btn.setFixedSize(50, 26)
                use_btn.setStyleSheet(
                    "QPushButton{background:#ff9ec2;color:#fff;border:none;border-radius:8px;"
                    "font-size:11px;} QPushButton:hover{background:#ff7aa8;}"
                )
                effect = f"饥饿+{s.get('hunger',0)} 心情+{s.get('mood',0)} 好感+{s.get('affection',0)}" if kind == "食物" else f"心情+{s.get('mood',0)} 好感+{s.get('affection',0)}"
                use_btn.setToolTip(f"{name}：{effect}")
                use_btn.clicked.connect(lambda checked, n=name: self._use(n))
                rlay.addWidget(lab, 1)
                rlay.addWidget(use_btn)
                item = QListWidgetItem()
                item.setSizeHint(row.sizeHint())
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                self.list_widget.addItem(item)
                self.list_widget.setItemWidget(item, row)

    def _use(self, name: str):
        ok, bubble, _ = self.pet.status.use_item(name)
        self.pet.show_bubble(bubble)
        if ok:
            self.pet.animate_squash()
        self.pet._refresh_chat_status()
        self.refresh()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() == Qt.MouseButton.LeftButton and getattr(self, "_drag_pos", None) is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()


class ChatPanel(QWidget):
    """聊天面板：双击角色弹出，可拖动；含历史区、输入框、状态条、角色设定、清空记忆。"""

    send_requested = Signal(str)
    close_requested = Signal()

    def __init__(self, pet: "SilverMoonPet" = None):
        super().__init__()
        self.pet = pet
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(300, 430)
        self._drag_pos = None

        container = QWidget(self)
        container.setStyleSheet(
            "QWidget{background:#fff5fa;border:2px solid #ff9ec2;border-radius:16px;}"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(container)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        # 标题栏（可拖动区域）
        top = QHBoxLayout()
        top.setSpacing(6)
        title = QLabel(f"☰ {self._pn()} · 聊天")
        title.setStyleSheet(
            "color:#d6336c;background:transparent;border:none;font-weight:bold;font-size:13px;"
        )
        title.setToolTip("按住这里可以拖动面板")
        top.addWidget(title)
        self.coin_label = QLabel("💎 0")
        self.coin_label.setStyleSheet(
            "color:#e8590c;background:transparent;border:none;font-size:11px;font-weight:bold;"
        )
        self.coin_label.setToolTip("当前灵石")
        top.addWidget(self.coin_label)
        top.addStretch(1)
        persona_btn = QPushButton("角色设定")
        persona_btn.setFixedSize(54, 24)
        persona_btn.setStyleSheet(
            "QPushButton{background:#e7f5ff;color:#1971c2;border:none;border-radius:8px;font-size:10px;}"
            "QPushButton:hover{background:#d0ebff;}"
        )
        if self.pet is not None:
            persona_btn.clicked.connect(lambda: self.pet.open_persona_editor())
        clear_btn = QPushButton("清空")
        clear_btn.setFixedSize(40, 24)
        clear_btn.setStyleSheet(
            "QPushButton{background:#ffe0ec;color:#333;border:none;border-radius:8px;font-size:10px;}"
            "QPushButton:hover{background:#ffd0e0;}"
        )
        clear_btn.setToolTip("清空本次聊天显示（不影响长期记忆）")
        close_btn = QPushButton("×")
        close_btn.setFixedSize(24, 24)
        close_btn.setStyleSheet(
            "QPushButton{background:#ff9ec2;color:#fff;border:none;border-radius:8px;font-size:14px;}"
            "QPushButton:hover{background:#ff7aa8;}"
        )
        top.addWidget(persona_btn)
        top.addWidget(clear_btn)
        top.addWidget(close_btn)
        layout.addLayout(top)

        # 状态条（2x2 网格，更紧凑）
        self.bar_mood, self.val_mood = self._make_bar("#ff6b9d")
        self.bar_hunger, self.val_hunger = self._make_bar("#ffa94d")
        self.bar_aff, self.val_aff = self._make_bar("#ffd43b")
        self.bar_stamina, self.val_stamina = self._make_bar("#69db7c")
        grid = QGridLayout()
        grid.setSpacing(6)
        grid.addLayout(self._bar_col("心情", self.bar_mood, self.val_mood), 0, 0)
        grid.addLayout(self._bar_col("饥饿", self.bar_hunger, self.val_hunger), 0, 1)
        grid.addLayout(self._bar_col("好感", self.bar_aff, self.val_aff), 1, 0)
        grid.addLayout(self._bar_col("体力", self.bar_stamina, self.val_stamina), 1, 1)
        layout.addLayout(grid)

        # 历史区
        self.text = QTextEdit()
        self.text.setReadOnly(True)
        self.text.setStyleSheet(
            "QTextEdit{background:#ffffff;border:1px solid #ffd6e7;border-radius:10px;"
            "padding:6px;color:#333;font-size:12px;}"
        )
        layout.addWidget(self.text, 1)

        # 输入区
        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        self.input = QLineEdit()
        self.input.setPlaceholderText(f"和{self._pn()}说点什么…")
        self.input.setStyleSheet(
            "QLineEdit{background:#fff;border:1px solid #ffd6e7;border-radius:10px;"
            "padding:6px;color:#333;font-size:12px;}"
        )
        self.input.returnPressed.connect(self._send)
        send_btn = QPushButton("发送")
        send_btn.setFixedSize(50, 30)
        send_btn.setStyleSheet(
            "QPushButton{background:#ff9ec2;color:#fff;border:none;border-radius:10px;font-weight:bold;}"
            "QPushButton:hover{background:#ff7aa8;}"
        )
        send_btn.clicked.connect(self._send)
        bottom.addWidget(self.input, 1)
        bottom.addWidget(send_btn)
        layout.addLayout(bottom)

        self.messages = []  # [(role, text), ...]
        self._thinking_index = None  # 当前“思考中…”占位条目的索引
        clear_btn.clicked.connect(self._clear_memory)
        close_btn.clicked.connect(self.close_requested.emit)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if (
            event.buttons() == Qt.MouseButton.LeftButton
            and self._drag_pos is not None
        ):
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    # ---------- 渲染 ----------
    def _render(self):
        html = ""
        for role, text in self.messages:
            color = "#c2185b" if role == "user" else "#333"
            prefix = "你：" if role == "user" else f"{self._pn()}："
            esc = (
                text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\n", "<br>")
            )
            html += (
                f'<p style="margin:4px 0;">'
                f'<span style="color:{color};font-weight:bold;">{prefix}</span>'
                f'<span style="color:#333;">{esc}</span></p>'
            )
        self.text.setHtml(html)
        self.text.verticalScrollBar().setValue(self.text.verticalScrollBar().maximum())

    # ---------- 状态条 ----------
    @staticmethod
    def _make_bar(color: str):
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setTextVisible(False)
        bar.setFixedHeight(8)
        bar.setStyleSheet(
            f"QProgressBar{{background:#ffe3ee;border:1px solid #ffd6e7;border-radius:4px;}}"
            f"QProgressBar::chunk{{background:{color};border-radius:4px;}}"
        )
        val = QLabel("0")
        val.setStyleSheet(
            "color:#666;background:transparent;border:none;font-size:10px;"
        )
        val.setFixedWidth(18)
        val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return bar, val

    @staticmethod
    def _bar_col(label: str, bar: QProgressBar, val: QLabel):
        col = QVBoxLayout()
        col.setSpacing(2)
        top = QHBoxLayout()
        lab = QLabel(label)
        lab.setStyleSheet("color:#666;background:transparent;border:none;font-size:11px;")
        top.addWidget(lab)
        top.addWidget(val)
        col.addLayout(top)
        col.addWidget(bar)
        return col

    def update_status(self, bars):
        """bars: (mood, hunger, affection, stamina) 0-100"""
        mood, hunger, aff, stamina = bars
        self.bar_mood.setValue(mood)
        self.bar_hunger.setValue(hunger)
        self.bar_aff.setValue(aff)
        self.bar_stamina.setValue(stamina)
        self.val_mood.setText(str(mood))
        self.val_hunger.setText(str(hunger))
        self.val_aff.setText(str(aff))
        self.val_stamina.setText(str(stamina))

    def update_coins(self, coins: int):
        self.coin_label.setText(f"💎 {coins}")

    def add_user(self, text: str):
        self.messages.append(("user", text))
        self._render()

    def _pn(self) -> str:
        return getattr(self.pet, "pet_name", "苏璃") if self.pet else "苏璃"

    def show_thinking(self, placeholder: str = None):
        if placeholder is None:
            placeholder = f"（{self._pn()}思考中…）"
        # 如果上一轮还有未清理的占位，先移除，避免对话错位
        if self._thinking_index is not None:
            idx = self._thinking_index
            if 0 <= idx < len(self.messages) and self.messages[idx][0] == "assistant":
                self.messages.pop(idx)
        self.messages.append(("assistant", placeholder))
        self._thinking_index = len(self.messages) - 1
        self.input.setEnabled(False)
        self._render()

    def append_token(self, tok: str):
        # 有“思考中…”占位时，直接用 token 替换它
        if self._thinking_index is not None:
            idx = self._thinking_index
            if 0 <= idx < len(self.messages) and self.messages[idx][0] == "assistant":
                self.messages[idx] = ("assistant", tok)
            else:
                self.messages.append(("assistant", tok))
            self._thinking_index = None
            self._render()
            return
        if not self.messages or self.messages[-1][0] != "assistant":
            self.messages.append(("assistant", tok))
        else:
            role, text = self.messages[-1]
            self.messages[-1] = (role, text + tok)
        self._render()

    def finish_assistant(self):
        # 流式结束但没有任何 token 时，把占位替换为提示，避免下一轮错位
        if self._thinking_index is not None:
            idx = self._thinking_index
            if 0 <= idx < len(self.messages) and self.messages[idx][0] == "assistant":
                name = getattr(self.pet, "pet_name", "苏璃")
                self.messages[idx] = ("assistant", f"（{name}没有说话）")
            self._thinking_index = None
        self.input.setEnabled(True)
        self.input.setFocus()
        self._render()

    def show_error(self, msg: str):
        if self._thinking_index is not None:
            idx = self._thinking_index
            if 0 <= idx < len(self.messages):
                self.messages.pop(idx)
            self._thinking_index = None
        self.messages.append(("assistant", f"（出错了：{msg}）"))
        self.input.setEnabled(True)
        self.input.setFocus()
        self._render()

    def _send(self):
        t = self.input.text().strip()
        if not t:
            return
        self.input.clear()
        self.send_requested.emit(t)

    def _clear_memory(self):
        self.messages = []
        self._render()
        if self.pet:
            self.pet.clear_memory()

    def position_above(self, pet_rect: QRect, scale: float):
        x = pet_rect.center().x() - self.width() // 2
        y = pet_rect.top() - self.height() - int(10 * scale)
        screen = _screen_geo(pet_rect)
        x = max(screen.x(), min(x, screen.x() + screen.width() - self.width()))
        y = max(screen.y(), y)
        self.move(x, y)


class SilverMoonPet(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_WINDOW_TITLE)
        self.setWindowIcon(self._load_app_icon())
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

        # 通用桌宠：尽早确定角色包 / 名称 / 主题，供帧加载使用
        self.character_id = self._read_character_id()
        self.pet_name = "苏璃"
        self.theme = Theme()
        self._resolve_character()

        # 加载常驻帧序列（人形态）
        self.human_frames = self.load_frames(self.human_frames_dir)
        if not self.human_frames:
            QMessageBox.critical(self, "错误", f"未找到人形态帧序列 {self.human_frames_dir}")
            sys.exit(1)

        # 动画状态
        self.frame_index = 0
        self.frame_direction = 1   # 1: 正放, -1: 倒放（乒乓循环）

        # 角色标签
        self.pet_label = QLabel(self)
        self.pet_label.setScaledContents(True)
        self.pet_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

        # 气泡（独立顶层窗口）
        self.bubble = BubbleLabel(None)
        self.bubble.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.bubble.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # 状态
        self.scale = 1.0
        self.opacity = 1.0
        self._load_bboxes()
        self.apply_mask()
        self.is_topmost = True
        self.dragging = False
        self.last_mouse_pos = QPoint()
        self.interaction_index = 0
        self.animations = []
        self.bubble_timer = QTimer(self)
        self.bubble_timer.setSingleShot(True)
        self.bubble_timer.timeout.connect(self.bubble.hide)

        # 帧动画定时器（人形态常驻）
        self.frame_timer = QTimer(self)
        self.frame_timer.timeout.connect(self.next_frame)
        self.frame_timer.start(FRAME_INTERVAL_MS)

        # 待机气泡
        self.idle_timer = QTimer(self)
        self.idle_timer.timeout.connect(self.idle_tick)
        self.idle_timer.start(5000)

        # 加载配置（含置顶/透明度应用）
        self.load_config()

        # 加载自定义角色设定（保持文件原样，不自动替换角色名）
        self.persona = load_persona()

        # ---------- 养成状态 ----------
        self.status = PetStatus(STATUS_FILE)
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.status_tick)
        self.status_timer.start(60000)  # 每分钟衰减一次

        # 游戏/指令状态（窗口小游戏不需要聊天态变量）

        # ---------- AI 对话相关 ----------
        # 首次启用角色独立记忆时，把旧版单一 chat_memory.json 迁移到当前角色文件，保留现有对话。
        _migrate_old_memory(self.character_id)
        self.chat_memory = ChatMemory(_memory_file(self.character_id), pet_name=self.pet_name)
        self.ollama = ChatClient(
            provider=getattr(self, "model_provider", "ollama"),
            base_url=self.ollama_url,
            model=self.model,
            api_key=getattr(self, "api_key", ""),
            api_base=getattr(self, "api_base", ""),
        )
        self.chat_worker = None
        self._chat_full = ""
        self._chat_reply = ""
        self._chat_req_id = 0
        self._current_req_id = 0
        self._chat_weather_thread = None
        self._chat_weather_city = ""
        self.chat_panel = ChatPanel(self)
        self.chat_panel.send_requested.connect(self.start_chat)
        self.chat_panel.close_requested.connect(self.close_chat)
        # 单击/双击区分：单击 220ms 后触发互动，双击则开聊天
        self.click_timer = QTimer(self)
        self.click_timer.setSingleShot(True)
        self.click_timer.timeout.connect(self.trigger_interaction)

        # ---------- 鼠标悬停状态提示 ----------
        self.status_tooltip = StatusTooltip()
        self.hover_timer = QTimer(self)
        self.hover_timer.setSingleShot(True)
        self.hover_timer.timeout.connect(self._show_hover_status)

        # ---------- 系统托盘 ----------
        self._setup_tray()

        # ---------- 天气（仅在悬停状态栏显示 + 心情联动，不再有角色底部浮层标签） ----------
        self.weather = None
        self.weather_error = ""  # 最近一次天气获取失败的说明，供“查看天气”显示
        self.weather_timer = QTimer(self)
        self.weather_timer.timeout.connect(self._fetch_weather)
        self._io_thread = None  # 复用的后台 IO 线程

        # ---------- 全局热键 ----------
        self._hk_ids = {"toggle": 1, "chat": 2}
        self._setup_hotkeys()

        # 应用天气配置（立即拉一次）
        self.apply_weather_config()

        self.apply_scale()

    # ---------- 帧加载 ----------
    def load_frames(self, directory: Path) -> list[QPixmap]:
        frames = []
        if directory.exists():
            paths = sorted(directory.glob("*.png"))
            for p in paths:
                pm = QPixmap(str(p))
                if not pm.isNull():
                    frames.append(pm)
        if not frames and FALLBACK_IMAGE.exists():
            pm = QPixmap(str(FALLBACK_IMAGE))
            if not pm.isNull():
                frames.append(pm)
        return frames

    # ---------- 配置持久化 ----------
    def load_config(self):
        # AI 对话默认值先就位
        self.ollama_url = DEFAULT_OLLAMA_URL
        self.model = DEFAULT_MODEL
        self.model_provider = "ollama"
        self.api_base = ""
        self.api_key = ""
        # 天气 / 通用设置默认值
        self.weather_city = "北京"
        self.weather_enabled = True
        self.autostart = False
        self.character_id = DEFAULT_CHARACTER_ID
        self.pet_name = "苏璃"
        self.theme = Theme()
        if CONFIG_FILE.exists():
            try:
                cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                x = cfg.get("x", 100)
                y = cfg.get("y", 100)
                self.scale = float(cfg.get("scale", 1.0))
                self.opacity = float(cfg.get("opacity", 1.0))
                self.is_topmost = bool(cfg.get("topmost", True))
                self.ollama_url = cfg.get("ollama_url", DEFAULT_OLLAMA_URL)
                self.model = cfg.get("model", DEFAULT_MODEL)
                self.model_provider = cfg.get("model_provider", "ollama")
                self.api_base = cfg.get("api_base", "")
                # 兼容旧版误存的 responses 协议：统一改回 chat completions 端点
                if cfg.get("model_protocol") == "responses" and self.api_base:
                    self.api_base = self.api_base.replace("/responses", "/chat/completions")
                self.api_key = cfg.get("api_key", "")
                self.weather_city = cfg.get("weather_city", "北京")
                self.weather_enabled = bool(cfg.get("weather_enabled", True))
                self.autostart = bool(cfg.get("autostart", False))
                old_character_id = self.character_id
                self.character_id = cfg.get("character_id", DEFAULT_CHARACTER_ID)
                self.pet_name = cfg.get("pet_name", "苏璃")
                # 角色发生切换时，使用对应角色的独立记忆文件，避免记忆串台
                if getattr(self, "chat_memory", None) is not None:
                    if old_character_id != self.character_id:
                        self.chat_memory.save()
                        self.chat_memory = ChatMemory(
                            _memory_file(self.character_id), pet_name=self.pet_name
                        )
                    else:
                        self.chat_memory.pet_name = self.pet_name
                        self.chat_memory.save()
                theme_dict = cfg.get("theme")
                if isinstance(theme_dict, dict):
                    self.theme = Theme.from_dict(theme_dict)
                set_theme(self.theme)
                self._resolve_character()
                self.move(x, y)
            except Exception:
                self.move(100, 100)
                self.scale = 1.0
                self.opacity = 1.0
        else:
            self.move(100, 100)

        self.apply_opacity()
        self.update_topmost()
        self._apply_form()
        self.save_config()

    def save_config(self):
        cfg = {
            "x": self.x(),
            "y": self.y(),
            "scale": self.scale,
            "opacity": self.opacity,
            "topmost": self.is_topmost,
            "ollama_url": self.ollama_url,
            "model": self.model,
            "model_provider": self.model_provider,
            "api_base": self.api_base,
            "api_key": self.api_key,
            "weather_city": self.weather_city,
            "weather_enabled": self.weather_enabled,
            "autostart": self.autostart,
            "character_id": self.character_id,
            "pet_name": self.pet_name,
            "theme": self.theme.to_dict(),
        }
        try:
            CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"保存配置失败: {e}")

    # ---------- 通用桌宠：角色包 / 名称 / 主题 ----------
    def _read_character_id(self) -> str:
        """仅读 character_id，供帧加载前确定角色包（其余配置稍后由 load_config 统一读取）。"""
        cid = DEFAULT_CHARACTER_ID
        if CONFIG_FILE.exists():
            try:
                cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                cid = cfg.get("character_id", DEFAULT_CHARACTER_ID)
            except Exception:
                pass
        return cid

    def _resolve_character(self):
        """解析当前角色包的各资源路径（人形态帧、bboxes、视频）。"""
        info = character.resolve(self.character_id)
        self._char = info
        self.human_frames_dir = info["human_frames"]
        self.bboxes_file = info["bboxes"]
        self.video_file = info["video"]
        self.character_name = info.get("display_name", "苏璃")

    def _name(self, text: str) -> str:
        """把显示文案里的占位名替换为当前宠物名。

        注意：下面对「银月」的替换是**向后兼容垫片**，不是漏改的旧名。
        项目内所有文案已统一改用 {pet_name} 占位或当前角色名；但用户本地
        遗留的 persona.txt、聊天存档、自定义角色包里可能还写着旧名，
        这里统一兜底换成当前宠物名，保证界面上不会再出现旧名字。
        """
        if not isinstance(text, str):
            return text
        return (
            text.replace("{pet_name}", self.pet_name)
            .replace("银月", self.pet_name)
            .replace("苏璃", self.pet_name)
        )

    def apply_model_config(self):
        """根据当前 model_provider/ollama_url/model/api_base/api_key 重建聊天客户端并保存。"""
        self.ollama = ChatClient(
            provider=self.model_provider,
            base_url=self.ollama_url,
            model=self.model,
            api_key=self.api_key,
            api_base=self.api_base,
        )
        self.save_config()

    # ---------- 外观 ----------
    def apply_scale(self):
        w = int(BASE_WIDTH * self.scale)
        h = int(BASE_HEIGHT * self.scale)
        self.resize(w, h)
        self.update_pet_image()
        self.apply_mask()

    def apply_opacity(self):
        self.setWindowOpacity(self.opacity)
        self.bubble.setWindowOpacity(self.opacity)

    def _load_bboxes(self):
        """读取角色包 bboxes.json 的 human 包围盒 [x, y, w, h]（240x320 画布坐标系），
        用于窗口遮罩：仅在该包围盒内可点击/可见，透明留白处点击穿透到桌面。
        不同角色包各自带 bboxes.json，鼠标点击范围会跟随当前角色；
        导入角色包时会自动识别帧并生成 bboxes.json。"""
        self.human_bbox = QRect(0, 0, BASE_WIDTH, BASE_HEIGHT)
        p = self.bboxes_file
        if not p.exists():
            return
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            h = data.get("human")
            if isinstance(h, (list, tuple)) and len(h) == 4:
                self.human_bbox = QRect(int(h[0]), int(h[1]), int(h[2]), int(h[3]))
        except Exception:
            pass

    def apply_mask(self):
        """按角色包围盒设置窗口遮罩：仅角色包围盒内可点击/可见，
        透明留白处点击穿透到桌面。"""
        rect = self.human_bbox
        s = self.scale
        r = QRect(
            int(rect.x() * s),
            int(rect.y() * s),
            max(1, int(rect.width() * s)),
            max(1, int(rect.height() * s)),
        )
        self.setMask(QRegion(r))

    # ---------- 热重载（点击"启动桌宠"时即时切换角色/名称/配色） ----------
    def hot_reload(self):
        """重新读取 config.json 并即时应用，无需退出重开。"""
        prev_frames = getattr(self, "human_frames", [])
        try:
            self.load_config()  # 重新加载 pet_name / character_id / theme / persona 等
        except Exception:
            pass

        # 重新解析角色资源
        self._resolve_character()
        new_frames = self.load_frames(self.human_frames_dir)
        if new_frames:
            self.human_frames = new_frames
        else:
            # 帧缺失时不切换，保留旧角色并提示
            self.show_bubble(f"角色帧缺失，未能切换：{self.human_frames_dir}")
            self.human_frames = prev_frames or self.human_frames

        self._load_bboxes()
        self.apply_mask()
        self._apply_form()
        self.update_pet_image()

        # 重建托盘（tooltip / 菜单里的名字）
        try:
            self.tray.hide()
        except Exception:
            pass
        try:
            self._setup_tray()
        except Exception:
            pass

        # 主题
        set_theme(self.theme)
        self._apply_form()

        self.show_bubble(f"{self._name('{pet_name}已就位~')}")

    def active_frame(self) -> QPixmap:
        """返回当前应显示的帧（人形态常驻动画）。"""
        return self.human_frames[self.frame_index]

    def update_pet_image(self):
        pm = self.active_frame()
        self.pet_label.setPixmap(pm)
        self.pet_label.resize(self.size())

    # ---------- 动画循环（乒乓往返） ----------
    def next_frame(self):
        frames = self.human_frames
        self.frame_index += self.frame_direction
        if self.frame_index >= len(frames) - 1:
            self.frame_index = len(frames) - 1
            self.frame_direction = -1
        elif self.frame_index <= 0:
            self.frame_index = 0
            self.frame_direction = 1
        self.update_pet_image()

    # ---------- 动画重置 ----------
    def _apply_form(self):
        """重置帧循环到起始态（无变身，仅人形态常驻）。"""
        self.frame_index = 0
        self.frame_direction = 1
        self.frame_timer.setInterval(FRAME_INTERVAL_MS)
        self.update_pet_image()
        self.apply_mask()

    # ---------- 交互：拖动 ----------
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = False
            self.last_mouse_pos = event.globalPosition().toPoint()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() & Qt.MouseButton.LeftButton:
            new_pos = event.globalPosition().toPoint()
            delta = new_pos - self.last_mouse_pos
            if delta.manhattanLength() > 3:
                self.dragging = True
                self.move(self.pos() + delta)
                self.bubble.move(self.bubble.pos() + delta)
                if self.chat_panel.isVisible():
                    self.chat_panel.move(self.chat_panel.pos() + delta)
                self.last_mouse_pos = new_pos
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            if not self.dragging:
                # 延迟触发：若紧接着是双击则取消，改为开聊天
                self.click_timer.start(220)
            self.dragging = False
            event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.click_timer.stop()
            self.open_chat()
            event.accept()

    # ---------- 鼠标悬停状态提示 ----------
    def enterEvent(self, event):
        # 鼠标停在角色上 1 秒后显示状态框
        if not self.dragging and self.isVisible():
            self.hover_timer.start(1000)
        event.accept()

    def leaveEvent(self, event):
        self.hover_timer.stop()
        self.status_tooltip.hide()
        event.accept()

    def _show_hover_status(self):
        if self.dragging or self.isHidden():
            return
        self.status_tooltip.show_status(self.status, self.geometry(), self.scale, self.weather)
        if self.is_topmost:
            set_window_topmost(self.status_tooltip.winId(), True)

    # ---------- 系统托盘 ----------
    def _setup_tray(self):
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(self._make_tray_icon())
        self.tray.setToolTip(f"{self.pet_name}桌面宠物")

        tray_menu = QMenu(self)
        show_act = QAction("显示", self)
        show_act.triggered.connect(self.action_show)
        hide_act = QAction("隐藏", self)
        hide_act.triggered.connect(self.action_hide)
        chat_act = QAction(f"和{self.pet_name}聊天", self)
        chat_act.triggered.connect(self.open_chat)
        status_act = QAction("查看状态", self)
        status_act.triggered.connect(self.action_status)
        settings_act = QAction("设置...", self)
        settings_act.triggered.connect(self.open_settings)
        quit_act = QAction("退出", self)
        quit_act.triggered.connect(self.close)

        tray_menu.addAction(show_act)
        tray_menu.addAction(hide_act)
        tray_menu.addSeparator()
        tray_menu.addAction(chat_act)
        tray_menu.addAction(status_act)
        tray_menu.addAction(settings_act)
        tray_menu.addSeparator()
        tray_menu.addAction(quit_act)

        self.tray.setContextMenu(tray_menu)
        self.tray.activated.connect(
            lambda reason: (
                self.action_show()
                if reason == QSystemTrayIcon.ActivationReason.DoubleClick
                else None
            )
        )
        self.tray.show()

    def _load_app_icon(self) -> QIcon:
        """加载程序图标：优先使用同级目录的 icon.ico，否则用角色首帧。"""
        icon = QIcon()
        ico_path = Path(__file__).with_name("icon.ico")
        if ico_path.exists():
            icon.addFile(str(ico_path))
        if icon.isNull() and getattr(self, "human_frames", None):
            icon.addPixmap(self.human_frames[0])
        return icon

    def _make_tray_icon(self) -> QIcon:
        """系统托盘图标：优先使用 icon.ico，否则用角色首帧或文字占位。"""
        icon = self._load_app_icon()
        if not icon.isNull():
            return icon
        pm = QPixmap(64, 64)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        painter.setBrush(QColor("#ff7fb0"))
        painter.setPen(QColor("#ffffff"))
        painter.drawEllipse(8, 8, 48, 48)
        painter.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "银")
        painter.end()
        icon.addPixmap(pm)
        return icon

    def action_show(self):
        self.show()
        self.raise_()
        if self.is_topmost:
            set_window_topmost(self.winId(), True)

    def action_hide(self):
        # 隐藏到系统托盘：隐藏角色、气泡、聊天面板与悬停提示
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.show_bubble("当前系统没有托盘，没法隐藏哦~")
            return
        self.hover_timer.stop()
        self.status_tooltip.hide()
        self.bubble.hide()
        panel = getattr(self, "chat_panel", None)
        if panel is not None:
            panel.hide()
        self.hide()

    # ---------- 右键菜单 ----------
    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background-color: #ffffff; border: 1px solid #ff9ec2; padding: 6px; }"
            "QMenu::item { padding: 6px 24px; color: #333; }"
            "QMenu::item:selected { background-color: #ffe6f0; }"
            "QMenu::item:disabled { color: #999; }"
        )

        busy = self.status.is_busy()
        busy_kind = self.status.busy_text() if busy else ""
        remaining = self.status.remaining_minutes() if busy else 0

        def _add_disabled(text: str):
            act = QAction(text, self)
            act.setEnabled(False)
            menu.addAction(act)

        # ---------- 顶部：查看状态 / 聊天 ----------
        status_action = QAction("查看状态", self)
        status_action.triggered.connect(self.action_status)
        menu.addAction(status_action)

        chat_action = QAction(f"和{self.pet_name}聊天", self)
        chat_action.triggered.connect(self.open_chat)
        menu.addAction(chat_action)

        weather_action = QAction("查看天气", self)
        weather_action.triggered.connect(self.action_weather)
        menu.addAction(weather_action)

        menu.addSeparator()

        # ---------- 养成互动 ----------
        # 打工
        work_menu = menu.addMenu("打工")
        if busy:
            _add_disabled(f"{busy_kind}中（还剩 {remaining} 分钟）") if busy_kind != "打工" else None
            work_menu.setEnabled(False)
        else:
            for job, info in WORK_JOBS.items():
                job_menu = work_menu.addMenu(f"{job}（{info['coins']}灵石/时）")
                for h in WORK_DURATIONS:
                    act = QAction(f"{h} 小时", self)
                    act.triggered.connect(lambda checked, j=job, hh=h: self.action_work(j, hh))
                    job_menu.addAction(act)

        # 旅行
        travel_menu = menu.addMenu("旅行")
        if busy:
            travel_menu.setEnabled(False)
        else:
            for h in TRAVEL_DURATIONS:
                act = QAction(f"{h} 小时", self)
                act.triggered.connect(lambda checked, hh=h: self.action_travel(hh))
                travel_menu.addAction(act)

        # 商店
        shop_action = QAction("商店", self)
        shop_action.triggered.connect(self.action_open_shop)
        menu.addAction(shop_action)

        # 背包
        backpack_action = QAction("背包", self)
        backpack_action.triggered.connect(self.action_open_backpack)
        menu.addAction(backpack_action)

        # 抚摸
        pet_action = QAction("抚摸", self)
        pet_action.triggered.connect(self.action_pet)
        menu.addAction(pet_action)

        # 玩游戏（子菜单）—— 均为独立窗口小游戏
        play_menu = menu.addMenu("玩游戏")
        for gname, gkind in (
            ("2048", "2048"),
            ("推箱子", "sokoban"),
            ("贪吃蛇", "snake"),
            ("石头剪刀布", "rps"),
            ("扫雷", "minesweeper"),
            ("俄罗斯方块", "tetris"),
            ("五子棋", "gomoku"),
        ):
            act = QAction(gname, self)
            act.triggered.connect(lambda checked, k=gkind: self.action_open_game(k))
            play_menu.addAction(act)

        # 睡觉 / 唤醒
        if busy and self.status.activity_kind == "sleep":
            wake_action = QAction(f"唤醒（还剩 {remaining} 分钟）", self)
            wake_action.triggered.connect(self.toggle_sleep)
            menu.addAction(wake_action)
        elif busy:
            _add_disabled(f"{busy_kind}中无法睡觉（还剩 {remaining} 分钟）")
        else:
            sleep_menu = menu.addMenu("睡觉")
            for h in SLEEP_DURATIONS:
                act = QAction(f"{h} 小时", self)
                act.triggered.connect(lambda checked, hh=h: self.action_sleep(hh))
                sleep_menu.addAction(act)

        menu.addSeparator()
        hide_action = QAction("隐藏", self)
        hide_action.triggered.connect(self.action_hide)
        menu.addAction(hide_action)

        settings_action = QAction("设置...", self)
        settings_action.triggered.connect(self.open_settings)
        menu.addAction(settings_action)

        quit_action = QAction("退出", self)
        quit_action.triggered.connect(self.close)
        menu.addAction(quit_action)

        menu.exec(QCursor.pos())
        event.accept()

    def _position_beside(self, dlg: QDialog):
        """把对话框放到桌宠旁边，优先右侧，其次左侧，再其次下方，避免挡住角色。"""
        pet_geo = self.geometry()
        screen = _screen_geo(pet_geo)
        margin = 12
        # 候选位置：右、左、下
        candidates = []
        # 右侧
        x = pet_geo.right() + margin
        y = pet_geo.top()
        if x + dlg.width() <= screen.right():
            candidates.append((x, y))
        # 左侧
        x = pet_geo.left() - margin - dlg.width()
        if x >= screen.left():
            candidates.append((x, y))
        # 下方（居中）
        x = pet_geo.center().x() - dlg.width() // 2
        y = pet_geo.bottom() + margin
        if y + dlg.height() <= screen.bottom():
            candidates.append((x, y))

        if candidates:
            x, y = candidates[0]
        else:
            # 屏幕都很挤，放右下角
            x = screen.right() - dlg.width() - margin
            y = screen.bottom() - dlg.height() - margin
        y = max(screen.top(), min(y, screen.bottom() - dlg.height()))
        dlg.move(x, y)

    def open_settings(self):
        dlg = SettingsDialog(self, self)
        QTimer.singleShot(0, lambda: self._position_beside(dlg))
        dlg.exec()

    def open_persona_editor(self):
        dlg = PersonaDialog(self, self)
        QTimer.singleShot(0, lambda: self._position_beside(dlg))
        dlg.exec()

    def toggle_topmost(self):
        self.set_topmost(not self.is_topmost)
        self.save_config()

    def set_topmost(self, value: bool):
        self.is_topmost = value
        self.update_topmost()

    def update_topmost(self):
        # 用 Win32 直接切换，不重建窗口；角色、气泡、聊天面板同步
        set_window_topmost(self.winId(), self.is_topmost)
        set_window_topmost(self.bubble.winId(), self.is_topmost)
        panel = getattr(self, "chat_panel", None)
        if panel is not None:
            set_window_topmost(panel.winId(), self.is_topmost)

    def set_scale(self, scale: float):
        self.scale = max(MIN_SCALE, min(MAX_SCALE, scale))
        self.apply_scale()
        self.save_config()

    def set_opacity(self, opacity: float):
        self.opacity = max(MIN_OPACITY, min(MAX_OPACITY, opacity))
        self.apply_opacity()
        self.save_config()

    def set_custom_scale(self):
        val, ok = QInputDialog.getDouble(
            self,
            "自定义大小",
            f"请输入缩放比例 ({MIN_SCALE} - {MAX_SCALE}):",
            self.scale,
            MIN_SCALE,
            MAX_SCALE,
            2,
        )
        if ok:
            self.set_scale(val)

    # ---------- 互动动画 ----------
    def _is_animating(self) -> bool:
        return any(a.state() == QPropertyAnimation.State.Running for a in self.animations)

    def _clear_animations(self):
        for a in self.animations:
            a.stop()
        self.animations.clear()

    def trigger_interaction(self):
        self._clear_animations()
        interactions = [self.animate_jump, self.animate_squash, self.animate_shake]
        fn = interactions[self.interaction_index % len(interactions)]
        self.interaction_index += 1
        self.show_bubble(random.choice(BUBBLES))
        fn()

    def show_bubble(self, text: str, duration_ms: int = 2500):
        text = self._name(text)
        self.bubble.show_text(text, self.geometry(), self.scale)
        if self.is_topmost:
            set_window_topmost(self.bubble.winId(), True)
        self.bubble_timer.stop()
        self.bubble_timer.start(duration_ms)

    def idle_tick(self):
        if self.isVisible() and not self.dragging and not self._is_animating() and random.random() < 0.35:
            self.show_bubble(random.choice(IDLE_BUBBLES), 2000)

    def _on_interaction_finished(self):
        sender = self.sender()
        if sender in self.animations:
            self.animations.remove(sender)

    def animate_jump(self):
        start = self.y()
        height = int(80 * self.scale)
        duration = 250

        anim_up = QPropertyAnimation(self, b"pos")
        anim_up.setDuration(duration)
        anim_up.setStartValue(self.pos())
        anim_up.setEndValue(QPoint(self.x(), start - height))
        anim_up.setEasingCurve(QEasingCurve.Type.OutQuad)

        anim_down = QPropertyAnimation(self, b"pos")
        anim_down.setDuration(duration)
        anim_down.setStartValue(QPoint(self.x(), start - height))
        anim_down.setEndValue(QPoint(self.x(), start))
        anim_down.setEasingCurve(QEasingCurve.Type.InQuad)

        group = QSequentialAnimationGroup(self)
        group.addAnimation(anim_up)
        group.addAnimation(anim_down)
        group.finished.connect(self._on_interaction_finished)
        self.animations.append(group)
        group.start()

    def animate_squash(self):
        base_w = int(BASE_WIDTH * self.scale)
        base_h = int(BASE_HEIGHT * self.scale)
        x = self.x()
        y = self.y()

        squash_h = int(base_h * 0.65)
        squash_w = int(base_w * 1.15)
        squash_x = x - (squash_w - base_w) // 2
        squash_y = y + (base_h - squash_h)

        anim_down = QPropertyAnimation(self, b"geometry")
        anim_down.setDuration(120)
        anim_down.setStartValue(self.geometry())
        anim_down.setEndValue(QRect(squash_x, squash_y, squash_w, squash_h))
        anim_down.setEasingCurve(QEasingCurve.Type.OutQuad)

        anim_up = QPropertyAnimation(self, b"geometry")
        anim_up.setDuration(220)
        anim_up.setStartValue(QRect(squash_x, squash_y, squash_w, squash_h))
        anim_up.setEndValue(QRect(x, y, base_w, base_h))
        anim_up.setEasingCurve(QEasingCurve.Type.OutBounce)

        group = QSequentialAnimationGroup(self)
        group.addAnimation(anim_down)
        group.addAnimation(anim_up)
        group.finished.connect(self._on_interaction_finished)
        self.animations.append(group)
        group.start()

    def animate_shake(self):
        x = self.x()
        offset = int(18 * self.scale)

        group = QSequentialAnimationGroup(self)
        for target_x in [x - offset, x + offset, x - offset, x + offset, x]:
            anim = QPropertyAnimation(self, b"pos")
            anim.setDuration(80)
            anim.setStartValue(self.pos())
            anim.setEndValue(QPoint(target_x, self.y()))
            anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
            group.addAnimation(anim)

        group.finished.connect(self._on_interaction_finished)
        self.animations.append(group)
        group.start()

    # ---------- AI 对话 ----------
    def open_chat(self):
        self.chat_panel.position_above(self.geometry(), self.scale)
        if self.is_topmost:
            set_window_topmost(self.chat_panel.winId(), True)
        self.chat_panel.update_status(self.status.bars())
        self.chat_panel.update_coins(self.status.coins)
        self.chat_panel.show()
        self.chat_panel.raise_()
        self.chat_panel.input.setFocus()

    def close_chat(self):
        self.chat_panel.hide()

    def clear_memory(self):
        self.chat_memory.clear()
        try:
            if self.chat_memory.path.exists():
                self.chat_memory.path.unlink()
        except Exception:
            pass

    # ---------- 养成状态 ----------
    def status_tick(self):
        bubble = self.status.tick(1)
        if bubble and self.isVisible() and not self.dragging:
            self.show_bubble(bubble)
        if self.isVisible() and not self.dragging and not self._is_animating() and random.random() < 0.25:
            self.show_bubble(self.status_idle_bubble())
        if self.chat_panel.isVisible():
            self.chat_panel.update_status(self.status.bars())
            self.chat_panel.update_coins(self.status.coins)

    def status_idle_bubble(self) -> str:
        s = self.status
        if s.is_busy():
            return s.activity_status_text()
        if s.sleeping:
            return f"呼……呼……（{self.pet_name}在睡觉）"
        if s.hunger < 30:
            return random.choice(["肚子咕咕叫，想吃东西~", "好饿呀，主人给点灵石嘛~"])
        if s.mood < 30:
            return random.choice(["今天有点提不起劲…", f"呜…陪陪{self.pet_name}嘛~"])
        if s.affection > 80:
            return random.choice(["最喜欢主人啦！", "主人最好了~"])
        if s.stamina < 20:
            return random.choice(["累得没力气了，想歇会儿…", f"主人，{self.pet_name}想睡一觉~"])
        if s.coins <= 0:
            return random.choice(["身上没有灵石啦，去打点工吧~", "灵石花光了，呜…"])
        return random.choice(IDLE_BUBBLES)

    # ---------- 互动动作 ----------
    def action_open_shop(self):
        dlg = ShopDialog(self)
        QTimer.singleShot(0, lambda: self._position_beside(dlg))
        dlg.exec()

    def action_work(self, job: str, hours: int = 1):
        ok, bubble, _ = self.status.start_activity("work", hours, job)
        self.show_bubble(bubble)
        if ok:
            self.animate_shake()
        self._refresh_chat_status()

    def action_travel(self, hours: int = 1):
        ok, bubble, _ = self.status.start_activity("travel", hours)
        self.show_bubble(bubble)
        if ok:
            self.animate_jump()
        self._refresh_chat_status()

    def action_sleep(self, hours: int = 1):
        ok, bubble, _ = self.status.start_activity("sleep", hours)
        self.show_bubble(bubble)
        if ok:
            self.animate_jump()
        self._refresh_chat_status()

    def action_use_item(self, item: str):
        ok, bubble, _ = self.status.use_item(item)
        self.show_bubble(bubble)
        if ok:
            self.animate_squash()
        self._refresh_chat_status()

    def action_open_backpack(self):
        dlg = BackpackDialog(self)
        QTimer.singleShot(0, lambda: self._position_beside(dlg))
        dlg.exec()

    def action_open_game(self, kind: str):
        # 打开内置休闲小游戏窗口
        if kind == "rps":
            launch_game(kind, parent=self, on_round=self._on_rps_round)
        else:
            launch_game(kind, parent=self,
                        on_game_over=lambda sc: self._on_game_over(kind, sc))

    def _on_game_over(self, kind: str, score: int):
        # 陪宠物玩一局小游戏，给一点点好感/心情奖励
        name = {
            "2048": "2048", "sokoban": "推箱子", "snake": "贪吃蛇",
            "minesweeper": "扫雷", "tetris": "俄罗斯方块", "gomoku": "五子棋",
        }.get(kind, kind)
        self.status.reward(mood=2, affection=1)
        self._refresh_chat_status()
        self.show_bubble(f"刚陪{self.pet_name}玩了{name}，得分 {score}，好开心~", 3500)

    def _on_rps_round(self, result, user, pet):
        # 石头剪刀布每局结算：赢则心情+2好感+1，输则仅+1心情，平局不奖励
        if result == "你赢":
            self.status.reward(mood=2, affection=1)
        elif result == f"{self.pet_name}赢":
            self.status.reward(mood=1)
        self._refresh_chat_status()

    def action_pet(self):
        self.status.pet()
        self.show_bubble("害羞地蹭了蹭主人~")

    def action_play(self):
        ok, bubble, _ = self.status.play()
        if not ok:
            self.show_bubble(bubble)
        else:
            self.show_bubble("好开心，和主人玩最棒了！")
            self.animate_jump()
        self._refresh_chat_status()

    def action_status(self):
        self.show_bubble("「" + self.status.summary_text() + "」")

    # ---------- 天气常驻 ----------
    def apply_weather_config(self):
        try:
            self.weather_timer.stop()
        except Exception:
            pass
        if self.weather_enabled and self.weather_city:
            self.weather_timer.start(60 * 60 * 1000)
            self._fetch_weather()
        else:
            self.weather = None

    def _fetch_weather(self):
        if not self.weather_enabled or not self.weather_city:
            return
        if self._io_thread is not None and self._io_thread.isRunning():
            return
        city = self.weather_city
        self._io_thread = _IOThread(lambda: get_weather(city))
        self._io_thread.got.connect(self._on_weather_got)
        self._io_thread.failed.connect(self._on_weather_failed)
        self._io_thread.start()

    def _on_weather_got(self, w):
        if not w:
            return
        self.weather = w
        # 心情随天气轻微变化（每次拉取结算一次）
        code = w.get("code", -1)
        if code in _RAINY_CODES:
            self.status.reward(mood=-2)
        elif code in _SUNNY_CODES:
            self.status.reward(mood=1)
        self._refresh_chat_status()

    def _on_weather_failed(self, err):
        self.weather_error = str(err)
        print(f"天气获取失败: {err}")

    def action_weather(self):
        if self.weather:
            w = self.weather
            txt = f"「{w.get('city', '')} {w.get('desc', '')}"
            if w.get("temp") is not None:
                txt += f"，{w['temp']}°C"
            if w.get("wind") is not None:
                txt += f"，风{w['wind']}km/h"
            txt += "」"
            self.show_bubble(txt)
        else:
            if self.weather_error:
                self.show_bubble(f"天气查询失败了：{self.weather_error[:120]}")
            else:
                self.show_bubble(f"{self.pet_name}还没拿到天气，稍等一下哦~")

    # ---------- 开机自启 ----------
    def set_autostart(self, enable: bool):
        self.autostart = enable
        self.save_config()
        key = r"Software\Microsoft\Windows\CurrentVersion\Run"
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as hk:
                if enable:
                    exe = sys.executable
                    winreg.SetValueEx(hk, "通用桌宠", 0, winreg.REG_SZ, f'"{exe}"')
                else:
                    try:
                        winreg.DeleteValue(hk, "通用桌宠")
                    except FileNotFoundError:
                        pass
        except Exception as e:
            print(f"设置开机自启失败: {e}")

    def get_autostart(self) -> bool:
        key = r"Software\Microsoft\Windows\CurrentVersion\Run"
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_QUERY_VALUE) as hk:
                try:
                    winreg.QueryValueEx(hk, "通用桌宠")
                    return True
                except FileNotFoundError:
                    return False
        except Exception:
            return False

    # ---------- 全局热键 ----------
    def _setup_hotkeys(self):
        if sys.platform != "win32":
            return
        try:
            user32 = ctypes.windll.user32
            MOD_CONTROL = 0x0002
            MOD_ALT = 0x0001
            MOD_NOREPEAT = 0x4000
            mod = MOD_CONTROL | MOD_ALT | MOD_NOREPEAT
            # 明确声明参数/返回类型，避免 ctypes 默认推断导致的注册失败
            user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_uint, ctypes.c_uint]
            user32.RegisterHotKey.restype = ctypes.c_bool
            user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
            user32.UnregisterHotKey.restype = ctypes.c_bool
            # 注册到本窗口句柄：即使宠物被隐藏（HWND 仍存活），热键依然有效
            hwnd = int(self.winId())
            for name, ch in (("toggle", "S"), ("chat", "C")):
                vk = ctypes.windll.user32.VkKeyScanW(ord(ch)) & 0xFF
                ok = user32.RegisterHotKey(hwnd, self._hk_ids[name], mod, vk)
                if not ok:
                    print(f"注册热键失败: {name}")
        except Exception as e:
            print(f"热键初始化失败: {e}")

    def _unregister_hotkeys(self):
        if sys.platform != "win32":
            return
        try:
            user32 = ctypes.windll.user32
            hwnd = int(self.winId())
            for name in self._hk_ids:
                user32.UnregisterHotKey(hwnd, self._hk_ids[name])
        except Exception:
            pass

    def nativeEvent(self, eventType, message):
        """捕获全局热键（Win32 WM_HOTKEY = 0x0312）。"""
        if eventType == "windows_generic_MSG":
            try:
                msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG))
                if msg.contents.message == 0x0312:
                    self._on_hotkey(int(msg.contents.wParam))
                    return True, 0
            except Exception:
                pass
        return False, 0

    def _on_hotkey(self, hk_id):
        if hk_id == self._hk_ids.get("toggle"):
            if self.isHidden():
                self.action_show()
            else:
                self.action_hide()
        elif hk_id == self._hk_ids.get("chat"):
            self.action_show()
            self.open_chat()

    def toggle_sleep(self):
        if self.status.is_busy() and self.status.activity_kind == "sleep":
            ok, bubble = self.status.cancel_activity()
        else:
            ok, bubble, _ = self.status.start_activity("sleep", 1)
        self.show_bubble(bubble)
        self._refresh_chat_status()

    def _refresh_chat_status(self):
        if getattr(self, "chat_panel", None) is not None:
            self.chat_panel.update_status(self.status.bars())
            self.chat_panel.update_coins(self.status.coins)

    # ---------- 本地指令 / 小游戏 ----------
    def _build_system_prompt(self) -> str:
        name_line = f"\n\n【你的名字】你叫{self.pet_name}，请在对话中以「{self.pet_name}」自称。"
        return (
            self.persona + name_line
            + "\n\n【当前时间】" + now_context()
            + "（这是你回答实时问题的唯一时间依据；若问题涉及天气/新闻等实时信息，必须依赖后续给出的联网搜索结果，绝不要依赖训练数据中的旧时间。）"
            + "\n\n【当前状态】" + self.status.summary_text()
            + "\n【状态提示】" + self.status.status_hint()
            + "\n请根据状态调整语气与行为；如果用户让你吃东西/陪玩/摸摸等，可以配合状态撒娇或道谢。"
        )

    def _match_shop_item(self, t: str):
        aliases = {
            "灵果": ["灵果", "灵石", "糕点", "点心", "果子", "零食"],
            "仙桃": ["仙桃", "桃子"],
            "灵膳": ["灵膳", "大餐", "饭菜", "膳", "饭"],
            "拨浪鼓": ["拨浪鼓", "玩具", "鼓"],
            "玉如意": ["玉如意", "如意"],
            "木剑": ["木剑", "剑"],
        }
        for item, al in aliases.items():
            if any(a in t for a in al):
                return item
        return None

    def _parse_hours(self, t: str) -> float:
        """解析「N小时 / 半天 / 一天」为时长倍数（1~8）。"""
        m = re.search(r"(\d+)\s*小时", t)
        if m:
            return max(1.0, min(8.0, float(int(m.group(1)))))
        if "半天" in t:
            return 4.0
        if "一天" in t or "一整天" in t:
            return 8.0
        return 1.0

    def _try_local_command(self, text: str):
        t = text.strip()

        # 0) 当前时间 / 日期 / 年份（本地准确回答，不走模型，避免幻觉）
        if any(k in t for k in ("几点", "时间", "几点了", "现在几点")) and "天气" not in t:
            now = datetime.now()
            return f"现在是北京时间 {now.year}年{now.month}月{now.day}日 {now.hour:02d}:{now.minute:02d}:{now.second:02d}~"
        if any(k in t for k in ("今天几号", "几号", "日期", "今天日期")):
            now = datetime.now()
            return f"今天是 {now.year}年{now.month}月{now.day}日 星期{'一二三四五六日'[now.weekday()]}~"
        if any(k in t for k in ("今年", "几几年", "现在几几年", "哪一年")):
            now = datetime.now()
            return f"现在是 {now.year}年 呀~"
        if "星期" in t or "礼拜" in t:
            now = datetime.now()
            return f"今天是星期{'一二三四五六日'[now.weekday()]}~"

        # 1) 睡觉 / 唤醒（真实时间活动）
        if t in ("睡觉", "睡", "休息", "睡吧"):
            hours = self._parse_hours(t)
            ok, bubble, _ = self.status.start_activity("sleep", int(hours))
            self._refresh_chat_status()
            return bubble
        if t in ("醒", "醒来", "起床", "醒醒"):
            ok, bubble = self.status.cancel_activity()
            self._refresh_chat_status()
            return bubble

        # 6) 打工 / 工作（真实时间活动，可选时长）
        if any(k in t for k in ("打工", "工作", "上班", "干活")):
            job = "采药"
            for j in WORK_JOBS:
                if j in t:
                    job = j
            hours = int(self._parse_hours(t))
            ok, bubble, _ = self.status.start_activity("work", hours, job)
            self._refresh_chat_status()
            return bubble

        # 7) 外出旅行（真实时间活动，可选时长）
        if any(k in t for k in ("旅行", "出去玩", "游玩", "出去走走", "逛逛", "去玩", "散散心", "出去旅游")):
            hours = int(self._parse_hours(t))
            ok, bubble, _ = self.status.start_activity("travel", hours)
            self._refresh_chat_status()
            return bubble

        # 8) 商店/购买（打开商店弹窗，或直接买指定物品）
        if "商店" in t or "买东西" in t:
            self.action_open_shop()
            return f"（{self.pet_name}打开商店清单）主人看看想买点什么~"
        item = self._match_shop_item(t)
        if item is None and any(k in t for k in ("买", "购", "来一份")):
            item = "灵果"
        if item is not None and any(k in t for k in ("买", "购", "来一份", "要")):
            ok, bubble, _ = self.status.buy(item)
            self._refresh_chat_status()
            return bubble

        # 9) 背包查看 / 取出喂食 · 玩耍
        if "背包" in t:
            return "「" + self.status.inventory_text() + "」"
        eat = self._match_shop_item(t)
        if eat is not None and any(k in t for k in ("吃", "喂", "食", "用", "玩", "耍")):
            ok, bubble, _ = self.status.use_item(eat)
            self._refresh_chat_status()
            return bubble

        # 9) 抚摸
        if any(k in t for k in ("摸", "抱", "揉", "亲", "蹭")):
            self.action_pet()
            return f"（{self.pet_name}被摸得眯起眼睛）主人好温柔~"

        # 10) 陪玩
        if any(k in t for k in ("玩", "陪", "游戏", "一起")):
            self.action_play()
            return f"（{self.pet_name}蹦蹦跳跳）陪主人玩{self.pet_name}最开心啦~"

        return None

    def _chat_panel_local_reply(self, reply: str):
        panel = self.chat_panel
        if panel._thinking_index is not None:
            idx = panel._thinking_index
            if 0 <= idx < len(panel.messages) and panel.messages[idx][0] == "assistant":
                panel.messages[idx] = ("assistant", reply)
            else:
                panel.messages.append(("assistant", reply))
            panel._thinking_index = None
        else:
            panel.messages.append(("assistant", reply))
        panel.input.setEnabled(True)
        panel.input.setFocus()
        panel._render()
        self.chat_memory.add_turn("user", self._chat_full)
        self.chat_memory.add_turn("assistant", reply)
        panel.update_status(self.status.bars())
        panel.update_coins(self.status.coins)

    def _extract_chat_weather_city(self, text: str):
        """从聊天文本中提取城市名；未提取到则使用当前设置的城市。"""
        if "天气" not in text and "气温" not in text and "温度" not in text:
            return None
        # 去掉常见提问前缀/时间词，避免把「查询」「今天」等误判为城市名
        t = text
        for p in (
            "查询一下", "查一下", "查询", "查", "搜索一下", "搜索", "搜一下", "搜",
            "告诉我", "问一下", "请问", "一下",
        ):
            if t.startswith(p):
                t = t[len(p):].strip()
                break
        t = re.sub(r"今天|现在|当前", "", t).strip()
        m = re.search(r"^([\u4e00-\u9fa5]{2,7}(?:市|县|区)?)(?:的)?(?:天气|气温|温度)", t)
        if m:
            city = m.group(1).strip().rstrip("的")
            if city and city not in ("今天", "现在", "当前"):
                return city
        return self.weather_city

    def _query_weather_for_chat(self, city: str):
        """在后台线程查询天气，完成后直接回复到聊天面板。"""
        self.chat_panel.show_thinking(f"（{self.pet_name}正在查天气…）")
        if self._chat_weather_thread is not None and self._chat_weather_thread.isRunning():
            try:
                self._chat_weather_thread.quit()
                self._chat_weather_thread.wait(500)
            except Exception:
                pass
        self._chat_weather_thread = _IOThread(lambda: get_weather(city))
        self._chat_weather_thread.got.connect(self._on_chat_weather_got)
        self._chat_weather_thread.failed.connect(self._on_chat_weather_failed)
        self._chat_weather_thread.start()

    def _on_chat_weather_got(self, w):
        if self.sender() is not self._chat_weather_thread:
            return
        if not w:
            self._on_chat_weather_failed("未能获取到天气信息")
            return
        txt = f"「{w.get('city', '')} {w.get('desc', '')}"
        if w.get("temp") is not None:
            txt += f"，{w['temp']}°C"
        if w.get("wind") is not None:
            txt += f"，风{w['wind']}km/h"
        txt += "」"
        self._chat_panel_local_reply(f"{txt} 主人外出记得看天气哦~")

    def _on_chat_weather_failed(self, err):
        if self.sender() is not self._chat_weather_thread:
            return
        city = self._chat_weather_city or self.weather_city
        self._chat_panel_local_reply(f"{self.pet_name}暂时没查到「{city}」的天气，主人稍后再试一次好不好？")

    def start_chat(self, text: str):
        self._chat_req_id += 1
        self._current_req_id = self._chat_req_id
        req_id = self._current_req_id

        self.chat_panel.add_user(text)
        # 记录本轮用户输入，供本地指令/小游戏分支也正确写入记忆
        self._chat_full = text
        self._chat_reply = ""

        # 1) 本地指令 / 小游戏（不走模型）
        local = self._try_local_command(text)
        if local is not None:
            self._chat_panel_local_reply(local)
            return

        # 2) 天气查询直接走本地天气接口，不经过 LLM/联网搜索，避免模型因搜索失败而回复搜不到
        weather_city = self._extract_chat_weather_city(text)
        if weather_city:
            self._chat_weather_city = weather_city
            self._query_weather_for_chat(weather_city)
            return

        # 3) 是否需要联网搜索（移至后台线程执行，避免阻塞 UI）
        #    时间/日期/年份类问题直接本地回答，不走模型，避免幻觉
        need_search = any(k in text for k in (
            "天气", "新闻", "搜索", "搜", "查一下", "最新", "热点", "股市", "汇率",
            "电影", "上映", "票房", "影讯", "行情", "股价", "股票", "比赛", "赛果",
            "NBA", "疫情", "高铁", "航班", "彩票", "怎样", "如何", "为什么", "多少钱", "是什么",
        ))
        search_query = ""
        if need_search:
            q = text
            for p in ("查一下", "查", "搜索一下", "搜索", "搜一下", "搜", "告诉我", "问一下"):
                if q.startswith(p):
                    q = q[len(p):].strip()
                    break
            search_query = q if q else text
        self.chat_panel.show_thinking(f"（{self.pet_name}正在联网查询…）" if need_search else f"（{self.pet_name}思考中…）")

        today = now_context()
        search_instruction = (
            f"今天是 {today}。下面是我刚刚联网搜索到的最新参考信息，请严格基于这些信息用中文回答用户的问题。"
            "如果参考信息里已经包含答案（如温度/天气/新闻/电影/数据等），请直接给出结论，不要再说'不知道'或'搜不到'；"
            "如果信息确实不足或为空，再诚实说明'暂时搜不到更详细的信息'，并不要编造。\n"
        )
        search_failed = (
            "（联网搜索失败：{}）"
            f"搜索没有成功。请直接说：'{self.pet_name}暂时搜不到最新的相关信息，无法给出准确答案。'"
            "不要建议主人去别的软件/网站查看，也不要编造具体的时间、天气、新闻、电影或数据。"
        )

        messages = self.chat_memory.build_messages(self._build_system_prompt())
        messages.append({"role": "user", "content": text})

        if self.chat_worker is not None and self.chat_worker.isRunning():
            try:
                self.chat_worker.quit()
                self.chat_worker.wait(500)
            except Exception:
                pass
        self.chat_worker = ChatWorker(
            self.ollama, messages, req_id=req_id,
            search_query=search_query or None,
            search_instruction=search_instruction,
            search_failed_instruction=search_failed,
        )
        self.chat_worker.token.connect(self._on_chat_token)
        self.chat_worker.finished.connect(self._on_chat_finished)
        self.chat_worker.error.connect(self._on_chat_error)
        self.chat_worker.start()

    def _on_chat_token(self, tok: str, req_id: int):
        if req_id != self._current_req_id:
            return  # 忽略旧 Worker 的迟到 token
        self.chat_panel.append_token(tok)
        self._chat_reply += tok

    def _reward_chat(self):
        """对话驱动养成：每次真心闲聊小幅加好感/心情；被夸额外加成；被嫌弃略减。"""
        text = (self._chat_full or "")
        affection = 1
        mood = 1
        praise = ("喜欢", "爱", "乖", "漂亮", "可爱", "棒", "赞", "亲", "乖宝", "萌", "懂事", "好喜欢")
        if any(k in text for k in praise):
            affection += 2
            mood += 2
        rude = ("烦", "走开", "讨厌", "闭嘴", "滚", "嫌弃", "讨厌你")
        if any(k in text for k in rude):
            mood = -1
            affection = 0
        self.status.reward(affection=affection, mood=mood)
        self._refresh_chat_status()

    def _on_chat_finished(self, req_id: int):
        if req_id != self._current_req_id:
            return
        self.chat_panel.finish_assistant()
        # 没有收到任何内容时，给记忆一个占位，避免后续对话丢失上下文
        reply = self._chat_reply.strip()
        if not reply:
            reply = f"（{self.pet_name}没有说话）"
        # 正常的模型回复才计入对话养成（出错/无意义占位不计入）
        if not reply.startswith("（"):
            self._reward_chat()
        self.chat_memory.add_turn("user", self._chat_full)
        self.chat_memory.add_turn("assistant", reply)
        # 记忆压缩放在回复后，避免阻塞 UI，同时包含最新一轮
        try:
            self.chat_memory.condense(self.ollama)
        except Exception:
            pass

    def _on_chat_error(self, msg: str, req_id: int):
        if req_id != self._current_req_id:
            return
        self.chat_panel.show_error(msg)
        # 出错也保存这一轮，避免用户输入丢失
        self.chat_memory.add_turn("user", self._chat_full)
        self.chat_memory.add_turn("assistant", f"（出错了：{msg}）")

    # ---------- 生命周期 ----------
    def closeEvent(self, event):
        self.save_config()
        # 停止所有可能重新弹出气泡/面板的定时器与后台任务，再关闭窗口
        self.frame_timer.stop()
        self.idle_timer.stop()
        self.bubble_timer.stop()
        self.click_timer.stop()
        self.status_timer.stop()
        try:
            self.weather_timer.stop()
        except Exception:
            pass
        self._unregister_hotkeys()
        try:
            self.hover_timer.stop()
        except Exception:
            pass
        try:
            self.status_tooltip.hide()
        except Exception:
            pass
        try:
            self.status.save()
        except Exception:
            pass
        if self.chat_worker is not None:
            try:
                self.chat_worker.quit()
                self.chat_worker.wait(1000)
            except Exception:
                pass
        try:
            self.bubble.hide()
            self.bubble.close()
        except Exception:
            pass
        try:
            self.chat_panel.hide()
            self.chat_panel.close()
        except Exception:
            pass
        try:
            self.tray.hide()
        except Exception:
            pass
        event.accept()
        QApplication.instance().quit()


def _create_single_instance() -> bool:
    """创建命名互斥量。返回 True 表示这是第一个实例；False 表示已有实例。
    任何异常都退化为“允许多开”，避免把用户挡在门外。"""
    if sys.platform != "win32":
        return True
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        last_err = ctypes.get_last_error()
        if not mutex:  # 创建失败，兜底允许多开
            return True
        if last_err == 183:  # ERROR_ALREADY_EXISTS
            return False
        return True
    except Exception:
        return True


def _bring_existing_to_front():
    """把已运行的桌宠窗口调到前台（不关闭它）。"""
    try:
        user32 = ctypes.windll.user32
        EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def enum_proc(hwnd, lparam):
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if buf.value == "通用桌面宠物":
                if user32.IsIconic(hwnd):
                    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                user32.SetForegroundWindow(hwnd)
            return True

        user32.EnumWindows(EnumWindowsProc(enum_proc), 0)
    except Exception:
        pass


def _check_reload(pet):
    """轮询热重载标记：launcher 写入后，运行中的桌宠即时切换配置。"""
    if RELOAD_FLAG.exists():
        try:
            RELOAD_FLAG.unlink()
        except Exception:
            pass
        try:
            pet.hot_reload()
        except Exception:
            pass


def main():
    # 单实例保护：避免重复打开留下多个气泡/面板。
    # 若检测到已有实例，写入“热重载”标记并请它切到前台；本次新进程直接退出，
    # 由已运行的实例即时重新读取最新配置（角色/名称/配色），实现快速切换。
    if not _create_single_instance():
        try:
            RELOAD_FLAG.write_text("1", encoding="utf-8")
        except Exception:
            pass
        _bring_existing_to_front()
        sys.exit(0)

    # 启动时清理可能残留的热重载标记，避免立刻重复重载
    try:
        if RELOAD_FLAG.exists():
            RELOAD_FLAG.unlink()
    except Exception:
        pass

    app = QApplication(sys.argv)
    # 隐藏到托盘时不退出程序（由托盘/退出菜单控制生命周期）
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")

    pet = SilverMoonPet()
    pet.show()

    # 热重载轮询：点击“启动桌宠”时，运行中的实例会即时切换配置
    reload_timer = QTimer()
    reload_timer.timeout.connect(lambda: _check_reload(pet))
    reload_timer.start(300)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
