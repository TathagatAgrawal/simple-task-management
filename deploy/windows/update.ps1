# Update the task board to the latest version, keeping all of the firm's data. Run in an
# Administrator PowerShell:
#
#   powershell -ExecutionPolicy Bypass -File deploy\windows\update.ps1
#
# Options:
#   -CheckOnly   Only say whether a newer version exists and what is new. Changes nothing.
#   -ZipPath X   For a folder that was not installed with git: use this ZIP of the new version
#                (GitHub: Code, Download ZIP). The app's data, backups, logs and settings are kept.
#   -Force       Throw away local edits to the app's own files if they stop the update.
#
# What it does: counts your data, takes a backup, gets the new code, installs its dependencies,
# starts the app (database changes are applied automatically on start, all or nothing), checks
# that the page loads, and counts your data again. If the new version will not start, it puts
# the previous version back. No Node or other tools are needed on this PC.

param(
    [string]$ZipPath = "",
    [switch]$CheckOnly,
    [switch]$Force
)

. (Join-Path $PSScriptRoot "common.ps1")
Assert-Admin
Set-Location $AppDir

$HasGit = Test-Path (Join-Path $AppDir ".git")
$uv = Get-UvPath
if (-not $uv) { throw "uv was not found. Run install.ps1 first." }

# One line of Python (single quotes only, so it survives being passed on the command line).
$SummaryCode = @'
import sqlite3; from simple_task_management.config import load_settings; c = sqlite3.connect(load_settings().db_path); n = lambda t: c.execute('select count(*) from ' + t).fetchone()[0]; print('tasks=%d updates=%d people=%d schema=%d' % (n('tasks'), n('updates'), n('users'), c.execute('pragma user_version').fetchone()[0]))
'@

function Get-DataSummary {
    # Returns @{ tasks; updates; people; schema } read straight from the database, or $null.
    try {
        $text = (& $uv run --no-dev python -c $SummaryCode 2>$null | Out-String).Trim()
    } catch {
        return $null
    }
    if ($LASTEXITCODE -ne 0) { return $null }
    if ($text -match 'tasks=(\d+) updates=(\d+) people=(\d+) schema=(\d+)') {
        return @{ tasks = [int]$Matches[1]; updates = [int]$Matches[2]; people = [int]$Matches[3]; schema = [int]$Matches[4] }
    }
    return $null
}

function Write-DataSummary([string]$Label, $Summary) {
    if ($Summary) {
        Write-Host ("{0}: {1} tasks, {2} updates, {3} people (database version {4})" -f $Label, $Summary.tasks, $Summary.updates, $Summary.people, $Summary.schema)
    } else {
        Write-Host "${Label}: could not read the database (this is normal on a brand-new install)."
    }
}

function Restore-PreviousVersion {
    Write-Host "The new version did not start. Putting the previous version back..." -ForegroundColor Yellow
    Stop-App
    if ($HasGit -and $script:before) {
        git reset --hard $script:before | Out-Null
    } elseif ($script:codeBackup -and (Test-Path $script:codeBackup)) {
        robocopy $script:codeBackup $AppDir /E /NFL /NDL /NJH /NJS /NP | Out-Null
        $global:LASTEXITCODE = 0
    }
    & $uv sync --no-dev
    Start-App
    if (Test-AppHealthy) {
        Write-Host "The previous version is running again. Your data was not changed." -ForegroundColor Green
    } else {
        Write-Host "The previous version did not start either. Your data is safe in $AppDir\data." -ForegroundColor Red
    }
    if ($script:backupPath) { Write-Host "The backup taken before this update: $script:backupPath" }
    Write-Host "Please send the last lines of $AppDir\logs\app.log to whoever looks after the app."
}

# ---------------------------------------------------------------- 1. find the new version
$before = $null
$backupPath = ""
$codeBackup = ""
$zipRoot = $null

