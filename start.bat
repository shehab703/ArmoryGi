@echo off
REM Launches ArmoryGIS Pro without a visible CMD window (uses pythonw via launch.vbs)
cd /d "%~dp0"
if not exist "venv\Scripts\pythonw.exe" (
    echo [ERROR] Virtual environment not found.
    echo Run setup.bat or install_offline.bat first.
    pause
    exit /b 1
)
wscript.exe //nologo "%~dp0launch.vbs"
exit /b 0
