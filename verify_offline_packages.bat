@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title ArmoryGIS Pro - Verify Offline Packages
color 0E

echo ========================================
echo   Verify offline_packages folder
echo ========================================
echo.

if not exist "offline_packages\" (
    echo [FAIL] offline_packages folder not found.
    echo Run download_offline_packages.bat first.
    pause
    exit /b 1
)

call scripts\resolve_python.bat
if errorlevel 1 (
    echo [FAIL] Python 3.10+ required to run verification script.
    pause
    exit /b 1
)

%PY% scripts\verify_offline_wheels.py
if errorlevel 1 (
    pause
    exit /b 1
)

echo.
pause
exit /b 0
