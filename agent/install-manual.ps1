$ErrorActionPreference = 'Stop'
$orbitProject = Split-Path $PSScriptRoot -Parent
$orbitPython = Join-Path $orbitProject '.venv-agent\Scripts\pythonw.exe'
$orbitScript = Join-Path $PSScriptRoot 'orbit_parallel_bridge.py'
$orbitConfig = Join-Path $orbitProject '.env.agent'
if (!(Test-Path -LiteralPath $orbitPython) -or !(Test-Path -LiteralPath $orbitConfig)) { throw 'Python o configurazione agente assenti' }
if (!(Test-Path -LiteralPath $orbitScript)) { throw 'Bridge Orbit Parallel assente' }
$orbitUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$orbitPrincipal = New-ScheduledTaskPrincipal -UserId $orbitUser -LogonType Interactive -RunLevel Limited
$orbitSettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -RestartCount 10 -RestartInterval (New-TimeSpan -Minutes 1)
$orbitWorker = New-ScheduledTaskAction -Execute $orbitPython -WorkingDirectory $orbitProject -Argument ('"{0}" worker --config "{1}"' -f $orbitScript, $orbitConfig)
$orbitLogon = New-ScheduledTaskTrigger -AtLogOn -User $orbitUser
Stop-ScheduledTask -TaskName 'Orbit Instagram Manual Likes' -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName 'Orbit Instagram Manual Likes' -Action $orbitWorker -Trigger $orbitLogon -Settings $orbitSettings -Principal $orbitPrincipal -Force | Out-Null
Start-ScheduledTask -TaskName 'Orbit Instagram Manual Likes'
Write-Output 'Collegamento manuale avviato su Orbit legacy + Orbit Parallel. I like partono solo dal clic nella dashboard che ha creato il comando.'
