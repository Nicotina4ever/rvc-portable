@echo off
setlocal
title RVC Portable - pubblica tutto
set "DROID=%RVC_DROID_DIR%"
if not defined DROID set "DROID=%~dp0..\Android\rvc-portable-android"
if not exist "%DROID%\tools\publish.ps1" (
    echo ERRORE: repo Android non trovato in "%DROID%".
    echo Imposta RVC_DROID_DIR con il percorso della cartella rvc-portable-android.
    pause
    exit /b 1
)
echo ==== PC: rvc-portable ====
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\publish.ps1" %*
if errorlevel 1 (
    echo.
    echo Pubblicazione PC fallita: mi fermo.
    pause
    exit /b 1
)
echo.
echo ==== Android: rvc-droid ====
powershell -NoProfile -ExecutionPolicy Bypass -File "%DROID%\tools\publish.ps1" %*
if errorlevel 1 (
    echo.
    echo Pubblicazione Android fallita: il PC e' gia' stato pubblicato.
    pause
    exit /b 1
)
echo.
echo Fatto: PC e Android pubblicati.
pause
exit /b 0
