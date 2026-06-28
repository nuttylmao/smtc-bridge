@echo off
setlocal

echo --- Checking Dependencies ---
:: Ensure pip is installed
python -m ensurepip --default-pip >nul 2>&1

:: Install or upgrade requirements
pip install -r requirements.txt

:: Ensure PyInstaller is installed
pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing PyInstaller...
    pip install pyinstaller
)

echo.
echo --- Cleaning Old Builds ---
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"

echo.
echo --- Building Executable ---
pyinstaller --noconfirm smtc-bridge.spec

echo.
echo --- Build Complete! ---
echo Check the 'dist' folder for your smtc-bridge.exe.
pause