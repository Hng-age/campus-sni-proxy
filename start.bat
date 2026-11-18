@echo off
rem ASCII-safe launcher (use this if the Chinese bat filename is garbled)
fltmc >nul 2>&1
if errorlevel 1 (
    powershell -NoProfile -Command "Start-Process -Verb RunAs -FilePath '%~f0'"
    exit /b
)
cd /d "%~dp0"
title SNI Proxy Manager
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0proxy_manager.ps1"
pause
