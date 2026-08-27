@echo off
REM Sets PY to a working Python 3.10+ command. Call from project root.
REM Usage: call scripts\resolve_python.bat

set "PY="

if exist "%~dp0..\venv\Scripts\python.exe" (
    "%~dp0..\venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
    if not errorlevel 1 (
        set "PY=%~dp0..\venv\Scripts\python.exe"
        goto :found
    )
)

for %%V in (3.10 3.11 3.12 3.13) do (
    if not defined PY (
        py -%%V -c "import sys; sys.exit(0)" >nul 2>&1
        if not errorlevel 1 set "PY=py -%%V"
    )
)

if not defined PY (
    where py >nul 2>&1
    if not errorlevel 1 (
        py -3 -c "import sys; sys.exit(0)" >nul 2>&1
        if not errorlevel 1 set "PY=py -3"
    )
)

if not defined PY (
    where python >nul 2>&1
    if not errorlevel 1 set "PY=python"
)

if not defined PY (
    echo [ERROR] Python 3.10+ not found.
    echo Install from https://python.org or run: py -0p
    py -0p 2>nul
    exit /b 1
)

%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 3.10 or higher is required.
    %PY% --version 2>nul
    exit /b 1
)

:found
exit /b 0
