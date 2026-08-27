@echo off
setlocal EnableDelayedExpansion
echo [DEBUG MODE] Starting ArmoryGIS Pro with console logging...
if not exist "venv\Scripts\activate.bat" (
    echo [ERROR] Run 'setup.bat' first.
    pause
    exit /b 1
)

call venv\Scripts\activate.bat
set ARMORYGIS_DEBUG=true
python main.py
if %errorlevel% neq 0 pause