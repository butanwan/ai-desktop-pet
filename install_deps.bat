@echo off
setlocal enabledelayedexpansion
chcp 936 >nul 2>&1
title Universal Desktop Pet - Install Dependencies

echo ============================================
echo   Universal Desktop Pet - First-time Setup
echo ============================================
echo.

cd /d "%~dp0"

:: ---- Detect Python (try python, py, python3) ----
set PYTHON=
where python >nul 2>&1 && set PYTHON=python
if "%PYTHON%"=="" (
    where py >nul 2>&1 && set PYTHON=py
)
if "%PYTHON%"=="" (
    where python3 >nul 2>&1 && set PYTHON=python3
)

if "%PYTHON%"=="" (
    echo [ERROR] Python not found!
    echo   Please install Python 3.10 or newer first.
    echo   Download: https://www.python.org/downloads/
    echo   IMPORTANT: Tick "Add python.exe to PATH" during install!
    pause
    exit /b 1
)

:: Show detected version
for /f "tokens=2 delims= " %%v in ('%PYTHON% --version 2^>^&1') do (
    echo Found: %%v
)
echo.

:: ---- Create venv if missing ----
if not exist "venv\Scripts\python.exe" (
    echo [1/2] Creating virtual environment...
    %PYTHON% -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create venv! Check Python version ^>= 3.10.
        pause
        exit /b 1
    )
    echo       venv created successfully.
) else (
    echo [1/2] venv already exists, skipping.
)
echo.

:: ---- Upgrade pip first ----
echo [2/2a] Upgrading pip...
call venv\Scripts\python.exe -m pip install --upgrade pip -q
if errorlevel 1 (
    echo [WARN] pip upgrade failed, continuing anyway...
)
echo.

:: ---- Install dependencies with progress visible ----
echo [2/2b] Installing PySide6 numpy Pillow ...
echo       This downloads packages, please be patient...
echo.
call venv\Scripts\pip.exe install PySide6 numpy Pillow --progress-bar on

if errorlevel 1 (
    echo.
    echo [ERROR] Installation failed! Trying Tsinghua mirror...
    echo.
    call venv\Scripts\pip.exe install PySide6 numpy Pillow -i https://pypi.tuna.tsinghua.edu.cn/simple --progress-bar on
    if errorlevel 1 (
        echo.
        echo [ERROR] Mirror also failed. Possible causes:
        echo   1. Network issue - check your internet connection
        echo   2. Python version incompatible - need 3.10 or newer
        echo   3. Run this bat as Administrator if needed
        pause
        exit /b 1
    )
)

:: ---- Verify installation ----
echo.
echo ============================================
echo   Verifying installation...
call venv\Scripts\python.exe -c "import PySide6; import numpy; from PIL import Image; print('All OK')" 2>nul
if errorlevel 1 (
    echo [ERROR] Verification failed! Some packages may be corrupted.
    echo   Try running this bat again.
) else (
    echo   All dependencies installed and verified OK!
)
echo ============================================
echo.
echo   You can now:
echo   - Double-click the pet launcher  (.exe) to start the pet
echo   - Double-click the settings      (.exe) to open settings
echo.
pause
