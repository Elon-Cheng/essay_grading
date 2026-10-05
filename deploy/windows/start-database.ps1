$ErrorActionPreference = 'Stop'
$siteRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$pgRoot = 'C:\essay-grading-postgres\pgsql'
$pgData = 'C:\essay-grading-pgdata'
$control = "$pgRoot\bin\pg_ctl.exe"
& $control status -D $pgData *> $null
if ($LASTEXITCODE -ne 0) {
    & $control -D $pgData -l "$siteRoot\logs\postgres.log" -w start
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL startup failed' }
}
while ($true) {
    Start-Sleep -Seconds 30
    & $control status -D $pgData *> $null
    if ($LASTEXITCODE -ne 0) { exit 1 }
}
