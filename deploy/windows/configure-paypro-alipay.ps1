param([string]$AppId,[switch]$EnableForVerification)
$ErrorActionPreference='Stop'
$payRoot='C:\paypro'
$settingsPath="$payRoot\settings.json"
$settings=Get-Content -LiteralPath $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
if($AppId){$settings.ALIPAY_APP_ID=$AppId}
function Read-Key([string]$Path){
 $text=Get-Content -LiteralPath $Path -Raw
 return (($text -replace '-----[^\r\n]+-----','') -replace '\s','')
}
if(Test-Path -LiteralPath "$payRoot\secrets\alipay-app-private-key.pem"){$settings.ALIPAY_APP_PRIVATE_KEY=Read-Key "$payRoot\secrets\alipay-app-private-key.pem"}
if(Test-Path -LiteralPath "$payRoot\secrets\alipay-public-key.pem"){$settings.ALIPAY_PUBLIC_KEY=Read-Key "$payRoot\secrets\alipay-public-key.pem"}
$settings|ConvertTo-Json|Set-Content -LiteralPath $settingsPath -Encoding UTF8
$lines=foreach($property in $settings.PSObject.Properties){
 $escaped=-join ([string]$property.Value).ToCharArray().ForEach({if([int]$_ -gt 127){'\u{0:x4}' -f [int]$_}elseif($_ -eq '\'){'\\'}else{[string]$_}})
 $property.Name+'='+$escaped
}
[System.IO.File]::WriteAllLines("$payRoot\config\secret-values.properties",[string[]]$lines,[System.Text.Encoding]::ASCII)
if($EnableForVerification){
 if(-not $settings.ALIPAY_APP_ID -or -not $settings.ALIPAY_APP_PRIVATE_KEY -or -not $settings.ALIPAY_PUBLIC_KEY){throw 'Alipay AppID and both keys are required'}
 $configPath="$payRoot\config\application-prod.yml"
 $text=Get-Content -LiteralPath $configPath -Raw -Encoding UTF8
 $text=[regex]::Replace($text,'(?s)(- id: alipay_dmf\s.*?status:) false','$1 true')
 $text|Set-Content -LiteralPath $configPath -Encoding UTF8
 Write-Output 'PayPro Alipay enabled for verification. SaaS checkout remains closed until actual settlement is verified.'
}
& schtasks.exe /End /TN 'PayPro-web' 2>$null | Out-Null
Get-Process java -ErrorAction SilentlyContinue | Where-Object {$_.Path -and $_.Path.StartsWith($payRoot+'\',[StringComparison]::OrdinalIgnoreCase)} | Stop-Process -Force -ErrorAction SilentlyContinue
& schtasks.exe /Run /TN 'PayPro-web' | Out-Null
Write-Output 'Configuration saved; private keys were not displayed.'
