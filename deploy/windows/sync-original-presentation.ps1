param([Parameter(Mandatory=$true)][string]$PackageDirectory)
$ErrorActionPreference = 'Stop'
$siteRoot = 'C:\essay-grading'
$packageRoot = (Resolve-Path -LiteralPath $PackageDirectory).Path
$files = @('static/annotations.js','tests/test_annotations.cjs')
$manifest = Get-Content -LiteralPath (Join-Path $packageRoot 'manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($file in $files) {
    if ((Get-FileHash -LiteralPath (Join-Path $packageRoot $file)).Hash -ne $manifest.PSObject.Properties[$file].Value) {
        throw "Package checksum mismatch: $file"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $siteRoot $file))) { throw "Target missing: $file" }
}
$backupRoot = Join-Path $siteRoot ('backups\original-presentation-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ'))
foreach ($file in $files) {
    $backupFile = Join-Path $backupRoot $file
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $backupFile) | Out-Null
    Copy-Item -LiteralPath (Join-Path $siteRoot $file) -Destination $backupFile
}
try {
    foreach ($file in $files) {
        Copy-Item -LiteralPath (Join-Path $packageRoot $file) -Destination (Join-Path $siteRoot $file) -Force
        if ((Get-FileHash -LiteralPath (Join-Path $siteRoot $file)).Hash -ne $manifest.PSObject.Properties[$file].Value) {
            throw "Installed checksum mismatch: $file"
        }
    }
    $served = Join-Path $backupRoot 'served-annotations.js'
    Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/static/annotations.js' -OutFile $served -TimeoutSec 10
    if ((Get-FileHash -LiteralPath $served).Hash -ne $manifest.'static/annotations.js') { throw 'Served script mismatch' }
    $health = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/healthz' -TimeoutSec 10
    if ($health.StatusCode -ne 200) { throw 'Health check failed' }
} catch {
    foreach ($file in $files) {
        Copy-Item -LiteralPath (Join-Path $backupRoot $file) -Destination (Join-Path $siteRoot $file) -Force
    }
    throw
}
Write-Output "Synced 2 files; served script checksum verified. Backup: $backupRoot"
Write-Output 'Health: 200. No service restart needed.'
