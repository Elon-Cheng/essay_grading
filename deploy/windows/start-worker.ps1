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
$process = Start-Process -FilePath "$siteRoot\.venv\Scripts\python.exe" -ArgumentList 'worker.py' -WorkingDirectory $siteRoot -WindowStyle Hidden -RedirectStandardOutput "$siteRoot\logs\worker-stdout.log" -RedirectStandardError "$siteRoot\logs\worker-stderr.log" -Wait -PassThru
exit $process.ExitCode
