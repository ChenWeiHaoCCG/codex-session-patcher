@echo off
setlocal

set VERSION=1.4.1

echo === Codex Session Patcher Build ===
echo Version: %VERSION%

echo Cleaning previous build artifacts...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist *.egg-info rmdir /s /q *.egg-info

echo Installing build dependency...
pip install pyinstaller
if errorlevel 1 exit /b 1

echo Building CLI executable...
pyinstaller codex-patcher.spec --clean -y
if errorlevel 1 exit /b 1

echo Building Web Launcher executable...
pyinstaller codex-web-launcher.spec --clean -y
if errorlevel 1 exit /b 1

if exist dist\codex-patcher (
    echo CLI build output:
    dir dist\codex-patcher
)

if exist dist\codex-patcher-launcher (
    echo Web Launcher build output:
    dir dist\codex-patcher-launcher
)

echo === Build complete ===
