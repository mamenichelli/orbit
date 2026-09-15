$ErrorActionPreference = 'Stop'
$orbitProject = Split-Path $PSScriptRoot -Parent
$orbitPython = Join-Path $orbitProject '.venv-agent\Scripts\pythonw.exe'
$orbitScript = Join-Path $PSScriptRoot 'orbit_manual_instagram.py'
$orbitConfig = Join-Path $orbitProject '.env.agent'
if (!(Test-Path -LiteralPath $orbitPython) -or !(Test-Path -LiteralPath $orbitConfig)) { throw 'Python o configurazione agente assenti' }
$orbitUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$orbitPrincipal = New-ScheduledTaskPrincipal -UserId $orbitUser -LogonType Interactive -RunLevel Limited
$orbitSettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$orbitWorker = New-ScheduledTaskAction -Execute $orbitPython -WorkingDirectory $orbitProject -Argument ('"{0}" worker --config "{1}"' -f $orbitScript, $orbitConfig)
$orbitLogon = New-ScheduledTaskTrigger -AtLogOn -User $orbitUser
Register-ScheduledTask -TaskName 'Orbit Instagram Manual Likes' -Action $orbitWorker -Trigger $orbitLogon -Settings $orbitSettings -Principal $orbitPrincipal -Force | Out-Null
Start-ScheduledTask -TaskName 'Orbit Instagram Manual Likes'
Write-Output 'Collegamento manuale avviato. Nessun contenuto delle chat esportato da questa installazione.'
