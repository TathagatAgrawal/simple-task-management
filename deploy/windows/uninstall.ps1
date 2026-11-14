# Completely remove the task board from this Windows PC. Run in an *Administrator* PowerShell:
#   powershell -ExecutionPolicy Bypass -File deploy\windows\uninstall.ps1
#
# Removes the TaskBoard scheduled task, stops the app, offers to save a copy of the database to
# the Desktop, removes the Tailscale Serve address and deletes the app folder. It then offers,
# one question at a time, to delete the backups, remove uv and its Python, and let the PC sleep
# again.
#
# Unlike the other scripts this one is self-contained (it doesn't load common.ps1), so it still
# works on a half-deleted install: copy just this file anywhere and run it. If the app isn't in
# C:\TaskBoard, say where it is:
#   powershell -ExecutionPolicy Bypass -File uninstall.ps1 -AppDir "D:\Apps\TaskBoard"

param([string]$AppDir = "")

$ErrorActionPreference = "Stop"
$TaskName = "TaskBoard"
$Port = 8000

function Confirm-Step([string]$Question, [bool]$Default = $false) {
    $hint = if ($Default) { "(Y/n)" } else { "(y/N)" }
    $answer = Read-Host "$Question $hint"
    if ([string]::IsNullOrWhiteSpace($answer)) { return $Default }
    return $answer.Trim().ToLower().StartsWith("y")
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Please run this script as Administrator (right-click PowerShell -> Run as administrator)." -ForegroundColor Red
    exit 1
}

# Find the app folder: the checkout this script lives in, otherwise the standard location.
if (-not $AppDir) {
    $parent = Join-Path $PSScriptRoot "..\.."
    if (Test-Path (Join-Path $parent "pyproject.toml")) {
        $AppDir = (Resolve-Path $parent).Path
    } else {
        $AppDir = "C:\TaskBoard"
    }
}
$AppDir = $AppDir.TrimEnd("\")

Write-Host ""
Write-Host "This will remove the task board from this PC:" -ForegroundColor Cyan
Write-Host "  - remove the '$TaskName' scheduled task and stop the app"
Write-Host "  - remove its Tailscale address (tailscale serve on port 443)"
Write-Host "  - delete $AppDir, including the database with every task and update"
Write-Host "You'll be offered a copy of the database before anything is deleted."
Write-Host ""
if ((Read-Host "Type REMOVE to continue") -ne "REMOVE") {
    Write-Host "Cancelled. Nothing was changed."
    exit 0
}

# Note where backups go before the settings file is deleted.
$backupDir = Join-Path $AppDir "backups"
$envFile = Join-Path $AppDir ".env"
if (Test-Path $envFile) {
    $line = Get-Content $envFile | Where-Object { $_ -match "^\s*BACKUP_DIR\s*=" } | Select-Object -First 1
    if ($line) {
        $value = ($line -split "=", 2)[1].Trim().Trim('"').Trim("'")
        if ([System.IO.Path]::IsPathRooted($value)) { $backupDir = $value } else { $backupDir = Join-Path $AppDir $value }
    }
}

# 1. Remove the scheduled task first: it restarts the app within a minute if the app stops.
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed the '$TaskName' scheduled task."
} else {
    Write-Host "No '$TaskName' scheduled task found (already removed)."
}

