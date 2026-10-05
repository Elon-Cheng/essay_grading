$ErrorActionPreference = 'Stop'
$siteRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Set-Location -LiteralPath $siteRoot
foreach ($line in Get-Content -LiteralPath (Join-Path $siteRoot '.env') -Encoding UTF8) {
    if ($line.Trim() -and -not $line.Trim().StartsWith('#')) {
        $pair = $line.Split('=', 2)
        if ($pair.Count -ne 2) { throw 'Invalid environment setting' }
        [Environment]::SetEnvironmentVariable($pair[0].Trim(), $pair[1], 'Process')
    }
}
$env:ESSAY_DATA_DIR = Join-Path $siteRoot 'data'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUNBUFFERED = '1'
$appHost = if ($env:APP_HOST) { $env:APP_HOST } else { '0.0.0.0' }
$appPort = if ($env:APP_PORT) { $env:APP_PORT } else { '80' }
$proxyArguments = if ($appHost -eq '127.0.0.1') { @('--proxy-headers', '--forwarded-allow-ips', '127.0.0.1') } else { @('--no-proxy-headers') }
$arguments = @('-m', 'uvicorn', 'app:app', '--host', $appHost, '--port', $appPort) + $proxyArguments
$process = Start-Process -FilePath "$siteRoot\.venv\Scripts\python.exe" -ArgumentList $arguments -WorkingDirectory $siteRoot -WindowStyle Hidden -RedirectStandardOutput "$siteRoot\logs\stdout.log" -RedirectStandardError "$siteRoot\logs\stderr.log" -Wait -PassThru
exit $process.ExitCode
