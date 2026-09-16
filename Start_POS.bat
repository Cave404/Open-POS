@echo off
setlocal enabledelayedexpansion
title Open-POS System Launcher
cd /d "%~dp0"

REM Force pip to completely bypass locked AppData cache folders
set PIP_NO_CACHE_DIR=1

echo ===================================================
echo             Open-POS System Launcher
echo ===================================================

REM 1. Verify Python availability
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python was not found on your system PATH.
    echo Please install Python 3.12+ and check "Add python.exe to PATH".
    echo.
    pause
    exit /b 1
)

REM 2. Verify or create virtual environment
if not exist "venv\Scripts\python.exe" (
    echo [*] Creating isolated virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to initialize virtual environment.
        pause
        exit /b 1
    )
)

REM 3. Pre-flight dependency check
"venv\Scripts\python.exe" -c "import webview, waitress, flask, psycopg, cryptography" >nul 2>&1
if errorlevel 1 (
    echo [*] Installing or updating required dependencies...
    echo [*] (Pip cache bypass active to prevent Windows file locks)
    echo.
    "venv\Scripts\python.exe" -m pip install -r requirements.txt --no-cache-dir
    
    REM Post-install validation
    "venv\Scripts\python.exe" -c "import webview, waitress, flask" >nul 2>&1
    if errorlevel 1 (
        echo.
        echo ===================================================
        echo [ERROR] Dependency installation failed.
        echo ===================================================
        echo 1. Ensure any other running Python apps or older POS systems are closed.
        echo 2. Check internet connection for package downloads.
        echo 3. Check data\logs\ for installation traces.
        echo.
        pause
        exit /b 1
    )
    echo [*] Dependencies verified successfully.
    echo.
)

REM 4. Launch Application
echo [*] Starting Open-POS Engine...
"venv\Scripts\python.exe" run.py

if errorlevel 1 (
    echo.
    echo ===================================================
    echo [ERROR] Open-POS shut down unexpectedly.
    echo ===================================================
    echo Check data\logs\openpos_system.log for details.
    echo.
    pause
)
