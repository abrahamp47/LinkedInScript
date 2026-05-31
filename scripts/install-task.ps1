<#
.SYNOPSIS
    One-command setup: installs dependencies, configures the tool, and registers
    a daily Windows Task Scheduler entry for LinkedInScript.

.DESCRIPTION
    Handles everything needed to go from fresh clone to daily automated runs:
    1. Detects Python virtual environment
    2. Installs pip dependencies + Playwright Chromium
    3. Generates config.yaml if missing
    4. Reads schedule time from config.yaml
    5. Self-elevates to admin if needed
    6. Registers the scheduled task (idempotent with -Force)

.PARAMETER PythonPath
    Optional. Full path to python.exe. Auto-detected if not provided.

.PARAMETER Time
    Optional. Override schedule time (HH:MM format). Defaults to config.yaml value or 08:00.

.EXAMPLE
    .\install-task.ps1
    .\install-task.ps1 -Time "07:30"
    .\install-task.ps1 -PythonPath "C:\Python314\python.exe"
#>

param(
    [string]$PythonPath = "",
    [string]$Time = ""
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path

# --- Self-Elevation ---

function Invoke-SelfElevate {
    $isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) {
        Write-Host "Requesting administrator privileges..." -ForegroundColor Yellow
        $arguments = "-ExecutionPolicy Bypass -File `"$PSCommandPath`""
        if ($PythonPath) { $arguments += " -PythonPath `"$PythonPath`"" }
        if ($Time) { $arguments += " -Time `"$Time`"" }
        Start-Process PowerShell -Verb RunAs -ArgumentList $arguments -Wait
        exit $LASTEXITCODE
    }
}

# --- Python Detection ---

function Find-Python {
    if ($PythonPath -ne "" -and (Test-Path $PythonPath)) {
        return $PythonPath
    }

    $candidates = @(
        (Join-Path $ProjectRoot ".venv\Scripts\python.exe"),
        (Join-Path $ProjectRoot "venv\Scripts\python.exe")
    )

    foreach ($p in $candidates) {
        if (Test-Path $p) { return $p }
    }

    $systemPython = Get-Command python -ErrorAction SilentlyContinue
    if ($systemPython) { return $systemPython.Source }

    Write-Error @"
Python not found. Searched:
  - $($candidates[0])
  - $($candidates[1])
  - System PATH

Fix: create a venv first:
  python -m venv .venv
  .\.venv\Scripts\Activate.ps1

Or specify explicitly:
  .\install-task.ps1 -PythonPath "C:\path\to\python.exe"
"@
    exit 1
}

# --- Main ---

Write-Host ""
Write-Host "LinkedInScript Setup" -ForegroundColor Cyan
Write-Host "====================" -ForegroundColor Cyan
Write-Host ""

# Step 1: Find Python
$PythonPath = Find-Python
Write-Host "[1/5] Python: $PythonPath" -ForegroundColor Green

# Step 2: Install dependencies
Write-Host "[2/5] Installing dependencies..."
& $PythonPath -m pip install -r (Join-Path $ProjectRoot "requirements.txt") --quiet 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Warning "  pip install had issues — run manually if needed: pip install -r requirements.txt"
} else {
    Write-Host "  pip packages installed." -ForegroundColor Green
}

& $PythonPath -m playwright install chromium 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Warning "  Playwright install had issues — run manually: python -m playwright install chromium"
} else {
    Write-Host "  Playwright Chromium installed." -ForegroundColor Green
}

# Step 3: Generate config if missing
$ConfigPath = Join-Path $ProjectRoot "config.yaml"
$ExamplePath = Join-Path $ProjectRoot "config.example.yaml"

if (-not (Test-Path $ConfigPath)) {
    if (Test-Path $ExamplePath) {
        Copy-Item $ExamplePath $ConfigPath
        Write-Host "[3/5] config.yaml created from template." -ForegroundColor Green
        Write-Host "  Edit config.yaml to customize keywords, companies, email settings." -ForegroundColor Yellow
    } else {
        Write-Warning "[3/5] No config.example.yaml found — config.yaml must be created manually."
    }
} else {
    Write-Host "[3/5] config.yaml already exists." -ForegroundColor Green
}

# Step 4: Determine schedule time
$ScheduleTime = "08:00"

if ($Time -ne "") {
    $ScheduleTime = $Time
} elseif (Test-Path $ConfigPath) {
    $match = Select-String -Path $ConfigPath -Pattern '^\s*time:\s*"?(\d{2}:\d{2})"?' | Select-Object -First 1
    if ($match) {
        $ScheduleTime = $match.Matches.Groups[1].Value
    }
}

if ($ScheduleTime -notmatch '^([01]\d|2[0-3]):[0-5]\d$') {
    Write-Error "Invalid time '$ScheduleTime'. Use HH:MM format (e.g., 08:00, 14:30)."
    exit 1
}

Write-Host "[4/5] Schedule: daily at $ScheduleTime" -ForegroundColor Green

# Step 5: Register scheduled task (needs admin)
Invoke-SelfElevate

$TaskName = "LinkedInScript"

try {
    $Action = New-ScheduledTaskAction `
        -Execute $PythonPath `
        -Argument "`"$(Join-Path $ProjectRoot 'main.py')`"" `
        -WorkingDirectory $ProjectRoot

    $Trigger = New-ScheduledTaskTrigger -Daily -At $ScheduleTime

    $Settings = New-ScheduledTaskSettingsSet `
        -StartWhenAvailable `
        -DontStopOnIdleEnd `
        -RunOnlyIfNetworkAvailable `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
        -MultipleInstances IgnoreNew

    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $Action `
        -Trigger $Trigger `
        -Settings $Settings `
        -Description "Daily LinkedIn tech intern job monitor — scrapes, filters, emails digest" `
        -RunLevel Limited `
        -Force | Out-Null

    Write-Host "[5/5] Task registered!" -ForegroundColor Green

} catch {
    Write-Error "Failed to register task: $_"
    exit 1
}

# --- Summary ---

Write-Host ""
Write-Host "Setup complete!" -ForegroundColor Green
Write-Host ""
Write-Host "  Task:       $TaskName"
Write-Host "  Schedule:   Daily at $ScheduleTime"
Write-Host "  Python:     $PythonPath"
Write-Host "  Project:    $ProjectRoot"
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  1. Create .env with EMAIL_PASSWORD (see README)"
Write-Host "  2. Run: python main.py --test-email"
Write-Host "  3. Run: python main.py (logs in to LinkedIn on first run)"
Write-Host "  4. Done — runs automatically every day at $ScheduleTime"
Write-Host ""
Write-Host "Commands:" -ForegroundColor Cyan
Write-Host "  python main.py --status      Check last run and next scheduled time"
Write-Host "  python main.py --dry-run     Preview without sending email"
Write-Host "  .\scripts\uninstall-task.ps1  Remove the scheduled task"
Write-Host ""

exit 0
