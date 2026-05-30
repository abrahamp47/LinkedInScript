#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Registers LinkedInScript as a daily Windows Task Scheduler entry.

.DESCRIPTION
    Creates a scheduled task named "LinkedInScript" that runs daily at the time
    specified in config.yaml (default 08:00). The script auto-detects the Python
    virtual environment or accepts an explicit -PythonPath parameter.

    Safe to re-run: uses -Force for idempotent re-registration.

.PARAMETER PythonPath
    Optional. Full path to python.exe. If not provided, the script searches
    for .venv\Scripts\python.exe, venv\Scripts\python.exe, or system Python.

.EXAMPLE
    .\install-task.ps1
    .\install-task.ps1 -PythonPath "C:\Python314\python.exe"
#>

param(
    [string]$PythonPath = ""
)

$ErrorActionPreference = 'Stop'

# --- Preflight Checks ---

function Test-Prerequisites {
    <#
    .SYNOPSIS
        Validates execution environment before task registration.
    #>

    # 1. Execution policy check (HIGH review concern)
    $policy = Get-ExecutionPolicy -Scope CurrentUser
    if ($policy -eq 'Restricted') {
        Write-Warning @"
Execution policy is 'Restricted' for the current user.
While this script is running (so policy is permissive enough NOW),
future scripts may be blocked. To fix permanently, run:

    Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

"@
    }

    # 2. Python path validation (MEDIUM review concern)
    if ($PythonPath -ne "") {
        if (-not (Test-Path $PythonPath)) {
            Write-Error "Python path '$PythonPath' does not exist."
            exit 1
        }
        if ($PythonPath -notmatch '(python|python3)\.exe$') {
            Write-Error "Python path '$PythonPath' is invalid -- must end with python.exe or python3.exe."
            exit 1
        }
    }

    # 3. Config.yaml existence check
    $configPath = Join-Path $script:ProjectRoot "config.yaml"
    if (-not (Test-Path $configPath)) {
        Write-Warning "config.yaml not found at '$configPath'. Will use default schedule time (08:00)."
    }
}

# --- Resolve Project Root ---

$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path

# Run preflight checks
Test-Prerequisites

# --- Python Path Detection (D-04) ---

if ($PythonPath -eq "") {
    # Try common venv locations
    $VenvPaths = @(
        (Join-Path $ProjectRoot ".venv\Scripts\python.exe"),
        (Join-Path $ProjectRoot "venv\Scripts\python.exe")
    )

    foreach ($p in $VenvPaths) {
        if (Test-Path $p) {
            $PythonPath = $p
            break
        }
    }

    # Fall back to system Python
    if ($PythonPath -eq "") {
        $systemPython = Get-Command python -ErrorAction SilentlyContinue
        if ($systemPython) {
            $PythonPath = $systemPython.Source
        } else {
            Write-Error @"
Python not found. Searched:
  - $($VenvPaths[0])
  - $($VenvPaths[1])
  - System PATH

Specify the path explicitly:
  .\install-task.ps1 -PythonPath "C:\path\to\python.exe"
"@
            exit 1
        }
    }

    # Safety check: validate detected path ends with python.exe
    if ($PythonPath -notmatch '(python|python3)\.exe$') {
        Write-Error "Detected Python path '$PythonPath' does not end with python.exe. Aborting."
        exit 1
    }
}

# --- Read Schedule Time from config.yaml (D-03, Pitfall 6 mitigation) ---

$ConfigPath = Join-Path $ProjectRoot "config.yaml"
$ScheduleTime = "08:00"  # default fallback

if (Test-Path $ConfigPath) {
    $match = Select-String -Path $ConfigPath -Pattern '^\s*time:\s*"?(\d{2}:\d{2})"?' | Select-Object -First 1
    if ($match) {
        $ScheduleTime = $match.Matches.Groups[1].Value
    }
}

# Validate time format (T-05-07 security mitigation)
if ($ScheduleTime -notmatch '^([01]\d|2[0-3]):[0-5]\d$') {
    Write-Error "Invalid schedule time '$ScheduleTime'. Must be HH:MM in 24-hour format (e.g., 08:00, 14:30)."
    exit 1
}

# --- Register Scheduled Task (D-01, D-02) ---

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
        -Description "Daily LinkedIn tech intern job monitor" `
        -RunLevel Limited `
        -Force | Out-Null

} catch {
    Write-Error "Failed to register task: $_"
    exit 1
}

# --- Post-Registration Verification ---

try {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    Write-Host ""
    Write-Host "Task '$TaskName' registered successfully!" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Task Name:     $TaskName"
    Write-Host "  Schedule:      Daily at $ScheduleTime"
    Write-Host "  Python:        $PythonPath"
    Write-Host "  Working Dir:   $ProjectRoot"
    Write-Host "  Run Level:     $($task.Principal.RunLevel)"
    Write-Host ""
    Write-Host "To verify: Get-ScheduledTask -TaskName '$TaskName'"
    Write-Host "To remove: .\scripts\uninstall-task.ps1"
    Write-Host ""
} catch {
    Write-Warning "Task may have been registered but verification failed: $_"
}

exit 0
