# One-time setup of the task board on this Windows PC. Run in an *Administrator* PowerShell:
#   powershell -ExecutionPolicy Bypass -File deploy\windows\install.ps1
#
# It installs uv (which brings Python), installs the app's dependencies, optionally creates the
# first admin, registers a scheduled task that starts the app at boot and restarts it if it
# crashes, and publishes it on the tailnet with `tailscale serve`.

. (Join-Path $PSScriptRoot "common.ps1")
Assert-Admin
Set-Location $AppDir
Write-Host "== Setting up the task board in $AppDir ==" -ForegroundColor Cyan

# 1. uv (Python manager; also installs Python 3.13 for the app)
$uv = Get-UvPath
if (-not $uv) {
    Write-Host "Installing uv..."
    powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    $uv = Get-UvPath
}
if (-not $uv) { throw "uv could not be found after installing it. Open a new PowerShell window and run this script again." }
Write-Host "Using uv at $uv"

# 2. App dependencies
& $uv sync --no-dev
if ($LASTEXITCODE -ne 0) { throw "Installing dependencies failed (uv sync)." }

# 3. Settings file
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env. Edit BACKUP_DIR in it to point at a OneDrive / Google Drive folder." -ForegroundColor Yellow
}

# 4. First admin
if ((Read-Host "Create an admin account now? (y/n)") -eq "y") {
    & $uv run --no-dev simple-task-management create-admin
}

# 5. Scheduled task: start at boot (before anyone logs in), restart on crash, never time out
$action = New-ScheduledTaskAction -Execute $uv `
    -Argument "run --no-dev simple-task-management serve --host 127.0.0.1 --port $Port" `
    -WorkingDirectory $AppDir
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable
$credential = Get-Credential -UserName "$env:USERDOMAIN\$env:USERNAME" `
    -Message "Windows password for this account, so the app can start at boot before anyone signs in"
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -User $credential.UserName -Password $credential.GetNetworkCredential().Password -RunLevel Limited -Force | Out-Null
Write-Host "Registered scheduled task '$TaskName'."
Stop-App
Start-App

# 6. Publish on the tailnet with HTTPS
$tailscale = Get-TailscalePath
if ($tailscale) {
    & $tailscale serve --bg $Port
    & $tailscale serve status
} else {
    Write-Host "Tailscale was not found. Install it, then run: tailscale serve --bg $Port" -ForegroundColor Yellow
}

# 7. Keep the PC awake on mains power
if ((Read-Host "Set this PC to never sleep when plugged in? (y/n)") -eq "y") {
    powercfg /change standby-timeout-ac 0
    powercfg /change hibernate-timeout-ac 0
}

Write-Host ""
Write-Host "Done. Remaining manual steps:" -ForegroundColor Cyan
Write-Host "  - Tailscale tray icon -> Preferences -> 'Run unattended' (keeps it connected when nobody is logged in)"
Write-Host "  - Tailscale admin console -> Machines -> this PC -> 'Disable key expiry'"
Write-Host "  - Windows Update -> Active hours: set to office hours"
Write-Host "  - Edit .env so BACKUP_DIR points at a cloud-synced folder, then run deploy\windows\restart.ps1"
