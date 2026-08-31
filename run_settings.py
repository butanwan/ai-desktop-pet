"""run_settings.py — 轻量桌宠设置工具启动器（无控制台）。

只负责：找到同目录 venv 下的无控制台 Python（pythonw），执行 settings_tool.py。
自身不导入任何重型依赖，打包后仅 ~7MB。通过 pythonw 运行，不弹出黑色命令行窗口。
"""
import ctypes
import os
import subprocess
import sys
from pathlib import Path


def _app_dir() -> Path:
    return Path(sys.executable).parent


def _venv_python():
    """返回 venv 里的 pythonw/python 路径；没有 venv 则返回 None。"""
    app_dir = _app_dir()
    for cand in (app_dir / "venv" / "Scripts" / "pythonw.exe",
                 app_dir / "venv" / "Scripts" / "python.exe"):
        if cand.exists():
            return str(cand)
    return None


def _bootstrap_venv():
    """没有 venv 时引导用户运行 install_deps.bat。"""
    for name in ("install_deps.bat", "安装依赖.bat"):
        bat = _app_dir() / name
        if bat.exists():
            try:
                os.startfile(str(bat))
            except Exception:
                pass
            break
    try:
        ctypes.windll.user32.MessageBoxW(
            0,
            "未检测到运行环境（venv）。\n已为你打开「install_deps.bat」，请运行它完成一次依赖安装后，再启动本程序。",
            "桌宠设置", 0)
    except Exception:
        pass


def main():
    venv_python = _venv_python()
    if venv_python is None:
        _bootstrap_venv()
        sys.exit(1)

    script_dir = _app_dir()
    target = script_dir / "settings_tool.py"
    if not target.exists():
        target = Path(__file__).parent / "settings_tool.py"
    if not target.exists():
        sys.stderr.write(f"错误：找不到 settings_tool.py（搜索路径：{target}）\n")
        sys.exit(1)

    logf = None
    if sys.platform == "win32":
        try:
            logf = open(script_dir / "settings_debug.log", "a", encoding="utf-8")
        except Exception:
            logf = None

    flags = 0
    if sys.platform == "win32":
        flags = (getattr(subprocess, "DETACHED_PROCESS", 0) |
                 getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))

    try:
        subprocess.Popen(
            [venv_python, str(target)],
            cwd=str(script_dir),
            stdout=logf,
            stderr=logf,
            creationflags=flags,
            close_fds=(os.name == "nt"),
        )
    except Exception as e:
        sys.stderr.write(f"启动失败: {e}\n")
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
