#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root     = $PSScriptRoot
$RepoRoot = (Resolve-Path (Join-Path $Root "..\..")).Path
$IsWin    = ($PSVersionTable.PSEdition -eq 'Desktop') -or ($env:OS -eq 'Windows_NT')
$VenvBin  = if ($IsWin) { "Scripts" } else { "bin" }

# ── Load .env (optional — falls back to each service's own .env if missing) ────
$envFile = Join-Path $Root ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | Where-Object { $_ -match '^\s*[^#=\s]' } | ForEach-Object {
        $parts = $_ -split '=', 2
        if ($parts.Count -eq 2) {
            $k = $parts[0].Trim()
            $v = $parts[1].Trim().Trim('"').Trim("'")
            [Environment]::SetEnvironmentVariable($k, $v, 'Process')
        }
    }
    Write-Host "[start] Loaded central .env" -ForegroundColor DarkGray
} else {
    Write-Host "[start] No central .env found - services will use their own .env files." -ForegroundColor Yellow
}

$apiPort   = if ($env:API_PORT)   { $env:API_PORT }   else { "8000" }
$agentPort = if ($env:AGENT_PORT) { $env:AGENT_PORT } else { "9000" }

$ApiServerSrc   = Join-Path (Join-Path $RepoRoot "cloud-redteam") "api-server"
$AttackAgentSrc = Join-Path (Join-Path $RepoRoot "cloud-redteam") "attack-agent"
$Python         = Join-Path (Join-Path $Root "venv") (Join-Path $VenvBin "python")

if (-not (Test-Path "$Python*")) { Write-Error "Not found: $Python - run .\install.ps1 first." }

$pidsFile = Join-Path $Root ".pids.json"

# ── Add openclaw to PATH so attack-agent subprocess can find it ───────────────
$oclawCmd = Get-Command openclaw -ErrorAction SilentlyContinue
if ($oclawCmd) {
    $oclawDir = Split-Path $oclawCmd.Source
    [Environment]::SetEnvironmentVariable("PATH", "$oclawDir;$env:PATH", "Process")
} else {
    Write-Warning "[start] openclaw not found in PATH - attacks will fail to run."
}

# ── Copy .env to service source dirs so python-dotenv picks it up ─────────────
Copy-Item $envFile (Join-Path $ApiServerSrc   ".env") -Force
Copy-Item $envFile (Join-Path $AttackAgentSrc ".env") -Force

# ── Start api-server ──────────────────────────────────────────────────────────
Write-Host "[start] Starting api-server  → http://localhost:$apiPort" -ForegroundColor Cyan
if ($IsWin) {
    $apiProc = Start-Process -FilePath $Python -ArgumentList "main.py" `
        -WorkingDirectory $ApiServerSrc -PassThru -WindowStyle Normal
} else {
    $apiProc = Start-Process -FilePath $Python -ArgumentList "main.py" `
        -WorkingDirectory $ApiServerSrc -PassThru
}

# ── Start attack-agent ────────────────────────────────────────────────────────
Write-Host "[start] Starting attack-agent → http://localhost:$agentPort" -ForegroundColor Cyan
if ($IsWin) {
    $agentProc = Start-Process -FilePath $Python -ArgumentList "main.py" `
        -WorkingDirectory $AttackAgentSrc -PassThru -WindowStyle Normal
} else {
    $agentProc = Start-Process -FilePath $Python -ArgumentList "main.py" `
        -WorkingDirectory $AttackAgentSrc -PassThru
}

# ── Save PIDs ─────────────────────────────────────────────────────────────────
[PSCustomObject]@{
    api_server   = $apiProc.Id
    attack_agent = $agentProc.Id
} | ConvertTo-Json | Set-Content $pidsFile -Encoding UTF8

Write-Host ""
Write-Host "[start] Services running." -ForegroundColor Green
Write-Host "  api-server   PID $($apiProc.Id)  http://localhost:$apiPort"
Write-Host "  attack-agent PID $($agentProc.Id)  http://localhost:$agentPort"
Write-Host "  Run .\stop.ps1 to stop."
