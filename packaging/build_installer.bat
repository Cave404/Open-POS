@echo off
setlocal enabledelayedexpansion

echo ============================================================
echo Building OpenPOS Production Distribution
echo ============================================================

cd /d "%~dp0\.."

echo [1/3] Compiling standalone executable via PyInstaller...
call venv\Scripts\activate.bat
pyinstaller --noconfirm --clean packaging/openpos.spec
if %ERRORLEVEL% neq 0 (
    echo Error: PyInstaller build failed.
    exit /b %ERRORLEVEL%
)

echo [2/3] Verifying dist/OpenPOS output...
if not exist "dist\OpenPOS\OpenPOS.exe" (
    echo Error: dist\OpenPOS\OpenPOS.exe not found.
    exit /b 1
)

echo [3/3] Compiling Inno Setup Windows Installer...
set "ISCC_PATH=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist "%ISCC_PATH%" (
    set "ISCC_PATH=C:\Program Files\Inno Setup 6\ISCC.exe"
)

if exist "%ISCC_PATH%" (
    "%ISCC_PATH%" packaging\installer.iss
    if %ERRORLEVEL% neq 0 (
        echo Error: Inno Setup compilation failed.
        exit /b %ERRORLEVEL%
    )
    echo Successfully generated installer in dist_installer\
) else (
    echo Warning: ISCC.exe not found. PyInstaller distribution generated, but Setup.exe was skipped.
    echo Install Inno Setup 6 to generate Setup.exe automatically.
)

echo Build process complete.
endlocal
