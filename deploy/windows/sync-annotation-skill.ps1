param(
    [Parameter(Mandatory=$true)][string]$PackageDirectory
)
$ErrorActionPreference = 'Stop'
$siteRoot = 'C:\essay-grading'
$packageRoot = (Resolve-Path -LiteralPath $PackageDirectory).Path
$files = @('SKILL.md', 'references/word-span-annotations.md', 'references/web-annotations-prompt.md')
$manifest = Get-Content -LiteralPath (Join-Path $packageRoot 'manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not (Test-Path -LiteralPath (Join-Path $siteRoot 'app.py'))) {
    throw 'Expected application not found at C:\essay-grading'
}
foreach ($file in $files) {
    $expected = $manifest.PSObject.Properties[$file].Value
    if (-not $expected -or (Get-FileHash -LiteralPath (Join-Path $packageRoot $file) -Algorithm SHA256).Hash -ne $expected) {
        throw "Package checksum mismatch: $file"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $siteRoot $file))) {
        throw "Existing application file missing: $file"
    }
}
$backupRoot = Join-Path $siteRoot ('backups\annotation-skill-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ'))
New-Item -ItemType Directory -Path $backupRoot | Out-Null
foreach ($file in $files) {
    $backupFile = Join-Path $backupRoot $file
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $backupFile) | Out-Null
    Copy-Item -LiteralPath (Join-Path $siteRoot $file) -Destination $backupFile
}
try {
    foreach ($file in $files) {
        Copy-Item -LiteralPath (Join-Path $packageRoot $file) -Destination (Join-Path $siteRoot $file) -Force
        if ((Get-FileHash -LiteralPath (Join-Path $siteRoot $file) -Algorithm SHA256).Hash -ne $manifest.PSObject.Properties[$file].Value) {
            throw "Installed checksum mismatch: $file"
        }
    }
} catch {
    foreach ($file in $files) {
        Copy-Item -LiteralPath (Join-Path $backupRoot $file) -Destination (Join-Path $siteRoot $file) -Force
    }
    throw
}
Write-Output "Synced 3 files. Backup: $backupRoot"
Write-Output 'Prompts are read per request; new grading jobs use the updated rules.'
$health = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/healthz' -TimeoutSec 15
Write-Output "Health: $($health.StatusCode)"
