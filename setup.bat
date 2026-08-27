@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
echo ========================================
echo  ArmoryGIS Pro - Windows Setup
echo ========================================
echo.

call scripts\resolve_python.bat
if errorlevel 1 (
    echo [ERROR] Python 3.10+ not found. Install from https://python.org
    pause
    exit /b 1
)

set PYTHON_CMD=%PY%
echo [INFO] Using: %PYTHON_CMD%
%PYTHON_CMD% --version

if not exist "venv" (
    echo [INFO] Creating virtual environment...
    %PYTHON_CMD% -m venv venv
    if !errorlevel! neq 0 (
        echo [ERROR] Failed to create venv.
        pause
        exit /b 1
    )
) else (
    echo [INFO] Virtual environment already exists.
)

echo [INFO] Activating environment...
call venv\Scripts\activate.bat
if !errorlevel! neq 0 (
    echo [ERROR] Failed to activate venv.
    pause
    exit /b 1
)

echo [INFO] Upgrading pip...
python -m pip install --upgrade pip --quiet

echo [INFO] Installing dependencies (this may take a few minutes)...
pip install -r requirements.txt
if !errorlevel! neq 0 (
    echo [ERROR] Dependency installation failed.
    pause
    exit /b 1
)

echo.
set /p seed_db="Seed database with sample US/Israel weapons? (Y/N): "
if /i "!seed_db!"=="Y" (
    echo [INFO] Running database seeder...
    python database/seed_data.py
    if !errorlevel! neq 0 (
        echo [WARN] Seeding failed. You can run 'python database/seed_data.py' manually later.
    )
)

echo.
echo ========================================
echo  Setup Complete!
echo  Run 'start.bat' to launch ArmoryGIS Pro.
echo ========================================
pause
