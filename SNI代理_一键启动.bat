@echo off
rem Auto-elevate: re-launch this bat as administrator when needed
fltmc >nul 2>&1
if errorlevel 1 (
    powershell -NoProfile -Command "Start-Process -Verb RunAs -FilePath '%~f0'"
    exit /b
)
cd /d "%~dp0"
title SNI Proxy Manager
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0proxy_manager.ps1"
pause
