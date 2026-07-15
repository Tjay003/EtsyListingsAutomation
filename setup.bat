@echo off
setlocal
cd /d "%~dp0"

echo ==========================================
echo Etsy Listings Automation - First-Time Setup
echo ==========================================
echo.

set "PYTHON_CMD="

where python >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD (
    where py >nul 2>nul
    if not errorlevel 1 (
        py -3 --version >nul 2>nul
        if not errorlevel 1 (
            set "PYTHON_CMD=py -3"
        )
    )
)

if not defined PYTHON_CMD (
    echo ERROR: Python was not found.
    echo Install Python 3.11 or newer from https://www.python.org/downloads/
    echo IMPORTANT: During install, check "Add python.exe to PATH".
    echo Then close this window and run setup again.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    %PYTHON_CMD% -m venv .venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment.
        echo If Python was just installed, restart the computer or reinstall Python with PATH enabled.
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
    if exist ".env.example" (
        echo Creating .env from .env.example...
        copy ".env.example" ".env" >nul
        echo IMPORTANT: Open .env and add the private API keys before using AI features.
        echo.
    ) else (
        echo IMPORTANT: Create a .env file in this folder before starting the app.
        echo Minimum recommended values:
        echo GEMINI_API_KEY=your_key_here
        echo FAL_KEY=your_key_here
        echo OUTPUT_DIR=%%USERPROFILE%%\Downloads\AliExpressQueue
        echo.
    )
) else (
    echo .env found.
)

echo Setup complete.
echo Run start.bat to launch the app.
pause
