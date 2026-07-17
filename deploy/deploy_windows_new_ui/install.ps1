#Requires -Version 5.1
<#
.SYNOPSIS
  Installs api-server, attack-agent, and observer-plugin (into local openclaw).
  Works on Windows (PowerShell 5.1+) and Mac/Linux (pwsh / PowerShell Core).

  Python detection order:
    1. System Python (python / python3 in PATH)
    2. Embedded Python in python-embed\python-*-embed-*.zip  [Windows only]
       Download from https://www.python.org/downloads/windows/
       → "Windows embeddable package (64-bit)"
#>
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root     = $PSScriptRoot
$RepoRoot = (Resolve-Path (Join-Path $Root "..\..")).Path
$IsWin    = ($PSVersionTable.PSEdition -eq 'Desktop') -or ($env:OS -eq 'Windows_NT')

# Cross-platform venv bin path
$VenvBin = if ($IsWin) { "Scripts" } else { "bin" }

# Source paths
$ApiServerSrc   = Join-Path (Join-Path $RepoRoot "cloud-redteam") "api-server"
$AttackAgentSrc = Join-Path (Join-Path $RepoRoot "cloud-redteam") "attack-agent"
$ObserverSrc    = Join-Path $RepoRoot "observer-plugin"

# openclaw paths
$OpenclawHome  = Join-Path $HOME ".openclaw"
$ExtensionsDst = Join-Path (Join-Path $OpenclawHome "extensions") "redteam-observer"
$OpenclawJson  = Join-Path $OpenclawHome "openclaw.json"

function Write-Step($msg) { Write-Host "[install] $msg" -ForegroundColor Cyan }

# -- Embedded Python bootstrap (Windows only) ----------------------------------
function Initialize-EmbeddedPython {
    $EmbedDir   = Join-Path $Root "python-embed"
    $ExtractDir = Join-Path $EmbedDir "python"
    $ExePath    = Join-Path $ExtractDir "python.exe"

    # Already extracted
    if (Test-Path $ExePath) { return $ExePath }

    # Find zip
    $Zip = Get-ChildItem $EmbedDir -Filter "python-*-embed-*.zip" -ErrorAction SilentlyContinue |
           Select-Object -First 1
    if (-not $Zip) {
        Write-Host "[install] ERROR: Python not found in PATH and no embeddable Python zip found." -ForegroundColor Red
        Write-Host "  Download 'Windows embeddable package (64-bit)' from:" -ForegroundColor Red
        Write-Host "  https://www.python.org/downloads/windows/" -ForegroundColor Red
        Write-Host "  Place the .zip into: $EmbedDir" -ForegroundColor Red
        exit 1
    }

    # Extract
    Write-Host "  Extracting $($Zip.Name)..." -ForegroundColor Yellow
    New-Item -ItemType Directory -Force -Path $ExtractDir | Out-Null
    Expand-Archive -Path $Zip.FullName -DestinationPath $ExtractDir -Force

    # Enable 'import site' (required for pip and venv to work)
    $PthFile = Get-ChildItem $ExtractDir -Filter "python*._pth" | Select-Object -First 1
    if ($PthFile) {
        (Get-Content $PthFile.FullName -Raw) -replace '#import site', 'import site' |
            Set-Content $PthFile.FullName -Encoding UTF8
        Write-Host "  Enabled import site in $($PthFile.Name)"
    }

    # Bootstrap pip - use bundled get-pip.py if present, else download
    $GetPip = Join-Path $EmbedDir "get-pip.py"
    if (-not (Test-Path $GetPip)) {
        Write-Host "  Downloading get-pip.py (requires internet)..." -ForegroundColor Yellow
        Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" `
                          -OutFile $GetPip -UseBasicParsing
    }
    Write-Host "  Installing pip into embedded Python..."
    & $ExePath $GetPip --quiet

    Write-Host "  Embedded Python ready." -ForegroundColor Green
    return $ExePath
}

# -- 1. Python -----------------------------------------------------------------
Write-Step "Checking Python..."
$Python = if (Get-Command python  -ErrorAction SilentlyContinue) { "python"  }
          elseif (Get-Command python3 -ErrorAction SilentlyContinue) { "python3" }
          else { $null }

if ($Python) {
    Write-Host "  System Python: $(& $Python --version)"
} elseif ($IsWin) {
    Write-Host "  System Python not found - trying embedded Python..." -ForegroundColor Yellow
    $Python = Initialize-EmbeddedPython
    Write-Host "  $(& $Python --version)"
} else {
    Write-Error "Python not found. Install Python 3.10+ and add to PATH."
}

