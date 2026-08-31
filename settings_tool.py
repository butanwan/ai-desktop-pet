"""settings_tool.py — 通用桌宠自定义设置工具。

让用户无需改代码即可自定义：
- 角色包：下拉选择 / 导入新角色包（丢一个文件夹即可）
- 宠物名称
- 界面配色：主色 / 深色 / 面板 / 文字 / 边框（实时预览）

保存后写入 config.json；角色包资源放在 characters/<id>/。
导入角色包时会自动识别帧并生成角色范围（bboxes.json）。
改角色/名称/配色后，重启桌宠（或点"启动桌宠"）生效。
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QLabel, QPushButton,
    QLineEdit, QComboBox, QFileDialog, QColorDialog, QGroupBox, QFormLayout,
    QMessageBox, QWidget, QTextEdit,
)

import character
from character import characters_root, DEFAULT_CHARACTER_ID
from theme import DEFAULT_THEME_COLORS, Theme, set_theme

from launcher import launch_pet

# 导入角色包时自动识别帧、生成角色范围（bboxes.json）
from bbox_utils import compute_bbox


def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


CONFIG_FILE = _app_dir() / "config.json"

PERSONA_FILE = _app_dir() / "persona.txt"

# 默认人设取自聊天模块；导入失败则用内置兜底文本，保证设置工具可独立运行。
try:
    from chat import PERSONA as DEFAULT_PERSONA, DEFAULT_PERSONAS
except Exception:
    DEFAULT_PERSONA = (
        "你是一个可爱的桌宠，温柔贴心，说话带一点俏皮，"
        "会用口语化的中文和主人聊天，每次回复不超过 60 字。"
    )
    DEFAULT_PERSONAS = {"苏璃": DEFAULT_PERSONA}


def load_persona() -> str:
    """读取自定义角色设定；未设置时返回默认人设。"""
    if PERSONA_FILE.exists():
        try:
            text = PERSONA_FILE.read_text(encoding="utf-8").strip()
            if text:
                return text
        except Exception:
            pass
    return DEFAULT_PERSONA


def save_persona(text: str):
    try:
        PERSONA_FILE.write_text(text.strip(), encoding="utf-8")
    except Exception as e:
        print(f"保存角色设定失败: {e}")


EDITABLE_KEYS = ["accent", "accent_dark", "panel_bg", "text", "border"]
KEY_LABELS = {
    "accent": "主色（按钮/标题）",
    "accent_dark": "主色深色（悬停）",
    "panel_bg": "面板底色",
    "text": "文字颜色",
    "border": "边框颜色",
}


def load_config() -> dict:
    cfg = {
        "character_id": DEFAULT_CHARACTER_ID,
        "pet_name": "苏璃",
        "theme": {"name": "silver_moon", "colors": dict(DEFAULT_THEME_COLORS)},
    }
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            cfg["character_id"] = data.get("character_id", cfg["character_id"])
            cfg["pet_name"] = data.get("pet_name", cfg["pet_name"])
            t = data.get("theme")
            if isinstance(t, dict) and isinstance(t.get("colors"), dict):
                colors = dict(DEFAULT_THEME_COLORS)
                colors.update({k: str(v) for k, v in t["colors"].items() if k in EDITABLE_KEYS})
                cfg["theme"] = {"name": t.get("name", "custom"), "colors": colors}
        except Exception:
            pass
    return cfg


def save_config(cfg: dict):
    cfg.setdefault("character_id", DEFAULT_CHARACTER_ID)
    cfg.setdefault("pet_name", "苏璃")
    if "theme" not in cfg:
        cfg["theme"] = {"name": "custom", "colors": dict(DEFAULT_THEME_COLORS)}
    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


class SettingsTool(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("通用桌宠 · 自定义设置")
        self.setMinimumWidth(520)
        self.setMinimumHeight(440)

        self.cfg = load_config()
        self.colors = dict(self.cfg["theme"]["colors"])

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        tabs = QTabWidget()
        root.addWidget(tabs, 1)

        tabs.addTab(self._build_character_tab(), "角色与形象")
        tabs.addTab(self._build_persona_tab(), "角色设定")
        tabs.addTab(self._build_theme_tab(), "外观配色")

        # 底部按钮
        row = QHBoxLayout()
        self.save_btn = QPushButton("保存")
        self.save_btn.clicked.connect(self._on_save)
        self.start_btn = QPushButton("启动桌宠")
        self.start_btn.clicked.connect(self._on_start_pet)
        self.close_btn = QPushButton("关闭")
        self.close_btn.clicked.connect(self.accept)
        for b in (self.save_btn, self.start_btn, self.close_btn):
            b.setMinimumHeight(38)
            row.addWidget(b)
        root.addLayout(row)

        self._refresh_characters()

    # ---------------- 角色与形象 ----------------
    def _build_character_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(10)

        self.char_combo = QComboBox()
        self.char_combo.currentIndexChanged.connect(self._on_char_changed)
        form.addRow("角色包", self.char_combo)

        self.name_edit = QLineEdit(self.cfg["pet_name"])
        form.addRow("宠物名称", self.name_edit)

        v.addLayout(form)

        import_btn = QPushButton("导入新角色包（选择文件夹）")
        import_btn.clicked.connect(self._import_character)
        v.addWidget(import_btn)

        tip = QLabel(
            "角色包结构：characters/<名称>/ 下放置 frames/（常驻动画帧 *.png，透明背景），"
            "以及可选 character.json。导入时会自动识别帧、生成鼠标点击范围 bboxes.json。"
            "也可直接把一堆 PNG 放进文件夹，工具会自动归到 frames/。"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#888;font-size:11px;")
        v.addWidget(tip)

        v.addStretch(1)
        return w

    # ---------------- 角色设定（人设） ----------------
    def _build_persona_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(10)

        tip = QLabel("设定桌宠的「性格 / 说话风格」。保存后下次启动即生效，也会保留。"
                     "可点“恢复苏璃默认 / 恢复银月默认”填入对应内置人设，再按喜好微调。")
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#888;font-size:11px;")
        v.addWidget(tip)

        self.persona_edit = QTextEdit()
        self.persona_edit.setPlainText(load_persona())
        self.persona_edit.setStyleSheet(
            "QTextEdit{background:#fff;border:1px solid #ffd6e7;border-radius:10px;"
            "padding:8px;color:#333;font-size:12px;}"
        )
        v.addWidget(self.persona_edit, 1)

        row = QHBoxLayout()
        reset_suli_btn = QPushButton("恢复苏璃默认")
        reset_suli_btn.clicked.connect(lambda: self._restore_persona("苏璃"))
        reset_yinyue_btn = QPushButton("恢复银月默认")
        reset_yinyue_btn.clicked.connect(lambda: self._restore_persona("银月"))
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self._save_persona)
        row.addStretch(1)
        row.addWidget(reset_suli_btn)
        row.addWidget(reset_yinyue_btn)
        row.addWidget(save_btn)
        v.addLayout(row)
        return w

    def _restore_persona(self, name: str):
        """填入指定角色的默认人设（保持原文，不自动替换角色名）。"""
        self.persona_edit.setPlainText(DEFAULT_PERSONAS.get(name, DEFAULT_PERSONA))

    def _save_persona(self):
        text = self.persona_edit.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "提示", "角色设定不能为空哦~")
            return
        save_persona(text)
        QMessageBox.information(
            self, "已保存",
            "角色设定已写入 persona.txt，下次启动桌宠（或点“启动桌宠”）即生效。"
        )

    # ---------------- 外观配色 ----------------
    def _build_theme_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(12)

        self.swatches = {}
        form = QFormLayout()
        form.setSpacing(10)
        for key in EDITABLE_KEYS:
            btn = QPushButton()
            btn.setFixedSize(64, 26)
            btn.clicked.connect(lambda _checked, k=key: self._pick_color(k))
            self.swatches[key] = btn
            form.addRow(KEY_LABELS[key], btn)
        v.addLayout(form)

        reset_btn = QPushButton("重置为默认配色")
        reset_btn.clicked.connect(self._reset_colors)
        v.addWidget(reset_btn)

        # 预览
        prev = QGroupBox("预览")
        pv = QVBoxLayout(prev)
        self.prev_title = QLabel("标题文字示例")
        self.prev_btn = QPushButton("按钮示例")
        self.prev_input = QLineEdit("输入框示例")
        pv.addWidget(self.prev_title)
        pv.addWidget(self.prev_btn)
        pv.addWidget(self.prev_input)
        v.addWidget(prev)

        v.addStretch(1)
        self._apply_preview()
        return w

    # ---------------- 行为 ----------------
    def _refresh_characters(self):
        self.char_combo.blockSignals(True)
        self.char_combo.clear()
        chars = character.list_characters()
        pet_name = self.cfg.get("pet_name", "苏璃")
        for c in chars:
            # 默认内置角色在设置里的显示名跟随用户设置的 pet_name
            name = pet_name if c["id"] == DEFAULT_CHARACTER_ID else c["name"]
            self.char_combo.addItem(f"{name}  ({c['id']})", c["id"])
        # 选中当前
        idx = self.char_combo.findData(self.cfg["character_id"])
        if idx >= 0:
            self.char_combo.setCurrentIndex(idx)
        self.char_combo.blockSignals(False)

    def _on_char_changed(self, _i):
        self.cfg["character_id"] = self.char_combo.currentData()

    def _import_character(self):
        d = QFileDialog.getExistingDirectory(self, "选择角色包文件夹")
        if not d:
            return
        src = Path(d)
        cid = src.name
        dst = characters_root() / cid
        if dst.exists():
            QMessageBox.warning(self, "提示", f"已存在同名角色包：{cid}")
            return
        try:
            shutil.copytree(src, dst)
            # 兼容：frames/ 拼写错误、大小写不一致、PNG 在根目录等情况
            frames_dir, norm_msg = self._normalize_character_dir(dst)
            # 确保有 character.json
            meta = dst / "character.json"
            if not meta.exists():
                meta.write_text(
                    json.dumps(
                        {"name": cid, "display_name": cid, "frames": "frames",
                         "bboxes": "bboxes.json", "video": ""},
                        ensure_ascii=False, indent=2,
                    ),
                    encoding="utf-8",
                )
            # 自动识别帧，生成角色范围（鼠标点击范围 bboxes.json）
            bbox_msg = norm_msg
            if self._png_count(frames_dir) > 0:
                try:
                    # compute_bbox 返回的是帧原始像素坐标下的包围盒，
                    # 但桌宠窗口尺寸固定为 BASE_WIDTH×BASE_HEIGHT，
                    # pet_label 用 setScaledContents 把帧拉伸填满窗口，
                    # 因此 human 必须换算到 240×320 画布坐标系，否则遮罩错位。
                    BASE_W, BASE_H = 240, 320
                    hbox = compute_bbox(dst / "frames")  # 原始像素 [x,y,w,h]
                    fw, fh = self._frames_size(dst / "frames")
                    if fw and fh:
                        sx, sy = BASE_W / fw, BASE_H / fh
                        human = [
                            int(round(hbox[0] * sx)),
                            int(round(hbox[1] * sy)),
                            int(round(hbox[2] * sx)),
                            int(round(hbox[3] * sy)),
                        ]
                    else:
                        human = hbox
                    # 裁剪到画布范围内，避免遮罩把窗口切掉（只显示半个）
                    hx, hy, hw, hh = human
                    hx = max(0, min(hx, BASE_W))
                    hy = max(0, min(hy, BASE_H))
                    hw = max(0, min(hw, BASE_W - hx))
                    hh = max(0, min(hh, BASE_H - hy))
                    human = [hx, hy, hw, hh]
                    bboxes = {
                        "human": human,
                        "size": [BASE_W, BASE_H],
                        "clickable": [human] if human[2] > 0 and human[3] > 0 else [],
                    }
                    (dst / "bboxes.json").write_text(
                        json.dumps(bboxes, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    bbox_msg = "\n已自动识别帧、生成角色范围 bboxes.json。"
                except Exception as e:
                    bbox_msg = f"\n（自动生成角色范围失败：{e}）"
            self.cfg["character_id"] = cid
            self._refresh_characters()
            QMessageBox.information(
                self, "成功", f"已导入角色包：{cid}\n保存后重启桌宠生效。{bbox_msg}"
            )
        except Exception as e:
            QMessageBox.critical(self, "导入失败", str(e))

    @staticmethod
    def _frames_size(frames_dir: Path):
        """读取 frames 目录中第一张 PNG 的尺寸，用于 bboxes.size。"""
        pngs = sorted(Path(frames_dir).glob("*.png"))
        if pngs:
            try:
                from PIL import Image
                return Image.open(pngs[0]).size
            except Exception:
                pass
        return [0, 0]

    @staticmethod
    def _png_count(d: Path) -> int:
        return len(list(Path(d).glob("*.png"))) if Path(d).is_dir() else 0

    @staticmethod
    def _normalize_character_dir(cdir: Path) -> tuple[Path, str]:
        """确保 cdir/frames 存在且包含 PNG 帧。

        兼容：frames/ 拼写错误（如 farmes）、大小写不一致（Frames）、
        PNG 直接放在根目录等情况。
        返回 (frames_dir, 提示信息)。
        """
        cdir = Path(cdir)
        frames = cdir / "frames"

        if SettingsTool._png_count(frames) > 0:
            return frames, ""

        # 若已有空 frames，先删掉，避免重命名冲突
        if frames.exists():
            try:
                frames.rmdir()
            except Exception:
                pass

        # 找含 PNG 最多的子目录（候选 frames 文件夹）
        candidates = [
            (p, SettingsTool._png_count(p))
            for p in cdir.iterdir()
            if p.is_dir()
        ]
        candidates = [(p, n) for p, n in candidates if n > 0]
        if candidates:
            best, count = max(candidates, key=lambda x: x[1])
            best.rename(frames)
            return frames, f"\n（已自动把帧文件夹 {best.name} 修正为 frames，共 {count} 帧）"

        # 否则把根目录 PNG 移入 frames/
        pngs = sorted(cdir.glob("*.png"))
        if pngs:
            frames.mkdir(exist_ok=True)
            for p in pngs:
                shutil.move(str(p), str(frames / p.name))
            return frames, f"\n（已把根目录 {len(pngs)} 张 PNG 整理到 frames）"

        return frames, "\n（未找到 PNG 帧，请检查角色包结构）"

    def _pick_color(self, key):
        cur = QColor(self.colors.get(key, "#000000"))
        c = QColorDialog.getColor(cur, self, f"选择{KEY_LABELS[key]}")
        if c.isValid():
            self.colors[key] = c.name()
            self._apply_preview()

    def _reset_colors(self):
        for k in EDITABLE_KEYS:
            self.colors[k] = DEFAULT_THEME_COLORS[k]
        self._apply_preview()

    def _apply_preview(self):
        c = self.colors
        for key, btn in self.swatches.items():
            btn.setStyleSheet(f"background:{c.get(key, '#000')};border:1px solid #999;border-radius:6px;")
        self.prev_title.setStyleSheet(
            f"color:{c['accent']};background:transparent;border:none;font-weight:bold;font-size:13px;"
        )
        self.prev_btn.setStyleSheet(
            f"QPushButton{{background:{c['accent']};color:#fff;border:none;border-radius:8px;padding:6px 12px;}}"
            f"QPushButton:hover{{background:{c['accent_dark']};}}"
        )
        self.prev_input.setStyleSheet(
            f"QLineEdit{{background:#fff;border:1px solid {c['border']};border-radius:8px;"
            f"padding:4px 8px;color:{c['text']};}}"
        )

    def _on_save(self):
        self.cfg["pet_name"] = self.name_edit.text().strip() or "苏璃"
        self.cfg["theme"] = {"name": "custom", "colors": dict(self.colors)}
        save_config(self.cfg)
        # 让本次会话后续打开的对话框（如抠图）也用新配色
        set_theme(Theme.from_dict(self.cfg["theme"]))
        QMessageBox.information(
            self, "已保存",
            "配置已写入 config.json。\n改了角色 / 名称 / 配色后，点下方“启动桌宠”即可即时切换。"
        )

    def _on_start_pet(self):
        # 先保存，确保未点“保存”的改动也能即时生效
        self._on_save()
        # 关闭设置窗口，让桌宠（或新启动的实例）前台显示
        self.accept()
        launch_pet()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setWindowIcon(QIcon(str(_app_dir() / "icon.ico")))
    w = SettingsTool()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
