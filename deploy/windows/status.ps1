# Check that everything the task board needs is running. Safe to run any time:
#   powershell -ExecutionPolicy Bypass -File deploy\windows\status.ps1

. (Join-Path $PSScriptRoot "common.ps1")

$ok = $true

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    Write-Host "Scheduled task '$TaskName': $($task.State)"
} else {
    Write-Host "Scheduled task '$TaskName' is missing. Run install.ps1." -ForegroundColor Red
    $ok = $false
}

if (Test-AppHealthy) {
    Write-Host "App health check ($HealthUrl): OK" -ForegroundColor Green
} else {
    Write-Host "App health check ($HealthUrl): NOT RESPONDING. Try restart.ps1, then check logs\app.log" -ForegroundColor Red
    $ok = $false
}

$tailscale = Get-TailscalePath
if ($tailscale) {
    Write-Host "Tailscale serve:"
    & $tailscale serve status
} else {
    Write-Host "Tailscale is not installed." -ForegroundColor Red
    $ok = $false
}

$backupDir = Join-Path $AppDir "backups"
if (Test-Path (Join-Path $AppDir ".env")) {
    $line = Get-Content (Join-Path $AppDir ".env") | Where-Object { $_ -match "^\s*BACKUP_DIR\s*=" } | Select-Object -First 1
    if ($line) { $backupDir = ($line -split "=", 2)[1].Trim().Trim('"') }
}
$latest = Get-ChildItem -Path $backupDir -Filter "tasks-*.db" -ErrorAction SilentlyContinue |
    Sort-Object Name -Descending | Select-Object -First 1
if ($latest) {
    Write-Host "Latest backup: $($latest.FullName) ($($latest.LastWriteTime))"
} else {
    Write-Host "No backups found in $backupDir yet (the first one runs at 23:00)." -ForegroundColor Yellow
}

if ($ok) { Write-Host "All good." -ForegroundColor Green } else { exit 1 }
