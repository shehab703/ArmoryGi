@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title ArmoryGIS Pro - Embed Test

if exist "venv\Scripts\python.exe" (
    venv\Scripts\python.exe scripts\embed_diagnose.py --quiet
    if errorlevel 1 (
        echo.
        echo Run install_offline.bat on THIS PC, then retry.
        pause
        exit /b 1
    )
)

if exist "venv\Scripts\pythonw.exe" (
    venv\Scripts\pythonw.exe embed_launcher.py --skip-login --embedded
) else if exist "venv\Scripts\python.exe" (
    venv\Scripts\python.exe embed_launcher.py --skip-login --embedded
) else (
    echo [ERROR] venv not found. Run setup.bat or install_offline.bat first.
    pause
    exit /b 1
)
