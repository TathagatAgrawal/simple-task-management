# Shared settings and helpers for the Windows scripts. Dot-sourced, not run directly.

$ErrorActionPreference = "Stop"
$AppDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$TaskName = "TaskBoard"
$UpdateTaskName = "TaskBoardUpdate"
$Port = 8000
$HealthUrl = "http://127.0.0.1:$Port/healthz"

function Get-UvPath {
    $candidates = @(
        (Join-Path $env:USERPROFILE ".local\bin\uv.exe"),
        (Join-Path $env:USERPROFILE ".cargo\bin\uv.exe")
    )
    foreach ($path in $candidates) { if (Test-Path $path) { return $path } }
    $cmd = Get-Command uv -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

function Get-TailscalePath {
    $cmd = Get-Command tailscale -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $default = "C:\Program Files\Tailscale\tailscale.exe"
    if (Test-Path $default) { return $default }
    return $null
}

function Test-AppHealthy {
    try {
        $response = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 3
        return $response.Content.Trim() -eq "ok"
    } catch {
        return $false
    }
}

function Wait-AppHealthy([int]$Seconds = 60) {
    for ($i = 0; $i -lt $Seconds; $i++) {
        if (Test-AppHealthy) { return $true }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Stop-App {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $TaskName
    }
    # Make sure no leftover server process is still holding the port.
    Start-Sleep -Seconds 2
    Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
}

function Start-App {
    Start-ScheduledTask -TaskName $TaskName
    if (Wait-AppHealthy) {
        Write-Host "The task board is running." -ForegroundColor Green
    } else {
        Write-Host "The app did not start within a minute. Check $AppDir\logs\app.log" -ForegroundColor Red
    }
}

function Assert-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-Host "Please run this script as Administrator (right-click PowerShell -> Run as administrator)." -ForegroundColor Red
        exit 1
    }
}
