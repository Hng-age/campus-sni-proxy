@echo off
rem =======================================================
rem  SNI Proxy Desktop 2.0.0 - 桌面图形版启动器
rem =======================================================
cd /d "%~dp0"
title SNI Proxy Desktop

if exist "dist\SNI Proxy Desktop\SNI Proxy Desktop.exe" (
    start "" "dist\SNI Proxy Desktop\SNI Proxy Desktop.exe"
    exit /b 0
)

if exist "SNI Proxy Desktop.exe" (
    start "" "SNI Proxy Desktop.exe"
    exit /b 0
)

set "PY_EXE="
where python >nul 2>&1
if not errorlevel 1 set "PY_EXE=python"

if not defined PY_EXE (
    if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PY_EXE=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
)
if not defined PY_EXE (
    if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY_EXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
)
if not defined PY_EXE (
    if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PY_EXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
)
if not defined PY_EXE (
    if exist "%ProgramFiles%\Python313\python.exe" set "PY_EXE=%ProgramFiles%\Python313\python.exe"
)

if not defined PY_EXE (
    echo   [!!] 未检测到 Python，请先安装 Python 3.8+ 并勾选 Add python.exe to PATH
    echo        https://www.python.org/downloads/
    pause
    exit /b 1
)

"%PY_EXE%" -c "import PySide6" >nul 2>&1
if errorlevel 1 (
    echo   [*] 首次运行：正在安装 GUI 依赖 PySide6...
    "%PY_EXE%" -m pip install --quiet PySide6 2>nul
    if errorlevel 1 (
        "%PY_EXE%" -m pip install --quiet -i https://pypi.tuna.tsinghua.edu.cn/simple PySide6
    )
)

start "" "%PY_EXE%" main.py
