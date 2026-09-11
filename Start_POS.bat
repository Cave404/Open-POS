@echo off
setlocal enabledelayedexpansion
title Open-POS System Launcher

cd /d "%~dp0"

echo ===================================================
echo             Open-POS System Launcher
echo ===================================================
echo.

:: 1. Check if virtual environment exists
if not exist "venv\Scripts\python.exe" (
    echo [*] Virtual environment not detected. Creating Python venv...
    python --version >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Python is not installed or not in system PATH.
        echo Please install Python 3.10+ from https://www.python.org/ and ensure
        echo 'Add python.exe to PATH' is checked during installation.
        echo.
        pause
        exit /b 1
    )
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        echo Troubleshooting advice: Check user folder write permissions.
        echo.
        pause
        exit /b 1
    )
    echo [*] Installing dependencies from requirements.txt...
    venv\Scripts\pip.exe install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Failed to install required Python dependencies.
        echo Troubleshooting advice: Verify internet connectivity and re-run Start_POS.bat.
        echo.
        pause
        exit /b 1
    )
    echo [*] Virtual environment configured successfully.
)

:: 2. Ensure isolated data directory structure exists
if not exist "data\config" mkdir "data\config"
if not exist "data\db" mkdir "data\db"
if not exist "data\logs" mkdir "data\logs"
if not exist "data\uploads" mkdir "data\uploads"
if not exist "data\cache" mkdir "data\cache"

:: 3. Execute application through virtual environment
echo [*] Starting Open-POS Engine...
venv\Scripts\python.exe run.py
if errorlevel 1 (
    echo.
    echo ===================================================
    echo [ERROR] Open-POS encountered an unexpected error.
    echo ===================================================
    echo Troubleshooting advice:
    echo 1. Check if another instance of Open-POS is already running.
    echo 2. Check logs in data\logs\ or system event viewer.
    echo 3. To reinstall packages, delete the 'venv' directory and restart.
    echo.
    pause
    exit /b 1
)

exit /b 0
