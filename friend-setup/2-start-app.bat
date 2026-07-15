@echo off
setlocal
cd /d "%~dp0.."
if not exist "start.bat" (
    echo ERROR: start.bat was not found.
    echo.
    echo Make sure you extracted the full GitHub ZIP first, or cloned the full repo.
    echo Do not run this file from inside the ZIP preview, and do not copy only the friend-setup folder.
    echo.
    pause
    exit /b 1
)
call start.bat
