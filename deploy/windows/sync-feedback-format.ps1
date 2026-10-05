param([Parameter(Mandatory=$true)][string]$PackageDirectory)
$ErrorActionPreference = 'Stop'
$siteRoot = 'C:\essay-grading'
$packageRoot = (Resolve-Path -LiteralPath $PackageDirectory).Path
$files = @('SKILL.md','references/word-span-annotations.md','references/web-annotations-prompt.md',
    'references/web-grading-prompt.md','references/comprehensive-evaluation.md',
    'references/output-format.md','references/teacher-style.md','review_annotations.py',
    'static/index.html','static/annotations.js','tests/test_api.py',
    'tests/test_review_annotations.py','tests/test_annotations.cjs','scripts/recover_saved_annotations.py')
$manifest = Get-Content -LiteralPath (Join-Path $packageRoot 'manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($file in $files) {
    if ((Get-FileHash -LiteralPath (Join-Path $packageRoot $file)).Hash -ne $manifest.PSObject.Properties[$file].Value) {
        throw "Package checksum mismatch: $file"
    }
    if ($file -ne 'scripts/recover_saved_annotations.py' -and -not (Test-Path -LiteralPath (Join-Path $siteRoot $file))) {
        throw "Existing file missing: $file"
    }
}
Set-Location -LiteralPath $siteRoot
$python = Join-Path $siteRoot '.venv\Scripts\python.exe'
function Assert-Idle {
    $statusText = & $python -X utf8 (Join-Path $packageRoot 'server_feedback_status.py')
    if ($LASTEXITCODE -ne 0) { throw 'Could not verify job status' }
    $status = $statusText | ConvertFrom-Json
    if ($status.active_jobs -ne 0) { throw 'Active grading jobs; deployment deferred' }
    Write-Output 'Active jobs: 0'
}
Assert-Idle
$backupRoot = Join-Path $siteRoot ('backups\feedback-format-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ'))
New-Item -ItemType Directory -Path $backupRoot | Out-Null
foreach ($file in $files) {
    $backupFile = Join-Path $backupRoot $file
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $backupFile) | Out-Null
    if (Test-Path -LiteralPath (Join-Path $siteRoot $file)) {
        Copy-Item -LiteralPath (Join-Path $siteRoot $file) -Destination $backupFile
    }
}
$mutated = $false
try {
    Stop-ScheduledTask -TaskName 'EssayGradingWebsite'
    Assert-Idle
    Stop-ScheduledTask -TaskName 'EssayGradingWorker'
    # Only terminate Python processes for this application's website or worker.
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object {
        $_.ExecutablePath -and $_.ExecutablePath.StartsWith($siteRoot + '\', [StringComparison]::OrdinalIgnoreCase) -and
        ($_.CommandLine -match '\buvicorn\b' -or $_.CommandLine -match '\bworker\.py\b')
    } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    $mutated = $true
    foreach ($file in $files) {
        Copy-Item -LiteralPath (Join-Path $packageRoot $file) -Destination (Join-Path $siteRoot $file) -Force
        if ((Get-FileHash -LiteralPath (Join-Path $siteRoot $file)).Hash -ne $manifest.PSObject.Properties[$file].Value) {
            throw "Installed checksum mismatch: $file"
        }
    }
    # Test against disposable SQLite data, without touching production configuration.
    $env:APP_ENV = 'test'
    $env:DATABASE_URL = 'sqlite://'
    $env:ESSAY_DATA_DIR = Join-Path $backupRoot 'test-data'
    New-Item -ItemType Directory -Force -Path $env:ESSAY_DATA_DIR | Out-Null
    foreach ($testFile in @('test_review_annotations.py','test_api.py')) {
        $stdoutLog = Join-Path $backupRoot ($testFile + '.stdout.log')
        $stderrLog = Join-Path $backupRoot ($testFile + '.stderr.log')
        $testProcess = Start-Process -FilePath $python -ArgumentList @('-X','utf8','-m','unittest','discover','-s','tests','-p',$testFile) -WorkingDirectory $siteRoot -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog
        Get-Content -LiteralPath $stdoutLog -Encoding UTF8 | Write-Output
        Get-Content -LiteralPath $stderrLog -Encoding UTF8 | Write-Output
        if ($testProcess.ExitCode -ne 0) { throw "Server tests failed: $testFile" }
    }
    Write-Output "Synced and checksum-verified $($files.Count) files. Backup: $backupRoot"
} catch {
    Write-Output ('Deployment failed: ' + $_.Exception.Message)
    if ($mutated) {
        foreach ($file in $files) {
            if (Test-Path -LiteralPath (Join-Path $backupRoot $file)) {
                Copy-Item -LiteralPath (Join-Path $backupRoot $file) -Destination (Join-Path $siteRoot $file) -Force
            }
        }
        Write-Output "Restored deployment backup: $backupRoot"
    }
    throw
} finally {
    Start-ScheduledTask -TaskName 'EssayGradingWebsite'
    Start-ScheduledTask -TaskName 'EssayGradingWorker'
}
$healthy = $false
for ($attempt = 0; $attempt -lt 15; $attempt++) {
    try {
        $health = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/healthz' -TimeoutSec 3
        if ($health.StatusCode -eq 200) { $healthy = $true; break }
    } catch { Start-Sleep -Seconds 1 }
}
if (-not $healthy) { throw 'Service health verification failed' }
Write-Output 'Health: 200'
foreach ($file in @('static/index.html','static/annotations.js')) {
    $url = if ($file -eq 'static/index.html') { 'http://127.0.0.1:8000/static/index.html' } else { 'http://127.0.0.1:8000/static/annotations.js' }
    $resource = Join-Path $backupRoot ('served-' + (Split-Path -Leaf $file))
    Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $resource -TimeoutSec 10
    if ((Get-FileHash -LiteralPath $resource).Hash -ne $manifest.PSObject.Properties[$file].Value) {
        throw "Served resource mismatch: $file"
    }
}
Write-Output 'Served frontend checksums verified.'
Get-ScheduledTask -TaskName 'EssayGradingWebsite','EssayGradingWorker' | Select-Object TaskName,State | ConvertTo-Json
