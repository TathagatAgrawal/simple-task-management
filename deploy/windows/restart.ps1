# Restart the task board (or just stop it with -Stop). Run in an Administrator PowerShell:
#   powershell -ExecutionPolicy Bypass -File deploy\windows\restart.ps1 [-Stop]

param([switch]$Stop)

. (Join-Path $PSScriptRoot "common.ps1")
Assert-Admin

Stop-App
if ($Stop) {
    Write-Host "The task board is stopped. Run this script again without -Stop to start it."
} else {
    Start-App
}
