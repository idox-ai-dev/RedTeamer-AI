#Requires -Version 5.1
<#
.SYNOPSIS
  Installs mock-payment-mcp into openclaw for red-team testing.
  Run this separately -- mock-payment-mcp is a test tool, not part of the core deployment.

  To uninstall:  .\install-mock-payment.ps1 -Uninstall
#>
param(
    [switch]$Uninstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Root         = $PSScriptRoot
$RepoRoot     = Split-Path $Root -Parent
$IsWin        = ($PSVersionTable.PSEdition -eq 'Desktop') -or ($env:OS -eq 'Windows_NT')
$VenvBin      = if ($IsWin) { 'Scripts' } else { 'bin' }

$ServerSrc    = Join-Path $RepoRoot 'mock-payment-mcp'
$ServerPy     = Join-Path $ServerSrc 'server.py'
$TestDataSrc  = Join-Path $ServerSrc 'test-data'
$VenvPython   = Join-Path (Join-Path $Root 'venv') (Join-Path $VenvBin 'python')
$OpenclawHome = Join-Path $HOME '.openclaw'
$OpenclawJson = Join-Path $OpenclawHome 'openclaw.json'
$TestDataDst  = Join-Path $OpenclawHome 'test-data'

function Write-Step($msg) { Write-Host "[mock-payment] $msg" -ForegroundColor Cyan }

# -- Sanity checks ---------------------------------------------------------------
if (-not (Test-Path $ServerPy)) {
    Write-Error "server.py not found at: $ServerPy"
}
if (-not (Test-Path "$VenvPython*")) {
    Write-Error "Shared venv not found at: $VenvPython`n  Run .\install.ps1 first."
}
if (-not (Test-Path $OpenclawJson)) {
    Write-Error 'openclaw.json not found. Run openclaw at least once first.'
}

# -- Sanity check: test-data source exists ---------------------------------------
if (-not (Test-Path $TestDataSrc)) {
    Write-Error "test-data folder not found at: $TestDataSrc"
}

# -- Uninstall -------------------------------------------------------------------
if ($Uninstall) {
    Write-Step 'Removing mock-payment from openclaw.json...'
    $cfg = Get-Content $OpenclawJson -Raw | ConvertFrom-Json
    if ($cfg.PSObject.Properties['mcp'] -and
        $cfg.mcp.PSObject.Properties['servers'] -and
        $cfg.mcp.servers.PSObject.Properties['mock-payment']) {
        $cfg.mcp.servers.PSObject.Properties.Remove('mock-payment')
        $cfg | ConvertTo-Json -Depth 20 | Set-Content $OpenclawJson -Encoding UTF8
        Write-Host '  mock-payment removed from openclaw.json.' -ForegroundColor Green
    } else {
        Write-Host '  mock-payment was not registered -- nothing to remove.' -ForegroundColor Yellow
    }
    Write-Host ''
    Write-Host '[mock-payment] Uninstalled. Restart openclaw to apply.' -ForegroundColor Green
    Write-Host '  Note: test-data files in ~/.openclaw/test-data/ are NOT removed.' -ForegroundColor DarkGray
    exit 0
}

# -- 1. Install mcp package into shared venv -------------------------------------
Write-Step 'Installing mcp package into shared venv...'
$Pip = Join-Path (Join-Path $Root 'venv') (Join-Path $VenvBin 'pip')
& $Pip install --quiet mcp
Write-Host '  Done.'

# -- 2. Register mock-payment in openclaw.json -----------------------------------
Write-Step 'Registering mock-payment in openclaw.json...'
$cfg = Get-Content $OpenclawJson -Raw | ConvertFrom-Json

if (-not $cfg.PSObject.Properties['mcp']) {
    $cfg | Add-Member -MemberType NoteProperty -Name 'mcp' -Value ([PSCustomObject]@{})
}
if (-not $cfg.mcp.PSObject.Properties['servers']) {
    $cfg.mcp | Add-Member -MemberType NoteProperty -Name 'servers' -Value ([PSCustomObject]@{})
}

$serverEntry = [PSCustomObject]@{
    command = $VenvPython
    args    = @($ServerPy)
}

if ($cfg.mcp.servers.PSObject.Properties['mock-payment']) {
    $cfg.mcp.servers.'mock-payment' = $serverEntry
} else {
    $cfg.mcp.servers | Add-Member -MemberType NoteProperty -Name 'mock-payment' -Value $serverEntry
}

$cfg | ConvertTo-Json -Depth 20 | Set-Content $OpenclawJson -Encoding UTF8
Write-Host "  Registered: command=$VenvPython"
Write-Host "              args=$ServerPy"

# -- 3. Copy test-data files to ~/.openclaw/test-data ---------------------------
Write-Step 'Installing test-data files to ~/.openclaw/test-data/...'
New-Item -ItemType Directory -Force -Path $TestDataDst | Out-Null
foreach ($f in Get-ChildItem $TestDataSrc -File) {
    Copy-Item $f.FullName (Join-Path $TestDataDst $f.Name) -Force
    Write-Host "  Copied: $($f.Name) -> $TestDataDst"
}

Write-Host ''
Write-Host '[mock-payment] Done. Restart openclaw to load the mock-payment MCP server.' -ForegroundColor Green
Write-Host "  Test data installed at: $TestDataDst" -ForegroundColor DarkGray
Write-Host '  To uninstall: .\install-mock-payment.ps1 -Uninstall' -ForegroundColor DarkGray
