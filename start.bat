@echo off
setlocal
cd /d "%~dp0"

echo ==========================================
echo Etsy Listings Automation - Start App
echo ==========================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Virtual environment not found.
    echo Run setup.bat first.
    pause
    exit /b 1
)

if not exist ".env" (
    echo WARNING: .env file not found.
    echo The app can start, but AI/API features may fail until keys are added.
    echo.
)

echo Dashboard will be available at:
echo http://localhost:8000
echo.
echo Keep this window open while using the app.
echo Press Ctrl+C to stop the server.
echo.

start "" "http://localhost:8000"
call ".venv\Scripts\python.exe" -m uvicorn src.server:app --host 127.0.0.1 --port 8000
