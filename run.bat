@echo off
setlocal
cd /d "%~dp0"

rem Prefer the Python launcher (3.12) if it already has the project dependencies.
set "PY="
py -3.12 -c "import PySide6" >nul 2>nul && set "PY=py -3.12"
if not defined PY (
    python -c "import PySide6" >nul 2>nul && set "PY=python"
)

if not defined PY (
    echo.
    echo [Pause recognition] No Python interpreter with PySide6 found.
    echo Install the dependencies first:
    echo     python -m pip install -r requirements.txt
    echo.
    echo Then run this file again, or use the interpreter that has them:
    echo     python run.py
    echo.
    pause
    exit /b 1
)

%PY% run.py
if errorlevel 1 pause
endlocal
