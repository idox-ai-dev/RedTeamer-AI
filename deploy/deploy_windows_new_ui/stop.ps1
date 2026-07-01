#Requires -Version 5.1
$Root     = $PSScriptRoot
$RepoRoot = (Resolve-Path (Join-Path $Root "..\..")).Path
$pidsFile = Join-Path $Root ".pids.json"

# Kill by PID if we have them
if (Test-Path $pidsFile) {
    $pids = Get-Content $pidsFile -Raw | ConvertFrom-Json
    foreach ($name in @('api_server', 'attack_agent')) {
        $id = $pids.$name
        if ($id) {
            try {
                Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
                Write-Host "[stop] Stopped $name (PID $id)"
            } catch {
                Write-Host "[stop] $name (PID $id) already stopped."
            }
        }
    }
    Remove-Item $pidsFile -Force
}

# Also kill any remaining Python processes running main.py (uvicorn workers/reloaders)
$apiServer   = Join-Path (Join-Path $RepoRoot "cloud-redteam") "api-server"
$attackAgent = Join-Path (Join-Path $RepoRoot "cloud-redteam") "attack-agent"

Get-WmiObject Win32_Process -Filter "Name='python.exe' OR Name='python3.exe'" | Where-Object {
    $_.CommandLine -like "*$apiServer*" -or $_.CommandLine -like "*$attackAgent*"
} | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    Write-Host "[stop] Killed stale Python process (PID $($_.ProcessId))"
}

Write-Host "[stop] Done."
