@echo off
setlocal
cd /d "%~dp0"

echo ==========================================
echo Etsy Listings Automation - Update
echo ==========================================
echo.

where git >nul 2>nul
if errorlevel 1 (
    echo ERROR: Git was not found.
    echo Install Git, or update by downloading a fresh ZIP from the repository.
    pause
    exit /b 1
)

if not exist ".git" (
    echo ERROR: This folder is not a Git clone.
    echo Use the ZIP update flow, or clone the repository with Git.
    pause
    exit /b 1
)

echo Pulling latest code...
git pull
if errorlevel 1 (
    echo ERROR: git pull failed.
    echo If you have local changes, save them first or ask Tyrone for help.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment not found. Creating it now...
    python -m venv .venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment.
        pause
        exit /b 1
    )
)

echo.
echo Installing/updating dependencies...
call ".venv\Scripts\python.exe" -m pip install --upgrade pip
call ".venv\Scripts\pip.exe" install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install dependencies.
    pause
    exit /b 1
)

echo.
echo Update complete.
echo Run start.bat to launch the latest version.
pause
