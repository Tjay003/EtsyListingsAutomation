@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "REPO_ROOT=%%~fI"
set "TARGET_SCRIPT=%REPO_ROOT%\start.bat"

if not exist "%TARGET_SCRIPT%" (
    echo ERROR: start.bat was not found.
    echo.
    echo This launcher is checking here:
    echo "%TARGET_SCRIPT%"
    echo.
    echo Make sure you extracted the full GitHub ZIP first, or cloned the full repo.
    echo Do not run this file from inside the ZIP preview, and do not copy only the friend-setup folder.
    echo.
    pause
    exit /b 1
)

pushd "%REPO_ROOT%"
if errorlevel 1 (
    echo ERROR: Could not open the project folder:
    echo "%REPO_ROOT%"
    echo.
    pause
    exit /b 1
)

call "%TARGET_SCRIPT%"
set "EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %EXIT_CODE%
