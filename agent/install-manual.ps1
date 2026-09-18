$ErrorActionPreference = 'Stop'
$project = Split-Path $PSScriptRoot -Parent
$python = Join-Path $project '.venv-agent\Scripts\python.exe'
$bridge = Join-Path $PSScriptRoot 'orbit_parallel_bridge.py'
$config = Join-Path $project '.env.agent'
$runtime = Join-Path $project '.orbit-agent'
$runner = Join-Path $PSScriptRoot 'run-orbit-manual.ps1'
$log = Join-Path $runtime 'parallel-manual.log'

if (!(Test-Path -LiteralPath $python) -or !(Test-Path -LiteralPath $config)) { throw 'Python o configurazione agente assenti' }
if (!(Test-Path -LiteralPath $bridge)) { throw 'Bridge Orbit Parallel assente' }
New-Item -ItemType Directory -Force -Path $runtime | Out-Null

Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match '^python(w)?\.exe$' -and $_.CommandLine -and (
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

$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -RestartCount 10 -RestartInterval (New-TimeSpan -Minutes 1)
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -WorkingDirectory $project -Argument ('-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}"' -f $runner)
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user

Stop-ScheduledTask -TaskName 'Orbit Instagram Manual Likes' -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName 'Orbit Instagram Manual Likes' -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Start-ScheduledTask -TaskName 'Orbit Instagram Manual Likes'
Start-Sleep -Seconds 2
$state = (Get-ScheduledTask -TaskName 'Orbit Instagram Manual Likes').State
Write-Output "Worker Like avviato con auto-restart e log: $state"
