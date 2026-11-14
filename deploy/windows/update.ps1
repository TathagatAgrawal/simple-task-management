# Update the task board to the latest version. Run in an Administrator PowerShell:
#   powershell -ExecutionPolicy Bypass -File deploy\windows\update.ps1
#
# Takes a backup first, pulls the new code, reinstalls dependencies and restarts. Database
# migrations run automatically when the app starts.

. (Join-Path $PSScriptRoot "common.ps1")
Assert-Admin
Set-Location $AppDir

$uv = Get-UvPath
if (-not $uv) { throw "uv was not found. Run install.ps1 first." }

Write-Host "Taking a backup before updating..."
& $uv run --no-dev simple-task-management backup --label pre-update
if ($LASTEXITCODE -ne 0) { throw "Backup failed, so the update was cancelled." }

Stop-App

if (Test-Path ".git") {
    git pull --ff-only
    if ($LASTEXITCODE -ne 0) { Write-Host "git pull failed; restarting the current version." -ForegroundColor Red; Start-App; exit 1 }
} else {
    Write-Host "This folder is not a git checkout. Copy the new files over it, then press Enter." -ForegroundColor Yellow
    Read-Host | Out-Null
}

& $uv sync --no-dev
if ($LASTEXITCODE -ne 0) { Write-Host "Installing dependencies failed." -ForegroundColor Red }

Start-App
