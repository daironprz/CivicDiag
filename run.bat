@echo off
rem CivicDiag launcher — installs the one dependency if missing, then starts the app.
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found. Install it from https://www.python.org/downloads/
    echo and check "Add python.exe to PATH" during install.
    pause
    exit /b 1
)

python -c "import serial" >nul 2>nul
if errorlevel 1 (
    echo Installing pyserial (one-time setup)...
    python -m pip install --quiet pyserial
)

start "CivicDiag" pythonw main.py
