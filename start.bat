@echo off
setlocal
cd /d "%~dp0"
set "APP_HOST=127.0.0.1"
set "APP_PORT=8000"
set "APP_URL=http://%APP_HOST%:%APP_PORT%"

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
echo %APP_URL%
echo.
echo Keep this window open while using the app.
echo Press Ctrl+C to stop the server.
echo.

call :check_dashboard_running
if "%DASHBOARD_RUNNING%"=="1" (
    echo The app already appears to be running.
    echo Opening the existing dashboard instead of starting a second server.
    echo.
    start "" "%APP_URL%"
    echo If you need to fully restart it, close the old app terminal or press Ctrl+C there first.
    pause
    exit /b 0
)

call :check_port_in_use
if "%PORT_IN_USE%"=="1" (
    echo ERROR: Port %APP_PORT% is already in use, but the dashboard did not respond.
    echo.
    echo Close any old Etsy Listings Automation terminal windows, then try again.
    echo If you cannot find the old process, restart the computer and run this file again.
    pause
    exit /b 1
)

start "" "%APP_URL%"
call ".venv\Scripts\python.exe" -m uvicorn src.server:app --host %APP_HOST% --port %APP_PORT%
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" (
    echo Server stopped.
) else (
    echo ERROR: The server stopped or failed to start. Exit code: %EXIT_CODE%
    echo If this happened instantly, another process may be using port %APP_PORT%.
)
pause
exit /b %EXIT_CODE%

:check_dashboard_running
set "DASHBOARD_RUNNING=0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-WebRequest -UseBasicParsing -Uri '%APP_URL%/api/settings' -TimeoutSec 2; if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>nul
if not errorlevel 1 set "DASHBOARD_RUNNING=1"
exit /b 0

:check_port_in_use
set "PORT_IN_USE=0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $c = Get-NetTCPConnection -LocalPort %APP_PORT% -State Listen -ErrorAction SilentlyContinue; if ($c) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>nul
if not errorlevel 1 (
    set "PORT_IN_USE=1"
    exit /b 0
)
netstat -ano | findstr /R /C:":%APP_PORT% .*LISTENING" >nul 2>nul
if not errorlevel 1 set "PORT_IN_USE=1"
exit /b 0
