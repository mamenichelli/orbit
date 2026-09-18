$ErrorActionPreference = 'Stop'
$project = Split-Path $PSScriptRoot -Parent
$python = Join-Path $project '.venv-agent\Scripts\python.exe'
$bridge = Join-Path $PSScriptRoot 'orbit_parallel_bridge.py'
$config = Join-Path $project '.env.agent'
$runtime = Join-Path $project '.orbit-agent'
$runner = Join-Path $PSScriptRoot 'run-orbit-manual.ps1'
$log = Join-Path $runtime 'parallel-manual.log'
$startupDir = [Environment]::GetFolderPath('Startup')
$startupCmd = Join-Path $startupDir 'Orbit Parallel Manual.cmd'

if (!(Test-Path -LiteralPath $python) -or !(Test-Path -LiteralPath $config)) { throw 'Python o configurazione agente assenti' }
if (!(Test-Path -LiteralPath $bridge)) { throw 'Bridge Orbit Parallel assente' }
New-Item -ItemType Directory -Force -Path $runtime | Out-Null

Stop-ScheduledTask -TaskName 'Orbit Instagram Manual Likes' -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName 'Orbit Instagram Manual Likes' -Confirm:$false -ErrorAction SilentlyContinue

Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -and (
        $_.CommandLine -like '*run-orbit-manual.ps1*' -or
        $_.CommandLine -like '*orbit_parallel_bridge.py* worker *' -or
        $_.CommandLine -like '*orbit_instagram_directs.py* worker *'
    )
} | ForEach-Object {
    Invoke-CimMethod -InputObject $_ -MethodName Terminate -ErrorAction SilentlyContinue | Out-Null
}

$runnerBody = @"
`$ErrorActionPreference = 'Continue'
while (`$true) {
    try {
        & '$python' '$bridge' worker --config '$config' *>> '$log'
    } catch {
        ("[{0}] manual wrapper: {1}" -f (Get-Date -Format s), `$_.Exception.Message) | Add-Content -LiteralPath '$log'
    }
    Start-Sleep -Seconds 10
}
"@
Set-Content -LiteralPath $runner -Value $runnerBody -Encoding UTF8

$startupBody = @"
@echo off
start "" /min powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "$runner"
exit /b 0
"@
Set-Content -LiteralPath $startupCmd -Value $startupBody -Encoding ASCII

$proc = Start-Process powershell.exe -WindowStyle Hidden -ArgumentList @(
    '-NoProfile',
    '-ExecutionPolicy', 'Bypass',
    '-File', ('"{0}"' -f $runner)
) -PassThru

Start-Sleep -Seconds 4
$running = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -and $_.CommandLine -like '*run-orbit-manual.ps1*'
}
if (-not $running) {
    Write-Output 'ERRORE: worker manuale non avviato. Ultime righe log:'
    if (Test-Path -LiteralPath $log) { Get-Content -LiteralPath $log -Tail 30 }
    throw 'Worker Like Orbit non in esecuzione'
}
Write-Output 'Worker Like: Running (avvio diretto + Esecuzione automatica Windows)'
