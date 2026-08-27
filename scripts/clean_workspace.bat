@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
title ArmoryGIS Pro - Clean Workspace
color 0E

echo ========================================
echo   Clean regeneratable / unused files
echo   (Keeps source code + GALLARIES media)
echo ========================================
echo.

set /p confirm=Delete venv, tile cache, __pycache__, duplicate three_vendor? (Y/N): 
if /i not "%confirm%"=="Y" (
    echo Cancelled.
    pause
    exit /b 0
)

if exist "venv\" (
    echo [*] Removing venv\ ...
    rmdir /s /q "venv"
)

if exist "app_data\tile_cache\" (
    echo [*] Removing app_data\tile_cache\ ...
    rmdir /s /q "app_data\tile_cache"
)

if exist "resources\html\Js\three_vendor\" (
    echo [*] Removing duplicate three_vendor\ ...
    rmdir /s /q "resources\html\Js\three_vendor"
)

if exist "sim sess\" (
    echo [*] Removing sim sess\ ...
    rmdir /s /q "sim sess"
)

for /d /r %%D in (__pycache__) do @if exist "%%D" rmdir /s /q "%%D"

if exist "GALLARIES\3d model\3d model\telegram-bulk-account-creator-Emulator-main\" (
    echo [*] Removing stray telegram folder from GALLARIES\ ...
    rmdir /s /q "GALLARIES\3d model\3d model\telegram-bulk-account-creator-Emulator-main"
)

echo.
echo [OK] Cleanup complete.
echo Recreate venv: setup.bat  or  install_offline.bat
echo.
pause
