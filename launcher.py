"""launcher.py — 通用桌宠智能启动器。

设计要点（防"打开无反应"）：
- 不直接在顶部 import PySide6。若 PySide6 缺失或环境异常，脚本不应静默退出，
  而是自动降级到标准库 tkinter 兜底界面（照样能启动 exe / 看说明）。
- 出错时把堆栈写入 launcher_error.log，并尽量用弹窗提示。
- 优先运行已构建的 exe（启动桌宠.exe），没有则退回 python main.py。
- 提供按钮：启动桌宠 / 自定义设置 / 说明。
"""
import os
import subprocess
import sys
import traceback
from pathlib import Path


def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def _pet_exe() -> Path:
    """轻量启动器 exe（仅 ~5MB，调用 venv/python 运行 main.py）。"""
    return _app_dir() / "启动桌宠.exe"


def _settings_exe() -> Path:
    return _app_dir() / "桌宠设置.exe"


def _find_venv_python() -> str:
    """找到同目录 venv 下的 Python；用于源码模式启动。"""
    d = _app_dir()
    for candidate in [
        d / "venv" / "Scripts" / "python.exe",
        d / "venv" / "python.exe",
    ]:
        if candidate.exists():
            return str(candidate)
    return sys.executable


# 热重载请求标记：写入后，正在运行的桌宠会重新读取配置并即时切换角色/名称/配色
RELOAD_FLAG = _app_dir() / "reload_request.flag"


def launch_pet():
    """启动桌宠：有轻量 exe 跑 exe，否则用 venv python 跑 main.py。

    无论桌宠是否已在运行，都先写入“热重载”标记：若已在运行则由它即时切换配置；
    若未运行，新进程启动后会读取最新 config.json，效果一致。实现点击即生效。
    """
    try:
        RELOAD_FLAG.write_text("1", encoding="utf-8")
    except Exception:
        pass

    exe = _pet_exe()
    cwd = str(_app_dir())
    if exe.exists():
        try:
            if sys.platform == "win32":
                os.startfile(str(exe))
            else:
                subprocess.Popen([str(exe)], cwd=cwd)
            return True
        except Exception:
            try:
                subprocess.Popen([str(exe)], cwd=cwd)
                return True
            except Exception:
                pass
    # 源码模式：用 venv python 运行 main.py
    py = _find_venv_python()
    main_py = _app_dir() / "main.py"
    if main_py.exists():
        try:
            subprocess.Popen([py, str(main_py)], cwd=cwd)
            return True
        except Exception:
            return None
    return None


def _launch_script(name: str):
    py = _find_venv_python()
    script = _app_dir() / name
    if script.exists():
        subprocess.Popen([py, str(script)], cwd=str(_app_dir()))


def open_settings():
    # 优先打开已打包的 桌宠设置.exe（自包含、无需 PySide6）；没有再退回到源码
    exe = _settings_exe()
    if exe.exists():
        try:
            os.startfile(str(exe))
            return
        except Exception:
            pass
    _launch_script("settings_tool.py")


def open_readme():
    readme = _app_dir() / "README.md"
    if readme.exists():
        if sys.platform == "win32":
            os.startfile(str(readme))
        else:
            subprocess.Popen(["xdg-open", str(readme)])
    return readme.exists()


def _has_pyside() -> bool:
    try:
        import PySide6  # noqa: F401
        return True
    except Exception:
        return False


def _fatal(msg: str):
    """无 Qt 环境下也尽量把错误显示出来（先写日志，再尝试 tkinter / ctypes 弹窗）。"""
    try:
        (Path(_app_dir()) / "launcher_error.log").write_text(msg, encoding="utf-8")
    except Exception:
        pass
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("启动器错误", msg)
        root.destroy()
        return
    except Exception:
        pass
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, msg, "启动器错误", 0x10)
        return
    except Exception:
        pass


