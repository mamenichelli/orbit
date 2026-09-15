$ErrorActionPreference = 'Stop'
$collectorProject = Split-Path $PSScriptRoot -Parent
$collectorPython = Join-Path $collectorProject '.venv-agent\Scripts\pythonw.exe'
$collectorScript = Join-Path $PSScriptRoot 'orbit_manual_instagram.py'
$collectorConfig = Join-Path $collectorProject '.env.agent'
if (!(Test-Path -LiteralPath $collectorPython) -or !(Test-Path -LiteralPath $collectorConfig)) { throw 'Python o configurazione agente assenti' }
$collectorUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$collectorPrincipal = New-ScheduledTaskPrincipal -UserId $collectorUser -LogonType Interactive -RunLevel Limited
$collectorSettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5)
$collectorAction = New-ScheduledTaskAction -Execute $collectorPython -WorkingDirectory $collectorProject -Argument ('"{0}" watch --publish-collected-posts --interval 60 --config "{1}"' -f $collectorScript, $collectorConfig)
$collectorLogon = New-ScheduledTaskTrigger -AtLogOn -User $collectorUser
Register-ScheduledTask -TaskName 'Orbit Instagram General Collection' -Action $collectorAction -Trigger $collectorLogon -Settings $collectorSettings -Principal $collectorPrincipal -Force | Out-Null
Start-ScheduledTask -TaskName 'Orbit Instagram General Collection'
Write-Output 'Raccolta continuativa Generale registrata. Solo lettura: nessun like o defollow automatico.'
