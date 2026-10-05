$ErrorActionPreference='Stop'
$domain='pay.english-essay-grading.online'
$answers=Resolve-DnsName -Name $domain -Type A -ErrorAction Stop
if(-not ($answers | Where-Object {$_.IPAddress -eq '123.57.106.87'})){throw 'PayPro DNS does not point to this server'}
$siteRoot='C:\essay-grading'
foreach($line in Get-Content -LiteralPath "$siteRoot\.env" -Encoding UTF8){
 if($line.Trim() -and -not $line.Trim().StartsWith('#')){$pair=$line.Split('=',2);if($pair.Count -eq 2){[Environment]::SetEnvironmentVariable($pair[0].Trim(),$pair[1],'Process')}}
}
$path="$siteRoot\deploy\windows\Caddyfile"
$original=Get-Content -LiteralPath $path -Raw -Encoding UTF8
if(-not $original.Contains($domain+' {')){
 $backup="$siteRoot\backups\Caddyfile-before-paypro-"+[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
 Copy-Item -LiteralPath $path -Destination $backup
 $candidate=$path+'.paypro-pending'
 ($original+"`n$domain {`n    encode zstd gzip`n    reverse_proxy 127.0.0.1:8889`n}`n")|Set-Content -LiteralPath $candidate -Encoding UTF8
 & "$siteRoot\bin\caddy.exe" validate --config $candidate --adapter caddyfile
 if($LASTEXITCODE -ne 0){throw 'Caddy configuration validation failed'}
 Copy-Item -LiteralPath $candidate -Destination $path -Force
 & "$siteRoot\bin\caddy.exe" reload --config $path --adapter caddyfile
 if($LASTEXITCODE -ne 0){Copy-Item -LiteralPath $backup -Destination $path -Force;throw 'PayPro proxy reload failed; prior file restored'}
}
Write-Output 'PayPro HTTPS proxy configured. Verify certificate issuance before enabling checkout.'
