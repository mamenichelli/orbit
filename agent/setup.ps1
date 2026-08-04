param(
  [Parameter(Mandatory = $true)]
  [string]$Username,
  [string]$Seeds = "",
  [int]$EveryHours = 6
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$configPath = Join-Path $projectRoot ".env.agent"
$venvPath = Join-Path $projectRoot ".venv-agent"
$pythonPath = Join-Path $venvPath "Scripts\python.exe"
$requirements = Join-Path $PSScriptRoot "requirements.txt"
$agentScript = Join-Path $PSScriptRoot "orbit_instagram_agent.py"
$systemPython = Get-Command python -ErrorAction SilentlyContinue
$bundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$bootstrapPython = if ($systemPython) { $systemPython.Source } elseif (Test-Path -LiteralPath $bundledPython) { $bundledPython } else { $null }

if (-not $bootstrapPython) {
  throw "Python 3.10+ non trovato. Installa Python da python.org e riesegui lo script."
}

if (-not (Test-Path -LiteralPath $configPath)) {
  throw "Configurazione agente mancante: $configPath"
}

$config = @{}
foreach ($line in Get-Content -LiteralPath $configPath) {
  if ($line -match '^([^#=]+)=(.*)$') { $config[$matches[1].Trim()] = $matches[2].Trim() }
}
$config["ORBIT_INSTAGRAM_USERNAME"] = $Username.Trim().TrimStart("@")
$config["ORBIT_DISCOVERY_SEEDS"] = $Seeds
$orderedKeys = @(
  "ORBIT_DASHBOARD_URL", "ORBIT_AGENT_TOKEN", "ORBIT_INSTAGRAM_USERNAME",
  "ORBIT_DISCOVERY_SEEDS", "ORBIT_USERS_PER_SEED", "ORBIT_MAX_CANDIDATES", "ORBIT_MAX_RELATIONS"
)
$lines = foreach ($key in $orderedKeys) { "$key=$($config[$key])" }
Set-Content -LiteralPath $configPath -Value $lines -Encoding utf8

if (-not (Test-Path -LiteralPath $pythonPath)) {
  & $bootstrapPython -m venv $venvPath
}
& $pythonPath -m pip install --disable-pip-version-check -r $requirements
& $pythonPath $agentScript setup --config $configPath
& $pythonPath $agentScript sync --config $configPath

$taskName = "Orbit Instagram Sync"
$action = New-ScheduledTaskAction -Execute $pythonPath -Argument "`"$agentScript`" sync --config `"$configPath`"" -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddHours($EveryHours) `
  -RepetitionInterval (New-TimeSpan -Hours $EveryHours) `
  -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
  -Description "Sincronizza follower, seguiti e candidati Instagram con Orbit" -Force | Out-Null

Write-Host "Agente attivo. Prossima sincronizzazione automatica ogni $EveryHours ore."
