param(
    [string]$SiteDomain = 'english-essay-grading.online',
    [string]$IpBaseUrl = 'http://123.57.106.87'
)
$ErrorActionPreference = 'Stop'
$siteRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Set-Location -LiteralPath $siteRoot
if ($SiteDomain -notmatch '^[a-zA-Z0-9][a-zA-Z0-9.-]+$') { throw 'Invalid domain' }
if ($IpBaseUrl -notmatch '^http://[0-9.]+$') { throw 'Invalid IP base URL' }
if (-not (Test-Path -LiteralPath "$siteRoot\bin\caddy.exe")) { throw 'Install the verified official Caddy binary in bin/caddy.exe first' }
$backupRoot = Join-Path $siteRoot ('backups\https-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Force -Path $backupRoot, "$siteRoot\caddy-data" | Out-Null
Copy-Item -LiteralPath "$siteRoot\.env" -Destination "$backupRoot\.env"
$existing = Get-Content -LiteralPath "$siteRoot\.env"
$settingsToReplace = @('PUBLIC_BASE_URL', 'SITE_DOMAIN', 'IP_BASE_URL', 'APP_HOST', 'APP_PORT')
$updated = @($existing | Where-Object { $_.Split('=', 2)[0].Trim() -notin $settingsToReplace })
$updated += @("PUBLIC_BASE_URL=https://$SiteDomain", "SITE_DOMAIN=$SiteDomain", "IP_BASE_URL=$IpBaseUrl", 'APP_HOST=127.0.0.1', 'APP_PORT=8000')
# Validate the proxy before changing the running application's ports.
$env:SITE_DOMAIN = $SiteDomain
$env:IP_BASE_URL = $IpBaseUrl
& "$siteRoot\bin\caddy.exe" validate --config "$siteRoot\deploy\windows\Caddyfile" --adapter caddyfile
if ($LASTEXITCODE -ne 0) { throw 'Caddy configuration validation failed' }
Disable-ScheduledTask -TaskName EssayGradingWebsite | Out-Null
Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -in "$siteRoot\.venv\Scripts\python.exe", 'C:\essay-grading-runtime\python.exe' -and $_.CommandLine -match 'uvicorn app:app' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Stop-ScheduledTask -TaskName EssayGradingWebsite
try {
    Copy-Item -LiteralPath "$siteRoot\data" -Destination "$backupRoot\data" -Recurse
    $updated | Set-Content -LiteralPath "$siteRoot\.env" -Encoding UTF8
} catch {
    Copy-Item -LiteralPath "$backupRoot\.env" -Destination "$siteRoot\.env" -Force
    throw
} finally {
    Enable-ScheduledTask -TaskName EssayGradingWebsite | Out-Null
    Start-ScheduledTask -TaskName EssayGradingWebsite
}
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -File $siteRoot\deploy\windows\start-caddy.ps1" -WorkingDirectory $siteRoot
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable
Register-ScheduledTask -TaskName 'EssayGradingHTTPS' -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
if (-not (Get-NetFirewallRule -Name 'EssayGradingHTTPS' -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -Name 'EssayGradingHTTPS' -DisplayName 'Essay Grading HTTPS' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 443 | Out-Null
}
Start-ScheduledTask -TaskName EssayGradingHTTPS
Write-Output "Domain configured: https://$SiteDomain ; backup: $backupRoot"
