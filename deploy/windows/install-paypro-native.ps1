param([Parameter(Mandatory=$true)][string]$Archive)
$ErrorActionPreference='Stop'
$payRoot='C:\paypro'
if(Test-Path -LiteralPath $payRoot){throw 'PayPro directory already exists; preserve its data and settings'}
New-Item -ItemType Directory -Path $payRoot | Out-Null
& icacls.exe $payRoot /inheritance:r /grant:r '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-18:(OI)(CI)F' | Out-Null
if($LASTEXITCODE -ne 0){throw 'Could not protect PayPro configuration directory'}
Expand-Archive -LiteralPath $Archive -DestinationPath $payRoot
foreach($directory in @('logs','db','redis-data','qr','secrets')){New-Item -ItemType Directory -Force -Path (Join-Path $payRoot $directory) | Out-Null}
$manifest=Get-Content -LiteralPath "$payRoot\manifest.json" -Raw | ConvertFrom-Json
foreach($file in $manifest.PSObject.Properties){
 if((Get-FileHash -LiteralPath (Join-Path $payRoot $file.Name)).Hash -ne $file.Value){throw 'Native package checksum mismatch'}
}
Set-Location -LiteralPath $payRoot
$initializer=Start-Process -FilePath "$payRoot\mariadb\bin\mariadb-install-db.exe" -ArgumentList @('--datadir=C:\paypro\db','--port=3307') -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput "$payRoot\logs\database-init.stdout.log" -RedirectStandardError "$payRoot\logs\database-init.stderr.log"
if($initializer.ExitCode -ne 0){throw 'Database initialization failed; see private PayPro logs'}
$principal=New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings=New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
foreach($service in @('database','redis','web')){
 $action=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File C:\paypro\start-paypro.ps1 -Service $service" -WorkingDirectory $payRoot
 $task=New-ScheduledTask -Action $action -Trigger (New-ScheduledTaskTrigger -AtStartup) -Principal $principal -Settings $settings
 Register-ScheduledTask -TaskName ('PayPro-'+$service) -InputObject $task | Out-Null
}
Start-ScheduledTask -TaskName 'PayPro-database'
Start-ScheduledTask -TaskName 'PayPro-redis'
$ready=$false
for($i=0;$i -lt 30;$i++){
 if(Get-NetTCPConnection -State Listen -LocalPort 3307 -ErrorAction SilentlyContinue){$ready=$true;break}
 Start-Sleep -Seconds 1
}
if(-not $ready){throw 'PayPro database did not start'}
$bootstrap=Start-Process -FilePath "$payRoot\mariadb\bin\mariadb.exe" -ArgumentList @('--host=127.0.0.1','--port=3307','--user=root','--default-character-set=utf8mb4') -WindowStyle Hidden -Wait -PassThru -RedirectStandardInput "$payRoot\bootstrap.sql" -RedirectStandardOutput "$payRoot\logs\bootstrap.stdout.log" -RedirectStandardError "$payRoot\logs\bootstrap.stderr.log"
if($bootstrap.ExitCode -ne 0){throw 'PayPro database bootstrap failed; see private logs'}
Start-ScheduledTask -TaskName 'PayPro-web'
$healthy=$false
for($i=0;$i -lt 45;$i++){
 try{$response=Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8889/admin/login.html' -TimeoutSec 3;if($response.StatusCode -eq 200){$healthy=$true;break}}catch{Start-Sleep -Seconds 1}
}
if(-not $healthy){throw 'PayPro startup check failed; see private web logs'}
Get-NetTCPConnection -State Listen | Where-Object {$_.LocalPort -in @(3307,6380,8889)} | Select-Object LocalAddress,LocalPort | ConvertTo-Json
if((Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/healthz' -TimeoutSec 5).StatusCode -ne 200){throw 'Essay service health check failed'}
Write-Output 'PayPro administrator page: HTTP 200. Essay service: HTTP 200.'
Get-ScheduledTask -TaskName 'PayPro-database','PayPro-redis','PayPro-web' | Select-Object TaskName,State | ConvertTo-Json
