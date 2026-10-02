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
set "ISCC_PATH="
if exist "C:\Program Files\Inno Setup 7\ISCC.exe" set "ISCC_PATH=C:\Program Files\Inno Setup 7\ISCC.exe"
if not defined ISCC_PATH if exist "C:\Program Files (x86)\Inno Setup 7\ISCC.exe" set "ISCC_PATH=C:\Program Files (x86)\Inno Setup 7\ISCC.exe"
if not defined ISCC_PATH if exist "C:\Program Files\Inno Setup 6\ISCC.exe" set "ISCC_PATH=C:\Program Files\Inno Setup 6\ISCC.exe"
if not defined ISCC_PATH if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set "ISCC_PATH=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not defined ISCC_PATH (
    for /f "delims=" %%I in ('where ISCC.exe 2^>nul') do set "ISCC_PATH=%%I"
)

if defined ISCC_PATH (
    echo Using Inno Setup Compiler at: "!ISCC_PATH!"
    "!ISCC_PATH!" packaging\installer.iss
    if %ERRORLEVEL% neq 0 (
        echo Error: Inno Setup compilation failed.
        exit /b %ERRORLEVEL%
    )
    echo Successfully generated installer in dist_installer\
) else (
    echo Warning: ISCC.exe not found. PyInstaller distribution generated, but Setup.exe was skipped.
    echo Install Inno Setup 6 or 7 to generate Setup.exe automatically.
)

echo Build process complete.
endlocal
