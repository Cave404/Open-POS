@echo off
setlocal enabledelayedexpansion

echo ============================================================
echo OpenPOS Production Distribution ^& Installer Builder
echo ============================================================

cd /d "%~dp0\.."

:: 1. Verify Virtual Environment
if not exist "venv\Scripts\python.exe" (
    echo Error: Virtual environment not found at .\venv.
    echo Please create the virtual environment and install requirements first.
    exit /b 1
)

:: 2. Ensure WebView2 Bootstrapper exists for offline bundling
if not exist "packaging\MicrosoftEdgeWebview2Setup.exe" (
    echo Downloading Microsoft Edge WebView2 Evergreen Bootstrapper...
    powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object System.Net.WebClient).DownloadFile('https://go.microsoft.com/fwlink/p/?LinkId=2124703', 'packaging\MicrosoftEdgeWebview2Setup.exe')"
    if not exist "packaging\MicrosoftEdgeWebview2Setup.exe" (
        echo Warning: Failed to download WebView2 bootstrapper. Bundled installer will rely on existing system runtime.
    )
)

:: 3. Clean stale build artifacts
echo Cleaning previous build caches...
if exist "build" rd /s /q "build"
if exist "dist" rd /s /q "dist"
if exist "dist_installer" rd /s /q "dist_installer"

:: 4. Compile Standalone Binary via Venv PyInstaller
echo Compiling OpenPOS executable using virtual environment...
call venv\Scripts\pyinstaller.exe --noconfirm --clean packaging/openpos.spec
if %ERRORLEVEL% neq 0 (
    echo Error: PyInstaller build failed.
    exit /b %ERRORLEVEL%
)

if not exist "dist\OpenPOS\OpenPOS.exe" (
    echo Error: dist\OpenPOS\OpenPOS.exe was not created.
    exit /b 1
)

:: 5. Compile Inno Setup Installer
echo Compiling Inno Setup Windows Installer...
set "ISCC_PATH=C:\Program Files\Inno Setup 7\ISCC.exe"
if not exist "%ISCC_PATH%" set "ISCC_PATH=C:\Program Files (x86)\Inno Setup 7\ISCC.exe"
if not exist "%ISCC_PATH%" set "ISCC_PATH=C:\Program Files\Inno Setup 6\ISCC.exe"
if not exist "%ISCC_PATH%" set "ISCC_PATH=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"

if exist "%ISCC_PATH%" (
    echo Using Inno Setup compiler: "%ISCC_PATH%"
    "%ISCC_PATH%" packaging\installer.iss
    if %ERRORLEVEL% neq 0 (
        echo Error: Inno Setup compilation failed.
        exit /b %ERRORLEVEL%
    )
    echo ============================================================
    echo Build Successful: Installer generated in dist_installer\
    echo ============================================================
) else (
    echo Warning: Inno Setup compiler ISCC.exe not found.
    echo Standalone executable is available at dist\OpenPOS\OpenPOS.exe
)

endlocal
