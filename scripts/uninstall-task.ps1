<#
.SYNOPSIS
    Removes the LinkedInScript scheduled task from Windows Task Scheduler.

.DESCRIPTION
    Cleanly unregisters the "LinkedInScript" daily task. Safe to run even if
    the task is not currently registered.

.EXAMPLE
    .\uninstall-task.ps1
#>

$ErrorActionPreference = 'Stop'

$TaskName = "LinkedInScript"

try {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

    if ($null -eq $task) {
        Write-Host "Task '$TaskName' is not registered -- nothing to remove."
        exit 0
    }

    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false

    # Verify removal
    $check = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($null -ne $check) {
        Write-Warning "Task '$TaskName' may not have been fully removed. Check Task Scheduler manually."
    } else {
        Write-Host "Task '$TaskName' removed from Task Scheduler." -ForegroundColor Green
    }

} catch {
    Write-Error "Failed to unregister task: $_"
    exit 1
}

exit 0
