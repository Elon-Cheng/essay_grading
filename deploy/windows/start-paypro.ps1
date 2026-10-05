param([ValidateSet('database','redis','web')][string]$Service='web')
$ErrorActionPreference='Stop'
$payRoot='C:\paypro'
Set-Location -LiteralPath $payRoot
$settings=Get-Content -LiteralPath "$payRoot\settings.json" -Raw -Encoding UTF8 | ConvertFrom-Json
foreach($property in $settings.PSObject.Properties){[Environment]::SetEnvironmentVariable($property.Name,[string]$property.Value,'Process')}
switch($Service){
 'database' {$binary="$payRoot\mariadb\bin\mariadbd.exe";$arguments=@('--defaults-file=C:\paypro\database.ini')}
 'redis' {$binary="$payRoot\redis\redis-server.exe";$arguments=@('C:\paypro\redis.conf')}
 'web' {$binary="$payRoot\jre\bin\java.exe";$arguments=@('-Xms32m','-Xmx160m','-XX:MaxMetaspaceSize=96m','-XX:+UseSerialGC','-Xss256k','-jar','C:\paypro\paypro.jar','--spring.profiles.active=prod','--spring.config.additional-location=file:C:/paypro/config/')}
}
$process=Start-Process -FilePath $binary -ArgumentList $arguments -WorkingDirectory $payRoot -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput "$payRoot\logs\$Service-stdout.log" -RedirectStandardError "$payRoot\logs\$Service-stderr.log"
exit $process.ExitCode
