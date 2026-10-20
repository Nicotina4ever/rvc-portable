@echo off
setlocal
title RVC Portable - pubblica su GitHub
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\publish.ps1" %*
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" (
    echo.
    echo Pubblicazione non completata. Leggi il messaggio sopra.
    pause
    exit /b %CODE%
)
if "%~1"=="" pause
exit /b 0
