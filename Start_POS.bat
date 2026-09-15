@echo off
setlocal enabledelayedexpansion
title Open-POS System Launcher
cd /d "%~dp0"

REM Bypass Windows AppData pip cache locks globally
set PIP_NO_CACHE_DIR=1

echo ===================================================
echo             Open-POS System Launcher
echo ===================================================

REM 1. Verify Python is installed and accessible on PATH
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 3.12+ was not found on your system PATH.
    echo Please install Python and ensure "Add python.exe to PATH" is checked.
    echo.
    pause
    exit /b 1
)

REM 2. Verify or create the isolated virtual environment
if not exist "venv\Scripts\python.exe" (
    echo [*] Creating isolated virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo.
        echo [ERROR] Failed to create virtual environment.
        echo.
        pause
        exit /b 1
    )
)

REM 3. Pre-flight check: Verify core dependencies
"venv\Scripts\python.exe" -c "import webview, waitress, flask" >nul 2>&1
if errorlevel 1 (
    echo [*] Incomplete or missing dependencies detected.
    echo [*] Installing required libraries from requirements.txt...
    echo [*] (This may take 1-2 minutes during first run)
    echo.

    "venv\Scripts\python.exe" -m pip install -r requirements.txt --no-cache-dir

    REM Re-verify critical imports after installation
    "venv\Scripts\python.exe" -c "import webview, waitress, flask" >nul 2>&1
    if errorlevel 1 (
        echo.
        echo ===================================================
        echo [ERROR] Dependency installation did not complete.
        echo ===================================================
        echo Troubleshooting:
        echo 1. Close any running background Python apps in Task Manager.
        echo 2. Check your internet connection for package downloads.
        echo 3. Check data\logs\ for details.
        echo.
        pause
        exit /b 1
    )
    echo [*] Core dependencies installed and verified successfully.
    echo.
)

REM 4. Launch the OpenPOS Engine
echo [*] Starting Open-POS Engine...
"venv\Scripts\python.exe" run.py

if errorlevel 1 (
    echo.
    echo ===================================================
    echo [ERROR] Open-POS shut down unexpectedly.
    echo ===================================================
    echo If another POS is currently active, ensure port 5000 is free.
    echo Check data\logs\ for diagnostic traces.
    echo.
)

echo.
echo ===================================================
echo Launcher finished. Press any key to close window...
echo ===================================================
pause >nul
