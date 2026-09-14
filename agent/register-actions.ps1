$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".venv-agent\Scripts\python.exe"
$agentScript = Join-Path $PSScriptRoot "orbit_browser_actions.py"
$configPath = Join-Path $projectRoot ".env.agent"
$protectedPath = Join-Path $projectRoot ".orbit-agent\protected-seed.txt"

foreach ($path in @($pythonPath, $agentScript, $configPath, $protectedPath)) {
  if (-not (Test-Path -LiteralPath $path)) { throw "File richiesto assente: $path" }
}

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
  -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

$likeAction = New-ScheduledTaskAction -Execute $pythonPath `
  -Argument "`"$agentScript`" like-general-posts --config `"$configPath`"" `
  -WorkingDirectory $projectRoot
$likeTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) `
  -RepetitionInterval (New-TimeSpan -Minutes 30) `
  -RepetitionDuration (New-TimeSpan -Days 3650)
Register-ScheduledTask -TaskName "Orbit Instagram General Post Likes" `
  -Action $likeAction -Trigger $likeTrigger -Settings $settings -Force `
  -Description "Mette Mi piace ai post condivisi nelle chat Instagram Generali" | Out-Null

$unfollowAction = New-ScheduledTaskAction -Execute $pythonPath `
  -Argument "`"$agentScript`" unfollow-due --config `"$configPath`"" `
  -WorkingDirectory $projectRoot
$unfollowTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(15) `
  -RepetitionInterval (New-TimeSpan -Hours 6) `
  -RepetitionDuration (New-TimeSpan -Days 3650)
Register-ScheduledTask -TaskName "Orbit Instagram Due Unfollows" `
  -Action $unfollowAction -Trigger $unfollowTrigger -Settings $settings -Force `
  -Description "Defollow automatico dopo 10 giorni, escludendo gli intoccabili" | Out-Null

Write-Host "Automazioni registrate: like ogni 30 minuti, defollow ogni 6 ore quando Windows è disponibile."
