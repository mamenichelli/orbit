param(
  [Parameter(Mandatory = $true)]
  [string]$Username,
  [string]$Seeds = "",
  [int]$EveryHours = 6,
  [ValidateSet("session", "browser", "password")]
  [string]$AuthMode = "session"
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
$config["ORBIT_USERS_PER_SEED"] = "12"
$config["ORBIT_MAX_CANDIDATES"] = "3"
$orderedKeys = @(
  "ORBIT_DASHBOARD_URL", "ORBIT_AGENT_TOKEN", "ORBIT_INSTAGRAM_USERNAME",
  "ORBIT_SIWC_BYPASS_TOKEN", "ORBIT_DISCOVERY_SEEDS", "ORBIT_USERS_PER_SEED",
  "ORBIT_MAX_CANDIDATES", "ORBIT_MAX_RELATIONS"
)
$lines = foreach ($key in $orderedKeys) { "$key=$($config[$key])" }
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllLines($configPath, $lines, $utf8NoBom)

if (-not (Test-Path -LiteralPath $pythonPath)) {
  & $bootstrapPython -m venv $venvPath
}
& $pythonPath -m pip install --disable-pip-version-check -r $requirements
if ($LASTEXITCODE -ne 0) { throw "Installazione dipendenze non riuscita" }
& $pythonPath $agentScript setup --config $configPath --auth-mode $AuthMode
if ($LASTEXITCODE -ne 0) { throw "Accesso Instagram non riuscito: attività automatica non registrata" }
& $pythonPath $agentScript sync --config $configPath
if ($LASTEXITCODE -ne 0) { throw "Prima sincronizzazione non riuscita: attività automatica non registrata" }

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
  -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

$syncTaskName = "Orbit Instagram Sync"
$syncAction = New-ScheduledTaskAction -Execute $pythonPath -Argument "`"$agentScript`" sync --config `"$configPath`"" -WorkingDirectory $projectRoot
$syncFirstRunAt = (Get-Date).AddHours($EveryHours)

$discoveryTaskName = "Orbit Instagram Discovery"
$discoveryAction = New-ScheduledTaskAction -Execute $pythonPath -Argument "`"$agentScript`" discover --config `"$configPath`"" -WorkingDirectory $projectRoot
$discoveryFirstRunAt = (Get-Date).AddMinutes(10)
$cooldownPath = Join-Path $projectRoot ".orbit-agent\instagram-cooldown.json"
if (Test-Path -LiteralPath $cooldownPath) {
  try {
    $cooldown = Get-Content -LiteralPath $cooldownPath -Raw | ConvertFrom-Json
    $retryAt = [DateTimeOffset]::FromUnixTimeSeconds([long]$cooldown.retry_at).LocalDateTime
    if ($retryAt -gt (Get-Date)) { $discoveryFirstRunAt = $retryAt }
  } catch {
    $discoveryFirstRunAt = (Get-Date).AddMinutes(30)
  }
}
$relationCachePath = Join-Path $projectRoot ".orbit-agent\instagram-relations-cache.json"
if (-not (Test-Path -LiteralPath $relationCachePath)) {
  $syncFirstRunAt = if ($retryAt -and $retryAt -gt (Get-Date)) { $retryAt } else { (Get-Date).AddMinutes(10) }
  $discoveryFirstRunAt = $syncFirstRunAt.AddMinutes(15)
}
$syncTrigger = New-ScheduledTaskTrigger -Once -At $syncFirstRunAt `
  -RepetitionInterval (New-TimeSpan -Hours $EveryHours) `
  -RepetitionDuration (New-TimeSpan -Days 3650)
Register-ScheduledTask -TaskName $syncTaskName -Action $syncAction -Trigger $syncTrigger -Settings $settings `
  -Description "Aggiorna follower e seguiti Instagram per Orbit" -Force | Out-Null

$discoveryTrigger = New-ScheduledTaskTrigger -Once -At $discoveryFirstRunAt `
  -RepetitionInterval (New-TimeSpan -Minutes 30) `
  -RepetitionDuration (New-TimeSpan -Days 3650)
Register-ScheduledTask -TaskName $discoveryTaskName -Action $discoveryAction -Trigger $discoveryTrigger -Settings $settings `
  -Description "Cerca piccoli lotti di candidate Instagram verificate per Orbit" -Force | Out-Null

Write-Host "Agente attivo: relazioni ogni $EveryHours ore, ricerca candidate ogni 30 minuti."
