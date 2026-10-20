@echo off
setlocal
rem RVC Portable - avvio con console e log a video (debug).
set "ROOT=%~dp0"
set "PY=%ROOT%runtime\python.exe"
if not exist "%PY%" set "PY=%ROOT%.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo.
    echo Runtime non installato.
    echo Esegui prima setup.bat, poi riprova con run-console.bat.
    echo.
    pause
    exit /b 1
)

"%PY%" "%ROOT%launch.py" --console %*
echo.
echo Applicazione terminata. Premi un tasto per chiudere.
pause >nul
endlocal
