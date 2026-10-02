param([string]$PublicBaseUrl = 'http://123.57.106.87')
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$siteRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$runtimeRoot = 'C:\essay-grading-runtime'
Set-Location -LiteralPath $siteRoot
New-Item -ItemType Directory -Force -Path "$siteRoot\data", "$siteRoot\logs" | Out-Null
if (-not (Test-Path -LiteralPath "$runtimeRoot\python.exe")) {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $installer = Join-Path $siteRoot 'python-installer.exe'
    if (-not (Test-Path -LiteralPath $installer)) {
        $installer = Join-Path $env:TEMP 'essay-python-3.13.7.exe'
        & curl.exe --fail --location --silent --show-error --max-time 180 --output $installer 'https://www.python.org/ftp/python/3.13.7/python-3.13.7-amd64.exe'
        if ($LASTEXITCODE -ne 0) { throw 'Python download failed' }
    }
    $signature = Get-AuthenticodeSignature -LiteralPath $installer
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Python Software Foundation') { throw 'Python installer signature verification failed' }
    $process = Start-Process -FilePath $installer -ArgumentList '/quiet', 'InstallAllUsers=1', "TargetDir=$runtimeRoot", 'PrependPath=0', 'Include_test=0', 'Include_launcher=0' -WindowStyle Hidden -Wait -PassThru
    if ($process.ExitCode -notin 0, 3010) { throw "Python installation failed: $($process.ExitCode)" }
}
if (-not (Test-Path -LiteralPath "$siteRoot\.venv\Scripts\python.exe")) {
    & "$runtimeRoot\python.exe" -m venv "$siteRoot\.venv"
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed' }
}
& "$siteRoot\.venv\Scripts\python.exe" -m pip install -r "$siteRoot\requirements.txt"
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
if (-not (Test-Path -LiteralPath "$siteRoot\.env")) {
    @("PUBLIC_BASE_URL=$PublicBaseUrl", 'OPENAI_API_KEY=', 'OPENAI_BASE_URL=https://www.su8.codes/v1', 'OPENAI_MODEL=gpt-5.5') | Set-Content -LiteralPath "$siteRoot\.env" -Encoding ASCII
}
& icacls.exe $siteRoot /inheritance:r /grant:r 'SYSTEM:(OI)(CI)F' 'Administrators:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Directory permission setup failed' }
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -File $siteRoot\deploy\windows\start.ps1" -WorkingDirectory $siteRoot
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable
Register-ScheduledTask -TaskName 'EssayGradingWebsite' -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
if (-not (Get-NetFirewallRule -Name 'EssayGradingHTTP' -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -Name 'EssayGradingHTTP' -DisplayName 'Essay Grading HTTP' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 80 | Out-Null
}
Start-ScheduledTask -TaskName 'EssayGradingWebsite'
Write-Output 'Website startup task registered and started.'