def _run_tk():
    """PySide6 缺失时的兜底启动器（标准库 tkinter，几乎必然可用）。"""
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.title("通用桌宠启动器")
    root.geometry("360x340")
    root.resizable(False, False)

    tk.Label(root, text="通用桌宠工具箱", font=("Microsoft YaHei", 16, "bold")).pack(pady=(22, 2))
    tk.Label(root, text="源码 · 启动器 · 自定义设置", fg="#888").pack()

    def start():
        p = launch_pet()
        if p is not None:
            root.destroy()
        else:
            messagebox.showerror("启动失败", "未找到 启动桌宠.exe 或 main.py，请确认文件完整。")

    tk.Button(
        root, text="▶  启动桌宠", bg="#d6336c", fg="white",
        height=2, font=("Microsoft YaHei", 12, "bold"), command=start,
    ).pack(fill="x", padx=24, pady=(16, 6))

    row = tk.Frame(root)
    row.pack(fill="x", padx=18)
    # 兜底窗口里：若已生成 桌宠设置.exe，则「自定义设置」直接打开它（无需 PySide6）
    settings_exe = _settings_exe()
    if settings_exe.exists():
        tk.Button(row, text="自定义设置", command=open_settings).pack(side="left", expand=True, fill="x", padx=3)
        hint = "自定义设置：已可用（打开桌宠设置.exe）"
    elif _has_pyside():
        tk.Button(row, text="自定义设置", command=open_settings).pack(side="left", expand=True, fill="x", padx=3)
        hint = "自定义设置 已可用"
    else:
        tk.Button(row, text="自定义设置", state="disabled").pack(side="left", expand=True, fill="x", padx=3)
        hint = "提示：请先运行 install_deps.bat 安装 venv 依赖，之后即可使用"

    tk.Button(root, text="说明", command=open_readme).pack(fill="x", padx=24, pady=6)

    tk.Label(root, text=hint, fg="#999", font=("Microsoft YaHei", 9), wraplength=300).pack(pady=8)

    root.mainloop()


def _run_pyside():
    from PySide6.QtWidgets import (
        QApplication, QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QMessageBox,
    )
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont, QIcon

    class Launcher(QDialog):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("通用桌宠启动器")
            self.setFixedSize(360, 300)
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

            icon = _app_dir() / "icon.ico"
            if icon.exists():
                self.setWindowIcon(QIcon(str(icon)))

            root = QVBoxLayout(self)
            root.setContentsMargins(24, 24, 24, 24)
            root.setSpacing(14)

            title = QLabel("通用桌宠工具箱")
            title.setFont(QFont("Microsoft YaHei", 16, QFont.Weight.Bold))
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            root.addWidget(title)

            sub = QLabel("源码 · 启动器 · 自定义设置")
            sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sub.setStyleSheet("color:#888;font-size:11px;")
            root.addWidget(sub)
            root.addStretch(1)

            self.start_btn = QPushButton("▶  启动桌宠")
            self.start_btn.setMinimumHeight(52)
            self.start_btn.setStyleSheet(
                "QPushButton{background:#d6336c;color:#fff;border:none;border-radius:12px;"
                "font-size:16px;font-weight:bold;} QPushButton:hover{background:#a61e4d;}"
            )
            self.start_btn.clicked.connect(self._on_start)
            root.addWidget(self.start_btn)

            row = QHBoxLayout()
            row.setSpacing(10)
            b1 = QPushButton("自定义设置")
            b1.clicked.connect(open_settings)
            b3 = QPushButton("说明")
            b3.clicked.connect(open_readme)
            for b in (b1, b3):
                b.setMinimumHeight(40)
                b.setStyleSheet(
                    "QPushButton{background:#fff0f6;color:#d6336c;border:1px solid #ff9ec2;"
                    "border-radius:10px;font-size:13px;} QPushButton:hover{background:#ffd6e7;}"
                )
                row.addWidget(b)
            root.addLayout(row)

        def _on_start(self):
            p = launch_pet()
            if p:
                self.accept()

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    w = Launcher()
    w.show()
    sys.exit(app.exec())


def main():
    if _has_pyside():
        try:
            _run_pyside()
            return
        except Exception as e:  # noqa: BLE001
            _fatal("PySide6 启动器运行出错：\n%s\n\n%s" % (e, traceback.format_exc()))
    # 兜底：tkinter 界面（无需 PySide6）
    try:
        _run_tk()
    except Exception as e:  # noqa: BLE001
        _fatal("启动器无法启动（含 tkinter 兜底均失败）：\n%s\n\n%s" % (e, traceback.format_exc()))


if __name__ == "__main__":
    main()
