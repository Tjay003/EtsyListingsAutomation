@echo off
setlocal
cd /d "%~dp0"

echo ==========================================
echo Etsy Listings Automation - First-Time Setup
echo ==========================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo ERROR: Python was not found.
    echo Install Python 3.11 or newer, then run this file again.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment.
        pause
        exit /b 1
    )
) else (
    echo Virtual environment already exists.
)

echo.
echo Installing dependencies...
call ".venv\Scripts\python.exe" -m pip install --upgrade pip
call ".venv\Scripts\pip.exe" install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install dependencies.
    pause
    exit /b 1
)

echo.
if not exist ".env" (
    echo IMPORTANT: Create a .env file in this folder before starting the app.
    echo Minimum recommended values:
    echo GEMINI_API_KEY=your_key_here
    echo FAL_KEY=your_key_here
    echo OUTPUT_DIR=%%USERPROFILE%%\Downloads\AliExpressQueue
    echo.
) else (
    echo .env found.
)

echo Setup complete.
echo Run start.bat to launch the app.
pause
