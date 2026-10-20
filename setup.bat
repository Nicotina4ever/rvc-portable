@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title RVC Portable - Installazione
rem ==========================================================================
rem  RVC Portable - installazione Windows (nessun Python richiesto prima).
rem  Scarica il runtime del motore una sola volta e verifica l'ambiente.
rem
rem  Uso:
rem    setup.bat               installa e verifica (pausa finale)
rem    setup.bat --no-pause    per script/CI
rem
rem  Variabili utente opzionali:
rem    RVC_RUNTIME_ZIP         usa un archivio locale invece del download
rem    RVC_RUNTIME_URL         URL alternativo dell'archivio
rem    RVC_RUNTIME_SHA256      hash alternativo
rem ==========================================================================
set "ROOT=%CD%"
set "PY=%ROOT%\runtime\python.exe"

if exist "%PY%" goto verify

echo.
echo ============================================================
echo  RVC Portable - primo avvio: preparo il runtime del motore
echo ============================================================
echo.

set "RUNTIME_URL="
set "RUNTIME_SHA256="
set "RUNTIME_SIZE_MB="
set "RUNTIME_PARTS=1"
if exist "%ROOT%\install.conf" (
    for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%ROOT%\install.conf") do (
        if not "%%A"=="" set "%%A=%%B"
    )
)
rem Mappa le chiavi di install.conf sui nomi usati dallo script.
if defined RUNTIME_WINDOWS_URL set "RUNTIME_URL=%RUNTIME_WINDOWS_URL%"
if defined RUNTIME_WINDOWS_SHA256 set "RUNTIME_SHA256=%RUNTIME_WINDOWS_SHA256%"
if defined RUNTIME_WINDOWS_SIZE_MB set "RUNTIME_SIZE_MB=%RUNTIME_WINDOWS_SIZE_MB%"
if defined RVC_RUNTIME_URL set "RUNTIME_URL=%RVC_RUNTIME_URL%"
if defined RVC_RUNTIME_SHA256 set "RUNTIME_SHA256=%RVC_RUNTIME_SHA256%"
if defined RVC_RUNTIME_PARTS set "RUNTIME_PARTS=%RVC_RUNTIME_PARTS%"
if defined RUNTIME_WINDOWS_PARTS set "RUNTIME_PARTS=%RUNTIME_WINDOWS_PARTS%"
if "%RUNTIME_PARTS%"=="" set "RUNTIME_PARTS=1"

set "ARCHIVE="
if not defined RVC_RUNTIME_ZIP goto choose_source
if exist "%RVC_RUNTIME_ZIP%" (
    set "ARCHIVE=%RVC_RUNTIME_ZIP%"
    echo Archivio locale: %ARCHIVE%
    goto extract_archive
)
echo ERRORE: RVC_RUNTIME_ZIP non esiste: %RVC_RUNTIME_ZIP%
goto fail

:choose_source
if "%RUNTIME_URL%"=="" goto no_config
echo URL runtime: %RUNTIME_URL%
if not "%RUNTIME_SIZE_MB%"=="0" if not "%RUNTIME_SIZE_MB%"=="" echo Dimensione attesa: ~%RUNTIME_SIZE_MB% MB
echo.
if not "%RUNTIME_PARTS%"=="1" goto download_parts

