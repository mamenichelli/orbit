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
$orderedKeys = @(
  "ORBIT_DASHBOARD_URL", "ORBIT_AGENT_TOKEN", "ORBIT_INSTAGRAM_USERNAME",
  "ORBIT_DISCOVERY_SEEDS", "ORBIT_USERS_PER_SEED", "ORBIT_MAX_CANDIDATES", "ORBIT_MAX_RELATIONS"
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

$taskName = "Orbit Instagram Sync"
$action = New-ScheduledTaskAction -Execute $pythonPath -Argument "`"$agentScript`" sync --config `"$configPath`"" -WorkingDirectory $projectRoot
$firstRunAt = (Get-Date).AddHours($EveryHours)
$cooldownPath = Join-Path $projectRoot ".orbit-agent\instagram-cooldown.json"
if (Test-Path -LiteralPath $cooldownPath) {
  try {
    $cooldown = Get-Content -LiteralPath $cooldownPath -Raw | ConvertFrom-Json
    $retryAt = [DateTimeOffset]::FromUnixTimeSeconds([long]$cooldown.retry_at).LocalDateTime
    if ($retryAt -gt (Get-Date)) { $firstRunAt = $retryAt }
  } catch {
    $firstRunAt = (Get-Date).AddMinutes(30)
  }
}
$trigger = New-ScheduledTaskTrigger -Once -At $firstRunAt `
  -RepetitionInterval (New-TimeSpan -Hours $EveryHours) `
  -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
  -Description "Sincronizza follower, seguiti e candidati Instagram con Orbit" -Force | Out-Null

Write-Host "Agente attivo. Prossima sincronizzazione automatica ogni $EveryHours ore."
