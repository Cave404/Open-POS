@echo off
setlocal enabledelayedexpansion
title Open-POS Bootstrapper
cd /d "%~dp0"

echo ===================================================
echo             Open-POS System Launcher
echo ===================================================

REM 1. Verify virtual environment
if not exist "venv\Scripts\python.exe" (
    echo [*] Creating isolated virtual environment...
    python -m venv venv
)

REM 2. Pre-flight dependency check
"venv\Scripts\python.exe" -c "import webview, waitress, flask" >nul 2>&1
if errorlevel 1 (
    echo [*] Installing required system libraries...
    "venv\Scripts\pip.exe" install -r requirements.txt
)

REM 3. Launch Engine
echo [*] Starting Open-POS Engine...
"venv\Scripts\python.exe" run.py

echo.
echo ===================================================
echo Process terminated.
echo ===================================================
pause
