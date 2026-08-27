@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title ArmoryGIS Pro - Download Offline Packages
color 0B

echo ========================================
echo   Download wheels for offline install
echo   (Run once on a PC with internet)
echo ========================================
echo.

if not exist "offline_packages\" mkdir "offline_packages"
if not exist "scripts\" mkdir "scripts"

call scripts\resolve_python.bat
if errorlevel 1 (
    echo [ERROR] Could not find Python 3.10+
    pause
    exit /b 1
)

echo [*] Using: %PY%
%PY% --version
echo.

echo [*] Upgrading pip for download...
%PY% -m pip install --upgrade pip wheel setuptools --quiet
if errorlevel 1 (
    echo [WARN] pip upgrade failed; continuing...
)

echo [*] Downloading bootstrap tools...
%PY% -m pip download pip setuptools wheel packaging -d offline_packages
if errorlevel 1 (
    echo [WARN] Bootstrap download had issues; continuing...
)

echo.
echo [*] Downloading runtime wheels for Python 3.10, 3.11, and 3.12 (win_amd64)...
echo     (Offline PCs may use any of these Python versions.)
echo.

for %%V in (310 311 312) do (
    echo --- Python %%V ---
    %PY% -m pip download -r requirements-offline.txt -d offline_packages --python-version %%V --platform win_amd64 --only-binary=:all:
    if errorlevel 1 (
        echo [WARN] Binary-only download failed for %%V; retrying with source allowed...
        %PY% -m pip download -r requirements-offline.txt -d offline_packages --python-version %%V --platform win_amd64
        if errorlevel 1 (
            echo [ERROR] Download failed for Python %%V.
            pause
            exit /b 1
        )
    )
)

echo.
echo [*] Ensuring PyQt6 SIP / Qt6 wheels for all supported Python versions...
for %%V in (310 311 312) do (
    %PY% -m pip download PyQt6-sip==13.8.0 PyQt6-Qt6==6.7.3 PyQt6-WebEngine-Qt6==6.7.3 -d offline_packages --python-version %%V --platform win_amd64 --only-binary=:all:
    if errorlevel 1 (
        %PY% -m pip download PyQt6-sip==13.8.0 PyQt6-Qt6==6.7.3 PyQt6-WebEngine-Qt6==6.7.3 -d offline_packages --python-version %%V --platform win_amd64
    )
)

echo.
call verify_offline_packages.bat
if errorlevel 1 exit /b 1

echo.
echo [OK] Packages saved to offline_packages\
echo Copy the whole armorygis_pro folder to offline PCs, then run install_offline.bat
echo.
pause