# 2. Stop anything still running: programs started from the app folder, and the server on its port.
Start-Sleep -Seconds 2
Get-Process | Where-Object { $_.Path -and $_.Path.StartsWith($AppDir + "\", [StringComparison]::OrdinalIgnoreCase) } |
    Stop-Process -Force -ErrorAction SilentlyContinue
Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    Write-Host "Something is still running on port $Port. Restarting the PC will stop it." -ForegroundColor Yellow
} else {
    Write-Host "The app is stopped."
}

# 3. Offer a copy of the database (all tasks.db* files: recent changes may be in tasks.db-wal).
$dataDir = Join-Path $AppDir "data"
if (Get-ChildItem -Path $dataDir -Filter "tasks.db*" -ErrorAction SilentlyContinue) {
    if (Confirm-Step "Save a copy of the database to your Desktop first?" $true) {
        $stamp = Get-Date -Format "yyyy-MM-dd-HHmm"
        $copyDir = Join-Path ([Environment]::GetFolderPath("Desktop")) "TaskBoard-data-$stamp"
        New-Item -ItemType Directory -Path $copyDir -Force | Out-Null
        Copy-Item -Path (Join-Path $dataDir "tasks.db*") -Destination $copyDir
        Write-Host "Saved the database to $copyDir" -ForegroundColor Green
    }
}

# 4. Remove the address on the tailnet.
$tailscale = Get-Command tailscale -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1
if (-not $tailscale -and (Test-Path "C:\Program Files\Tailscale\tailscale.exe")) { $tailscale = "C:\Program Files\Tailscale\tailscale.exe" }
if ($tailscale) {
    & $tailscale serve --https=443 off
    if ($LASTEXITCODE -eq 0) { Write-Host "Removed the Tailscale Serve address." }
    else { Write-Host "Tailscale Serve had nothing to remove (or isn't set up)." }
}

# 5. Delete the app folder (retrying briefly in case a file is still being released).
if (Test-Path $AppDir) {
    Set-Location $env:USERPROFILE  # a folder can't be deleted while PowerShell is inside it
    for ($i = 0; $i -lt 3 -and (Test-Path $AppDir); $i++) {
        try { Remove-Item -Path $AppDir -Recurse -Force } catch { Start-Sleep -Seconds 3 }
    }
    if (Test-Path $AppDir) {
        Write-Host "Some files in $AppDir are still in use. Restart the PC, then delete that folder." -ForegroundColor Yellow
    } else {
        Write-Host "Deleted $AppDir."
    }
} else {
    Write-Host "$AppDir is already gone."
}

# 6. Optional clean-up, asking first for each.
$backups = Get-ChildItem -Path $backupDir -Filter "tasks-*.db" -ErrorAction SilentlyContinue
if ($backups) {
    if (Confirm-Step "Also delete the $($backups.Count) backup file(s) in $($backupDir)?") {
        $backups | Remove-Item -Force
        if (-not (Get-ChildItem -Path $backupDir -Force -ErrorAction SilentlyContinue)) { Remove-Item -Path $backupDir -Force }
        Write-Host "Deleted the backups."
    } else {
        Write-Host "Kept the backups in $backupDir."
    }
}

$uv = @((Join-Path $env:USERPROFILE ".local\bin\uv.exe"), (Join-Path $env:USERPROFILE ".cargo\bin\uv.exe")) |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if ($uv -and (Confirm-Step "Remove uv and the Python it installed? Only if nothing else on this PC uses uv.")) {
    & $uv cache clean
    foreach ($dir in @((& $uv python dir), (& $uv tool dir))) {
        if ($dir -and (Test-Path $dir)) { Remove-Item -Path $dir -Recurse -Force }
    }
    $binDir = Split-Path $uv
    foreach ($exe in "uv.exe", "uvx.exe", "uvw.exe") {
        $path = Join-Path $binDir $exe
        if (Test-Path $path) { Remove-Item -Path $path -Force }
    }
    Write-Host "Removed uv and its Python."
}

if (Confirm-Step "Let this PC go to sleep again after 30 minutes on mains power?") {
    powercfg /change standby-timeout-ac 30
    Write-Host "Sleep after 30 minutes restored."
}

Write-Host ""
Write-Host "Done. Things to do by hand if you want:" -ForegroundColor Cyan
Write-Host "  - Tailscale tray icon -> Preferences: turn off 'Run unattended' if this PC no longer needs it"
Write-Host "  - Tailscale admin console: re-enable key expiry for this PC, and rename it if you like"
Write-Host "  - Ask the staff to delete their Tasks bookmark (or the installed app window)"
