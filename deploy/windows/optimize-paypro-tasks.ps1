$ErrorActionPreference='Stop'
$payRoot='C:\paypro'
$values=Get-Content -LiteralPath "$payRoot\settings.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$lines=foreach($property in $values.PSObject.Properties){
 $value=[string]$property.Value
 $escaped=-join ($value.ToCharArray() | ForEach-Object {if([int]$_ -gt 127){'\u{0:x4}' -f [int]$_}elseif($_ -eq '\'){'\\'}else{[string]$_}})
 $property.Name+'='+$escaped
}
[System.IO.File]::WriteAllLines("$payRoot\config\secret-values.properties",[string[]]$lines,[System.Text.Encoding]::ASCII)
$definitions=@{
 database=@("$payRoot\mariadb\bin\mariadbd.exe",'--defaults-file=C:\paypro\database.ini');
 redis=@("$payRoot\redis\redis-server.exe",'C:\paypro\redis.conf');
 web=@("$payRoot\jre\bin\java.exe",'-Xms32m -Xmx160m -XX:MaxMetaspaceSize=96m -XX:+UseSerialGC -Xss256k -jar C:\paypro\paypro.jar --spring.profiles.active=prod --spring.config.additional-location=file:C:/paypro/config/,file:C:/paypro/config/secret-values.properties --logging.file.name=C:/paypro/logs/paypro.log --logging.file.max-size=2MB --logging.file.max-history=3 --logging.file.total-size-cap=10MB --mybatis-plus.configuration.log-impl=org.apache.ibatis.logging.nologging.NoLoggingImpl')
}
foreach($service in @('web','redis','database')){& schtasks.exe /End /TN ('PayPro-'+$service) 2>$null | Out-Null}
# Stop only runtimes owned by the protected PayPro installation directory.
Get-Process java,mariadbd,redis-server -ErrorAction SilentlyContinue | Where-Object {$_.Path -and $_.Path.StartsWith($payRoot+'\',[StringComparison]::OrdinalIgnoreCase)} | Stop-Process -Force -ErrorAction SilentlyContinue
foreach($service in @('database','redis','web')){
 $definition=$definitions[$service]
 $delay=if($service -eq 'web'){'PT15S'}else{'PT5S'}
 $xml=@"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
<Triggers><BootTrigger><Enabled>true</Enabled><Delay>$delay</Delay></BootTrigger></Triggers>
<Principals><Principal id="Author"><UserId>S-1-5-18</UserId><RunLevel>HighestAvailable</RunLevel></Principal></Principals>
<Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><ExecutionTimeLimit>PT0S</ExecutionTimeLimit><RestartOnFailure><Interval>PT1M</Interval><Count>999</Count></RestartOnFailure></Settings>
<Actions Context="Author"><Exec><Command>$($definition[0])</Command><Arguments>$($definition[1])</Arguments><WorkingDirectory>$payRoot</WorkingDirectory></Exec></Actions>
</Task>
"@
 $xmlPath="$payRoot\$service-task.xml"
 [System.IO.File]::WriteAllText($xmlPath,$xml,[System.Text.Encoding]::Unicode)
 & schtasks.exe /Create /TN ('PayPro-'+$service) /XML $xmlPath /F | Out-Null
 if($LASTEXITCODE -ne 0){throw 'PayPro task registration failed'}
 & schtasks.exe /Run /TN ('PayPro-'+$service) | Out-Null
 if($LASTEXITCODE -ne 0){throw 'PayPro task startup failed'}
}
Write-Output 'PayPro tasks now launch native executables directly, without resident PowerShell wrappers.'