if ($HasGit) {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "Git is not installed on this PC, so the update cannot download the new version." }
    $before = (git rev-parse HEAD | Out-String).Trim()
    git fetch origin
    if ($LASTEXITCODE -ne 0) { throw "Could not reach GitHub (is the internet working?). Nothing was changed." }
    $latest = (git rev-parse origin/main | Out-String).Trim()
    $behind = [int](git rev-list --count "HEAD..origin/main" | Out-String).Trim()

    if ($before -eq $latest) {
        Write-Host "This PC already has the latest version." -ForegroundColor Green
        exit 0
    }
    Write-Host "A newer version is available ($behind change(s)):" -ForegroundColor Cyan
    git log --oneline "HEAD..origin/main"
    if ($CheckOnly) { exit 0 }

    $dirty = (git status --porcelain --untracked-files=no | Out-String).Trim()
    if ($dirty -and -not $Force) {
        Write-Host "These files in the app folder were edited on this PC:" -ForegroundColor Yellow
        Write-Host $dirty
        throw "Nothing was changed. If those edits are not needed, run the update again with -Force."
    }
    git merge-base --is-ancestor HEAD origin/main
    $canFastForward = ($LASTEXITCODE -eq 0)
    if (-not $canFastForward -and -not $Force) {
        throw "This PC's copy of the app has history that the latest version does not (it was installed from a different copy). Nothing was changed. Run the update again with -Force to replace the app's files with the latest version; your data and settings are kept."
    }
} else {
    if ($CheckOnly) { throw "-CheckOnly needs a folder installed with git." }
    if (-not $ZipPath) {
        Write-Host "This folder was not installed with git, so give the update a ZIP of the new version:" -ForegroundColor Yellow
        Write-Host "  1. On GitHub, open the repository, click Code, then Download ZIP."
        Write-Host "  2. Run:  powershell -ExecutionPolicy Bypass -File deploy\windows\update.ps1 -ZipPath C:\path\to\the-zip-file.zip"
        exit 1
    }
    if (-not (Test-Path $ZipPath)) { throw "Could not find the ZIP file: $ZipPath" }
    $temp = Join-Path $env:TEMP ("taskboard-update-" + [guid]::NewGuid().ToString("N"))
    Expand-Archive -Path $ZipPath -DestinationPath $temp
    # A GitHub ZIP holds one folder (the repository); use whatever single folder is inside.
    $zipRoot = Get-ChildItem $temp -Directory | Select-Object -First 1
    if (-not $zipRoot -or -not (Test-Path (Join-Path $zipRoot.FullName "pyproject.toml"))) {
        throw "That ZIP does not look like the task board. Nothing was changed."
    }
}

# ---------------------------------------------------------------- 2. protect the data
Write-Host ""
$summaryBefore = Get-DataSummary
Write-DataSummary "Before" $summaryBefore

Write-Host "Taking a backup before updating..."
$out = (& $uv run --no-dev simple-task-management backup --label pre-update | Out-String)
if ($LASTEXITCODE -ne 0) { throw "The backup failed, so the update was cancelled. Nothing was changed." }
if ($out -match 'Backup written to (.+)') { $backupPath = $Matches[1].Trim() }
Write-Host "Backup saved: $backupPath"

# ---------------------------------------------------------------- 3. install the new version
Stop-App

if ($HasGit) {
    if ($canFastForward) {
        git merge --ff-only origin/main
    } else {
        git reset --hard origin/main
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Getting the new version failed; restarting the current version." -ForegroundColor Red
        Start-App
        exit 1
    }
} else {
    # Keep a copy of the current code so it can be put back, then copy the new files over it.
    # Data, backups, logs, the Python environment and the .env settings are never touched.
    $codeBackup = Join-Path $AppDir ("backups\code-before-update-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
    New-Item -ItemType Directory -Force -Path $codeBackup | Out-Null
    foreach ($name in @("src", "deploy", "pyproject.toml", "uv.lock")) {
        $item = Join-Path $AppDir $name
        if (Test-Path $item) { Copy-Item $item (Join-Path $codeBackup $name) -Recurse -Force }
    }
    robocopy $zipRoot.FullName $AppDir /E /XD data backups logs .venv .git node_modules /XF .env /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "Copying the new files failed (robocopy exit code $LASTEXITCODE)." }
    $global:LASTEXITCODE = 0
    Remove-Item $temp -Recurse -Force -ErrorAction SilentlyContinue
}

& $uv sync --no-dev
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing the new version's dependencies failed." -ForegroundColor Red
    Restore-PreviousVersion
    exit 1
}

# ---------------------------------------------------------------- 4. start it and check it
Start-App
if (-not (Test-AppHealthy)) {
    Restore-PreviousVersion
    exit 1
}

$pageOk = $false
try {
    $page = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/" -UseBasicParsing -TimeoutSec 10
    $bundle = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/static/dist/app.js" -UseBasicParsing -TimeoutSec 10
    $pageOk = ($page.StatusCode -eq 200) -and ($bundle.StatusCode -eq 200)
} catch {
    $pageOk = $false
}
if (-not $pageOk) {
    Write-Host "The app is running but its page did not load correctly." -ForegroundColor Red
    Restore-PreviousVersion
    exit 1
}

# ---------------------------------------------------------------- 5. prove the data is all there
Write-Host ""
$summaryAfter = Get-DataSummary
Write-DataSummary "After " $summaryAfter

if ($summaryBefore -and $summaryAfter) {
    $same = ($summaryBefore.tasks -eq $summaryAfter.tasks) -and ($summaryBefore.updates -eq $summaryAfter.updates) -and ($summaryBefore.people -eq $summaryAfter.people)
    if ($same) {
        if ($summaryAfter.schema -ne $summaryBefore.schema) {
            Write-Host ("The database was upgraded from version {0} to {1}." -f $summaryBefore.schema, $summaryAfter.schema)
        }
        Write-Host "All of your data is still there." -ForegroundColor Green
    } else {
        Write-Host "WARNING: the counts above are different. Do not use the app. Restore the backup: $backupPath" -ForegroundColor Red
        exit 1
    }
}

Write-Host ""
Write-Host "Updated. Tell everyone to refresh the page once (Ctrl+F5), and to close and reopen the app if they added it to their phone's home screen." -ForegroundColor Green
if ($HasGit) {
    Write-Host "If anything looks wrong, run:  git reset --hard $before   then restart.ps1   (your data keeps working with the older version)."
}
