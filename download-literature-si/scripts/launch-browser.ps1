param(
    [Parameter(Mandatory=$true)][string]$Ledger,
    [ValidateSet('chrome','edge')][string]$Browser='chrome',
    [Parameter(Mandatory=$true)][string[]]$DownloadDir,
    [ValidateRange(1,8)][int]$Max=2,
    [string[]]$Ids,
    [string]$BrowserPath,
    [switch]$Retry,
    [switch]$Force,
    [switch]$DryRun
)
$ErrorActionPreference='Stop'
$ledgerFile=Get-Item -LiteralPath $Ledger
$data=Get-Content -LiteralPath $ledgerFile.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
if($data.version -ne 1){throw 'Unsupported ledger version'}
$logPath=Join-Path $ledgerFile.DirectoryName 'browser-launch-events.jsonl'
$history=@()
if(Test-Path -LiteralPath $logPath){
    foreach($line in (Get-Content -LiteralPath $logPath -Encoding UTF8)){
        if($line.Trim()){$history+=($line | ConvertFrom-Json)}
    }
}
if(-not $BrowserPath){
    $exe=if($Browser -eq 'chrome'){'Google\Chrome\Application\chrome.exe'}else{'Microsoft\Edge\Application\msedge.exe'}
    $roots=@($env:ProgramFiles,${env:ProgramFiles(x86)},$env:LOCALAPPDATA) | Where-Object {$_}
    foreach($root in $roots){
        $candidate=Join-Path $root $exe
        if(Test-Path -LiteralPath $candidate){$BrowserPath=$candidate;break}
    }
}
if(-not $BrowserPath -or -not (Test-Path -LiteralPath $BrowserPath)){throw 'Browser not found. Supply -BrowserPath to the installed official browser.'}
$chosen=@();$targets=@();$seen=@{}
foreach($job in $data.jobs){
    if($Ids -and $job.id -notin $Ids){continue}
    if($seen.ContainsKey($job.url)){continue}
    $uri=[uri]$job.url
    if($uri.Scheme -ne 'https' -or $uri.Host -notin $data.allowed_hosts -or $uri.UserInfo -or $job.url -match '[\s"<>]'){throw ('Unexpected URL for '+$job.id)}
    if($job.filename -match '[<>:"/\\|?*\x00-\x1f]' -or $job.filename -notmatch '\.(pdf|docx)$'){throw 'Unexpected attachment basename'}
    $name=[IO.Path]::GetFileNameWithoutExtension($job.filename)
    $ext=[IO.Path]::GetExtension($job.filename)
    $pattern='^'+[regex]::Escape($name)+'(?: \(\d+\))?'+[regex]::Escape($ext)+'$'
    $existing=@()
    foreach($folder in $DownloadDir){
        if(Test-Path -LiteralPath $folder){$existing+=@(Get-ChildItem -LiteralPath $folder -File | Where-Object {$_.Name -match $pattern})}
    }
    if($existing.Count -gt 0 -and -not $Force){Write-Output ('EXISTS '+$job.id+' - run ingest');continue}
    if(-not $Retry -and @($history | Where-Object {$_.url -eq $job.url}).Count -gt 0){
        Write-Output ('ALREADY_REQUESTED '+$job.id+' - inspect progress before -Retry');continue
    }
    $chosen+=$job;$targets+=('"'+$uri.AbsoluteUri+'"');$seen[$job.url]=$true
    if($chosen.Count -ge $Max){break}
}
if($chosen.Count -eq 0){Write-Output 'No eligible new requests';return}
$verb=if($DryRun){'DRY_RUN '}else{'REQUEST '}
foreach($job in $chosen){Write-Output ($verb+$Browser+' '+$job.id+' '+$job.filename)}
if($DryRun){return}
# One normal-browser invocation for this small batch; preserve the existing user session.
# No remote-debugging port, custom profile, headless mode, shell eval or security flags.
$desktopShell=New-Object -ComObject Shell.Application
$desktopShell.ShellExecute($BrowserPath,($targets -join ' '),'','open',1)
foreach($job in $chosen){
    @{time=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds();browser=$Browser;job=$job.id;url=$job.url;filename=$job.filename} |
        ConvertTo-Json -Compress | Add-Content -LiteralPath $logPath -Encoding UTF8
}
