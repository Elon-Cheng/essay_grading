param([string]$IpcUrl = 'ws://127.0.0.1:15734/ipc')
$ErrorActionPreference = 'Stop'
$siteRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Set-Location -LiteralPath $siteRoot
& "$siteRoot\.venv\Scripts\python.exe" "$siteRoot\scripts\jamjams_watchdog.py" --ipc-url $IpcUrl
exit $LASTEXITCODE