set "ARCHIVE=%TEMP%\rvc-runtime-%RANDOM%-%RANDOM%.zip"
if exist "%ARCHIVE%" del /f /q "%ARCHIVE%" >nul 2>&1
echo Download in corso (puo' richiedere diversi minuti)...
where curl.exe >nul 2>nul
if not errorlevel 1 (
    curl.exe -L --fail --retry 3 --progress-bar -o "%ARCHIVE%" "%RUNTIME_URL%"
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing -Uri '%RUNTIME_URL%' -OutFile '%ARCHIVE%'"
)
if errorlevel 1 (
    echo.
    echo ERRORE durante il download. Controlla la connessione e riprova.
    goto fail
)
if not exist "%ARCHIVE%" (
    echo ERRORE: download non riuscito.
    goto fail
)
goto extract_archive

:download_parts
echo Download di %RUNTIME_PARTS% parti (limite GitHub per asset)...
set "PARTDIR=%TEMP%\rvc-runtime-parts-%RANDOM%-%RANDOM%"
mkdir "%PARTDIR%" >nul 2>&1
set "ARCHIVE=%TEMP%\rvc-runtime-full-%RANDOM%-%RANDOM%.zip"
for /l %%i in (1,1,%RUNTIME_PARTS%) do (
    set "IDX=00%%i"
    set "IDX=!IDX:~-3!"
    set "PART=!PARTDIR!\part.!IDX!"
    echo   parte !IDX! di %RUNTIME_PARTS%
    where curl.exe >nul 2>nul
    if not errorlevel 1 (
        curl.exe -L --fail --retry 3 --progress-bar -o "!PART!" "%RUNTIME_URL%.!IDX!"
    ) else (
        powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing -Uri '%RUNTIME_URL%.!IDX!' -OutFile '!PART!'"
    )
    if errorlevel 1 (
        echo.
        echo ERRORE durante il download della parte !IDX!.
        rmdir /s /q "%PARTDIR%" >nul 2>&1
        goto fail
    )
)
echo Ricompongo le parti...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$out=[IO.File]::OpenWrite('%ARCHIVE%'); Get-ChildItem -LiteralPath '%PARTDIR%' -File | Sort-Object Name | ForEach-Object { $in=[IO.File]::OpenRead($_.FullName); $in.CopyTo($out); $in.Dispose() }; $out.Dispose()"
if errorlevel 1 (
    echo ERRORE durante la ricomposizione delle parti.
    rmdir /s /q "%PARTDIR%" >nul 2>&1
    goto fail
)
rmdir /s /q "%PARTDIR%" >nul 2>&1
goto extract_archive

:extract_archive
if "%RUNTIME_SHA256%"=="" (
    echo ATTENZIONE: hash SHA-256 non configurato, verifica saltata.
) else (
    echo Verifica integrita' SHA-256...
    set "ACTUAL_SHA="
    for /f "skip=1 delims=" %%H in ('certutil -hashfile "%ARCHIVE%" SHA256 2^>nul') do (
        if not defined ACTUAL_SHA set "ACTUAL_SHA=%%H"
    )
    if not defined ACTUAL_SHA (
        for /f "usebackq delims=" %%H in (`powershell -NoProfile -Command "(Get-FileHash -Algorithm SHA256 -LiteralPath '%ARCHIVE%').Hash" 2^>nul`) do set "ACTUAL_SHA=%%H"
    )
    set "ACTUAL_SHA=!ACTUAL_SHA: =!"
    if /i not "!ACTUAL_SHA!"=="%RUNTIME_SHA256%" (
        echo.
        echo ERRORE: hash SHA-256 non corrispondente.
        echo   atteso:   %RUNTIME_SHA256%
        echo   ottenuto: !ACTUAL_SHA!
        echo Se hai ricostruito il runtime, aggiorna install.conf con:
        echo   runtime\python.exe -B tools\build_runtime_asset.py --update-install-conf
        goto fail
    )
    echo Hash OK.
)

echo Estrazione del runtime in "%ROOT%" (qualche minuto)...
where tar.exe >nul 2>nul
if not errorlevel 1 (
    tar.exe -xf "%ARCHIVE%" -C "%ROOT%"
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '%ARCHIVE%' -DestinationPath '%ROOT%' -Force"
)
if errorlevel 1 (
    echo ERRORE durante l'estrazione dell'archivio.
    goto fail
)
if not exist "%PY%" (
    echo ERRORE: estrazione incompleta: manca runtime\python.exe
    goto fail
)
if not defined RVC_RUNTIME_ZIP del /f /q "%ARCHIVE%" >nul 2>&1

:verify
echo.
echo Verifica dell'ambiente...
"%PY%" -B "%ROOT%\tools\bootstrap.py" --check
if errorlevel 1 (
    echo.
    echo Runtime presente ma incompleto: vedi messaggio sopra.
    goto fail
)

"%PY%" -B -m app --doctor
if errorlevel 1 (
    echo.
    echo Diagnostica con problemi: vedi messaggio sopra.
    goto fail
)

echo.
echo ============================================================
echo  Installazione completata. Avvia l'app con: run.bat
echo ============================================================
echo.
if /i "%~1"=="--no-pause" exit /b 0
pause
exit /b 0

:no_config
echo ERRORE: install.conf mancante o RUNTIME_WINDOWS_URL vuoto.
echo Scarica l'archivio runtime dalla pagina Releases del progetto, oppure
echo imposta RVC_RUNTIME_ZIP con il percorso locale dello zip e riprova.
goto fail

:fail
echo.
echo Installazione non completata.
if /i "%~1"=="--no-pause" exit /b 1
pause
exit /b 1
