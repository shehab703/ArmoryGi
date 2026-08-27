@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title ArmoryGIS Pro - Offline Install
color 0A

echo ========================================
echo   ArmoryGIS Pro - Offline Installation
echo ========================================
echo.

if not exist "offline_packages\" (
    echo [ERROR] offline_packages folder not found.
    echo Run download_offline_packages.bat on a PC with internet first.
    pause
    exit /b 1
)

call scripts\resolve_python.bat
if errorlevel 1 (
    echo [ERROR] Python 3.10+ not found. Install Python first.
    pause
    exit /b 1
)

echo [*] Using: %PY%
%PY% --version
echo.

echo [*] Checking offline wheels for this Python version...
%PY% scripts\verify_offline_wheels.py --for-current-python
if errorlevel 1 (
    echo.
    echo [ERROR] offline_packages is incomplete or missing wheels for this Python.
    echo On a PC with internet, re-run download_offline_packages.bat and copy the
    echo entire armorygis_pro folder again ^(including offline_packages^).
    pause
    exit /b 1
)
echo.

if exist "venv\" (
    echo [*] Removing old venv for clean offline install...
    rmdir /s /q "venv" 2>nul
)

echo [*] Creating virtual environment...
%PY% -m venv venv
if errorlevel 1 (
    echo [ERROR] Failed to create venv.
    pause
    exit /b 1
)

call venv\Scripts\activate.bat
if errorlevel 1 (
    echo [ERROR] Failed to activate venv.
    pause
    exit /b 1
)

echo [*] Installing bootstrap pip/setuptools/wheel (no internet)...
python -m pip install --no-index --find-links=offline_packages pip setuptools wheel packaging
if errorlevel 1 (
    echo [WARN] Bootstrap install failed; trying without packaging...
    python -m pip install --no-index --find-links=offline_packages pip setuptools wheel
)

echo [*] Installing from local wheels (no internet)...
python -m pip install --no-index --find-links=offline_packages -r requirements-offline.txt
if errorlevel 1 (
    echo [ERROR] Offline install failed.
    echo If PyQt6-sip was missing, re-download packages with download_offline_packages.bat
    echo ^(must include wheels for Python 3.10, 3.11, and 3.12^).
    pause
    exit /b 1
)

echo [*] Verifying PyQt6 WebEngine...
python -c "import PyQt6; import PyQt6.QtWebEngineWidgets; print('PyQt6 WebEngine OK')"
if errorlevel 1 (
    echo [ERROR] PyQt6 WebEngine verification failed.
    pause
    exit /b 1
)

echo.
echo [OK] Offline install complete.
echo Run: start.bat  or  run_embed.bat  or embed from C# host.
echo.
pause
