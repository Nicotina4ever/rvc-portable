@echo off
setlocal
rem RVC Portable - avvio senza finestra console (pythonw).
rem Per il debug usa run-console.bat.

set "ROOT=%~dp0"
set "PY=%ROOT%runtime\pythonw.exe"
if not exist "%PY%" set "PY=%ROOT%.venv\Scripts\pythonw.exe"
if not exist "%PY%" (
    echo.
    echo Runtime non installato.
    echo Esegui prima setup.bat, poi riprova con run.bat.
    echo.
    pause
    exit /b 1
)

start "" "%PY%" "%ROOT%launch.py" %*
endlocal
