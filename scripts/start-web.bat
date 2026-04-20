@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
set "LAUNCHER=%SCRIPT_DIR%start-web.py"
set "PYTHON_CMD="
set "LAUNCHED_BY_DOUBLECLICK=0"

if "%~1"=="" set "LAUNCHED_BY_DOUBLECLICK=1"

where py >nul 2>nul
if not errorlevel 1 set "PYTHON_CMD=py -3"

if not defined PYTHON_CMD (
    where python >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD (
    echo Python 3 was not found. Install Python first.
    pause
    exit /b 1
)

%PYTHON_CMD% "%LAUNCHER%" %*
set "EXIT_CODE=%ERRORLEVEL%"

if "%LAUNCHED_BY_DOUBLECLICK%"=="1" (
    if "%EXIT_CODE%"=="0" (
        echo.
        echo Web UI started. Default URL: http://127.0.0.1:9090
        echo Launcher log pointer: %~dp0..\web-logs\launcher-latest.log
        pause
    ) else (
        echo.
        echo Startup failed. Check %~dp0..\web-logs\launcher-latest.log
        pause
    )
) else (
    if not "%EXIT_CODE%"=="0" pause
)

exit /b %EXIT_CODE%
