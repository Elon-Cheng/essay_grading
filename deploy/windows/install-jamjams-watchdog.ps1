param([string]$IpcUrl = 'ws://127.0.0.1:15734/ipc', [switch]$SystemStartup)
$ErrorActionPreference = 'Stop'
$siteRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$python = Join-Path $siteRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Project Python environment not found' }
if ($IpcUrl -notmatch '^ws://(?:127\.0\.0\.1|localhost):\d+/ipc$') { throw 'Use a loopback Jamjams IPC URL' }
& $python -c 'from websockets.sync.client import connect; import httpx'
if ($LASTEXITCODE -ne 0) { throw 'Install project requirements first' }
# Use the same interactive account as Jamjams. No password is saved by this task.
$account = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$launcher = Join-Path $PSScriptRoot 'start-jamjams-watchdog.ps1'
$arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $launcher + '" -IpcUrl "' + $IpcUrl + '"'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments -WorkingDirectory $siteRoot
if ($SystemStartup) {
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
} else {
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $account
    $principal = New-ScheduledTaskPrincipal -UserId $account -LogonType Interactive -RunLevel Limited
}
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$task = New-ScheduledTask -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Waits for Jamjams, then checks and switches failed proxy nodes.'
$taskName = 'EssayGradingJamjamsWatchdog'
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $taskName
}
Register-ScheduledTask -TaskName $taskName -InputObject $task -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
Write-Output ('Installed EssayGradingJamjamsWatchdog. System startup: ' + [bool]$SystemStartup)
Write-Output 'Log: logs\jamjams-watchdog.log. Closing Jamjams pauses controls; starting it resumes controls.'
