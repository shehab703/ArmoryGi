@echo off
setlocal EnableExtensions
cd /d "%~dp0\.."
title ArmoryGIS Pro - Embed Diagnose

call scripts\resolve_python.bat 2>nul
if errorlevel 1 (
    echo [WARN] System Python not found; checking venv only...
)

if exist "venv\Scripts\python.exe" (
    venv\Scripts\python.exe scripts\embed_diagnose.py
) else if defined PY (
    "%PY%" scripts\embed_diagnose.py
) else (
    python scripts\embed_diagnose.py
)
set ERR=%ERRORLEVEL%
echo.
if %ERR% neq 0 (
    echo [FAIL] Fix issues above, then run install_offline.bat on THIS PC.
) else (
    echo [OK] Embed preflight passed.
)
pause
exit /b %ERR%
