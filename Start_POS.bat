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
        pause
        exit /b 1
    )
)

:: 2. Pre-flight dependency check
"venv\Scripts\python.exe" -c "import webview, waitress, flask" >nul 2>&1
if errorlevel 1 (
    echo [*] Installing required system libraries (bypassing locked cache)...
    "venv\Scripts\pip.exe" install -r requirements.txt --no-cache-dir
    if errorlevel 1 (
        echo.
        echo ===================================================
        echo [ERROR] Dependency installation failed.
        echo Check permissions or close background Python apps.
        echo ===================================================
        pause
        exit /b 1
    )
)

:: 3. Launch Engine
echo [*] Starting Open-POS Engine...
"venv\Scripts\python.exe" run.py

echo.
echo ===================================================
echo Process terminated.
echo ===================================================
pause
