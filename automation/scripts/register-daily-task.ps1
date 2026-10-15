#Requires -Version 5.1
<#
.SYNOPSIS
  Register a per-user scheduled task that runs automation\scripts\run-local.ps1 every day.

.DESCRIPTION
  User-level task (RunLevel Limited). No administrator prompt. The task runs only after
  the current user is logged on, because Playwright uses that user's browser session files.

.PARAMETER At
  Local time HH:mm. Default 08:00.

.PARAMETER TaskName
  Scheduled task name. Default JobsInsightDaily.

.PARAMETER Unregister
  Remove the task.
#>
param(
    [string]$At = "08:00",
    [string]$TaskName = "JobsInsightDaily",
    [switch]$Unregister
)

$ErrorActionPreference = "Stop"

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed scheduled task $TaskName"
    exit 0
}

if ($At -notmatch '^\d{1,2}:\d{2}$') {
    Write-Host "Time must look like 08:00. Got: $At"
    exit 1
}

$script = (Resolve-Path (Join-Path $PSScriptRoot "run-local.ps1")).Path
$argument = "-NoProfile -ExecutionPolicy Bypass -File `"$script`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argument
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)
$user = if ($env:USERDOMAIN) { "$env:USERDOMAIN\$env:USERNAME" } else { $env:USERNAME }
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Force | Out-Null
Write-Host "Registered user-level task $TaskName daily at $At (no admin). It runs when $user is logged on."
Write-Host "Command: powershell.exe $argument"
