@echo off
setlocal enabledelayedexpansion
title Open-POS System Bootstrapper
cd /d "%~dp0"

:: Force pip to completely bypass Windows AppData cache locks
set PIP_NO_CACHE_DIR=1

echo ===================================================
echo             Open-POS System Launcher
echo ===================================================

:: 1. Verify or create virtual environment
if not exist "venv\Scripts\python.exe" (
    echo [*] Creating isolated virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo.
        echo [ERROR] Python 3.12+ was not found on your system PATH.
        echo Please install Python and check "Add python.exe to PATH".
        pause
        exit /b 1
    )
)

:: 2. Strict Pre-Flight Dependency Gate
echo [*] Verifying core dependencies...
"venv\Scripts\python.exe" -c "import webview, waitress, flask, psycopg, cryptography" >nul 2>&1
if errorlevel 1 (
    echo [*] Installing required system libraries (first-run setup)...
    echo [*] Cache bypass active to prevent Windows file lock errors.
    
    :: Attempt cache purge in case of corrupted wheels
    "venv\Scripts\python.exe" -m pip cache purge >nul 2>&1
    
    :: Install packages with direct output
    "venv\Scripts\python.exe" -m pip install -r requirements.txt
    
    :: Re-verify installation success before allowing launch
    "venv\Scripts\python.exe" -c "import webview, waitress, flask" >nul 2>&1
    if errorlevel 1 (
        echo.
        echo ===================================================
        echo [FATAL] Dependency installation could not complete.
        echo ===================================================
        echo Troubleshooting:
        echo 1. Ensure any other running POS or Python apps are closed.
        echo 2. Check your internet connection for package downloads.
        echo 3. Verify antivirus is not blocking pip from writing to venv.
        pause
        exit /b 1
    )
    echo [*] Dependencies installed and verified successfully!
)

:: 3. Launch Engine & Setup Wizard
echo [*] Starting Open-POS Engine...
"venv\Scripts\python.exe" run.py

if errorlevel 1 (
    echo.
    echo ===================================================
    echo [ERROR] Open-POS shutdown unexpectedly.
    echo Check logs in data\logs\openpos_system.log
    echo ===================================================
)

echo.
pause
