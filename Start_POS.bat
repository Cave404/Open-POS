@echo off
setlocal enabledelayedexpansion
title Open-POS Bootstrapper
cd /d "%~dp0"

echo ===================================================
echo             Open-POS System Launcher
echo ===================================================

:: 1. Verify or create virtual environment
if not exist "venv\Scripts\python.exe" (
    echo [*] Creating isolated virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo [!] ERROR: Python 3.12+ was not found on PATH.
        echo Please install Python and check "Add Python to PATH".
        pause
        exit /b 1
    )
)

:: 2. Verify dependencies (check webview as sentinel)
"venv\Scripts\python.exe" -c "import webview, waitress, flask" >nul 2>&1
if errorlevel 1 (
    echo [*] Installing required system libraries (this may take a minute)...
    "venv\Scripts\python.exe" -m pip install --upgrade pip >nul 2>&1
    "venv\Scripts\pip.exe" install -r requirements.txt
    if errorlevel 1 (
        echo [!] ERROR: Failed to install requirements.
        pause
        exit /b 1
    )
)

:: 3. Launch with local venv Python
echo [*] Starting Open-POS Engine...
"venv\Scripts\python.exe" run.py

if errorlevel 1 (
    echo.
    echo ===================================================
    echo [ERROR] Open-POS encountered an unexpected shutdown.
    echo ===================================================
    echo Troubleshooting advice:
    echo 1. Check if another instance or port 5000 is occupied.
    echo 2. Check diagnostic logs in data\logs\openpos_system.log.
    echo 3. To reset packages, delete the 'venv' folder and re-run.
    pause
)