# -- 2. shared venv ------------------------------------------------------------
Write-Step "Setting up shared venv..."
$Venv = Join-Path $Root "venv"
if (-not (Test-Path $Venv)) { & $Python -m venv $Venv }
$Pip = Join-Path (Join-Path $Venv $VenvBin) "pip"
& $Pip install --quiet -r (Join-Path $ApiServerSrc   "requirements.txt")
& $Pip install --quiet -r (Join-Path $AttackAgentSrc "requirements.txt")
Write-Host "  Done."

# -- 4. Install observer-plugin into openclaw extensions -----------------------
Write-Step "Installing observer-plugin into openclaw..."
if (-not (Test-Path $OpenclawHome)) {
    Write-Error "~\.openclaw not found. Is openclaw installed and has been run at least once?"
}

New-Item -ItemType Directory -Force -Path (Join-Path $ExtensionsDst "dist") | Out-Null
foreach ($f in @("package.json", "openclaw.plugin.json")) {
    Copy-Item (Join-Path $ObserverSrc $f) (Join-Path $ExtensionsDst $f) -Force
}
Copy-Item (Join-Path (Join-Path $ObserverSrc "dist") "index.js") `
          (Join-Path (Join-Path $ExtensionsDst "dist") "index.js") -Force

Write-Host "  Copied to $ExtensionsDst"

# -- 5. Patch openclaw.json to enable the plugin -------------------------------
Write-Step "Patching openclaw.json..."
if (-not (Test-Path $OpenclawJson)) {
    Write-Warning "openclaw.json not found. Run openclaw once to generate it, then re-run this script."
} else {
    $cfg = Get-Content $OpenclawJson -Raw | ConvertFrom-Json

    if (-not $cfg.PSObject.Properties['plugins']) {
        $cfg | Add-Member -MemberType NoteProperty -Name 'plugins' -Value ([PSCustomObject]@{})
    }
    # Only add to allow-list if it already exists; if absent, OpenClaw permits all entries implicitly
    if ($cfg.plugins.PSObject.Properties['allow'] -and $cfg.plugins.allow -notcontains 'redteam-observer') {
        $cfg.plugins.allow += 'redteam-observer'
    }
    if (-not $cfg.plugins.PSObject.Properties['entries']) {
        $cfg.plugins | Add-Member -MemberType NoteProperty -Name 'entries' -Value ([PSCustomObject]@{})
    }
    $entry = [PSCustomObject]@{
        enabled = $true
        hooks   = [PSCustomObject]@{ allowConversationAccess = $true }
    }
    if ($cfg.plugins.entries.PSObject.Properties['redteam-observer']) {
        $cfg.plugins.entries.'redteam-observer' = $entry
    } else {
        $cfg.plugins.entries | Add-Member -MemberType NoteProperty -Name 'redteam-observer' -Value $entry
    }

    $cfg | ConvertTo-Json -Depth 20 | Set-Content $OpenclawJson -Encoding UTF8
    Write-Host "  openclaw.json patched - redteam-observer enabled."
}

# -- 6. Create .env if missing -------------------------------------------------
$envFile    = Join-Path $Root ".env"
$envExample = Join-Path $Root ".env.example"
if (-not (Test-Path $envFile)) {
    Copy-Item $envExample $envFile
    Write-Host "[install] .env created from .env.example - edit it before starting." -ForegroundColor Yellow
}

# -- 7. Check OPENCLAW_BIN is configured --------------------------------------
$envFile = Join-Path $Root ".env"
if (Test-Path $envFile) {
    $oclawBinLine = Get-Content $envFile | Where-Object { $_ -match '^\s*OPENCLAW_BIN\s*=' }
    if (-not $oclawBinLine) {
        Write-Host ""
        Write-Host "[install] WARNING: OPENCLAW_BIN is not set in .env" -ForegroundColor Yellow
        Write-Host "  On Windows, openclaw is usually a .cmd wrapper that requires a full path." -ForegroundColor Yellow
        Write-Host "  Add the following line to your .env file:" -ForegroundColor Yellow
        Write-Host "    OPENCLAW_BIN=C:\Users\$env:USERNAME\AppData\Roaming\npm\openclaw.cmd" -ForegroundColor Cyan
        Write-Host "  (Replace the path if openclaw is installed elsewhere.)" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "[install] Done. Run .\start.ps1 to start the services." -ForegroundColor Green
