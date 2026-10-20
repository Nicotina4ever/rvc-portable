param(
    [string]$Message = "",
    [switch]$DryRun
)

# Pubblica in un'unica operazione: add -> commit -> push.
# Uso: tools\publish.ps1 [-Message "testo commit"] [-DryRun]
# Dal repo: PUBBLICA.bat  oppure  PUBBLICA.bat -Message "testo"

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

function Fail([string]$msg) {
    Write-Host ""
    Write-Host "ERRORE: $msg" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path (Join-Path $repo '.git'))) {
    Fail "Questa cartella non e' un repository Git: $repo"
}

$branch = (& git rev-parse --abbrev-ref HEAD 2>$null).Trim()
if ($LASTEXITCODE -ne 0) { Fail "Impossibile leggere il branch Git." }
if ($branch -ne 'main') {
    Fail "Sei sul branch '$branch', atteso 'main'. Passa a main con: git switch main"
}

# Identita' locale: se manca, usa quella del progetto (una volta sola).
$email = (& git config user.email 2>$null)
if (-not $email) {
    & git config user.name "Nicotina4ever"
    & git config user.email "Nicotina4ever@users.noreply.github.com"
    Write-Host "Identita' Git locale impostata su Nicotina4ever." -ForegroundColor Yellow
}

# Credential Manager: evita che ogni push chieda di nuovo il login.
$helper = (& git config --global credential.helper 2>$null)
if (-not $helper) {
    & git config --global credential.helper manager
    Write-Host "Credential Manager configurato: al primo push autorizza GitHub una volta." -ForegroundColor Yellow
}

$changes = (& git status --porcelain)
if ($changes) {
    if ([string]::IsNullOrWhiteSpace($Message)) {
        $Message = "Aggiornamento " + (Get-Date -Format "yyyy-MM-dd HH:mm")
    }

    Write-Host ""
    Write-Host "Modifiche da pubblicare:" -ForegroundColor Cyan
    $changes | ForEach-Object { Write-Host "  $_" }
    Write-Host ""
    Write-Host "Commit: $Message" -ForegroundColor Cyan

    if (-not $DryRun) {
        & git add -A
        if ($LASTEXITCODE -ne 0) { Fail "git add non riuscito." }
        & git commit -m "$Message"
        if ($LASTEXITCODE -ne 0) { Fail "git commit non riuscito." }
    }
} else {
    Write-Host "Nessuna modifica da committare (il push aggiorna comunque il remoto)." -ForegroundColor DarkGray
}

if ($DryRun) {
    Write-Host ""
    Write-Host "DRY RUN: nessuna modifica, nessun commit, nessun push." -ForegroundColor Yellow
    exit 0
}

Write-Host ""
Write-Host "Push su origin main..." -ForegroundColor Cyan

# Prova a usare il token gia' salvato dal Credential Manager: cosi' non compaiono
# richieste di permesso a ogni push. Se il token non c'e', usa il push normale
# (GitHub chiedera' il login una volta).
$pushTarget = $null
$remote = (& git remote get-url origin 2>$null)
if ($remote -and $remote -match '^https://github\.com/') {
    try {
        $cred = "protocol=https`nhost=github.com`n`n" | & git credential fill 2>$null
        $token = (($cred -split "`n") | Where-Object { $_ -like 'password=*' }) -replace '^password=',''
        if ($token) {
            $pushTarget = $remote -replace '^https://github\.com/', "https://x-access-token:$token@github.com/"
        }
    } catch {
        $pushTarget = $null
    }
}

if ($pushTarget) {
    & git -c credential.helper= -c http.version=HTTP/1.1 push --porcelain $pushTarget main
} else {
    & git push origin main
}
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Push non riuscito." -ForegroundColor Red
    Write-Host "Se GitHub chiede di accedere, autorizza nel browser e rilancia PUBBLICA.bat." -ForegroundColor Yellow
    Write-Host "Se il messaggio parla di permessi negati, controlla di essere collaboratore del repo." -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "Fatto: modifiche pubblicate su GitHub." -ForegroundColor Green
