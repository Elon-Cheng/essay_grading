$ErrorActionPreference = 'Stop'
$siteRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Set-Location -LiteralPath $siteRoot
foreach ($line in Get-Content -LiteralPath (Join-Path $siteRoot '.env')) {
    if ($line.Trim() -and -not $line.Trim().StartsWith('#')) {
        $pair = $line.Split('=', 2)
        if ($pair.Count -ne 2) { throw 'Invalid environment setting' }
        [Environment]::SetEnvironmentVariable($pair[0].Trim(), $pair[1], 'Process')
    }
}
$process = Start-Process -FilePath "$siteRoot\bin\caddy.exe" -ArgumentList 'run', '--config', "$siteRoot\deploy\windows\Caddyfile", '--adapter', 'caddyfile' -WorkingDirectory $siteRoot -WindowStyle Hidden -RedirectStandardOutput "$siteRoot\logs\caddy-stdout.log" -RedirectStandardError "$siteRoot\logs\caddy-stderr.log" -Wait -PassThru
exit $process.ExitCode
