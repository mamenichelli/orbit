@echo off
setlocal
title ORBIT - ACCESSO MARCO MENICHELLI
set "ORBIT_PY=C:\Users\marco.menichelli\Documents\Social\.venv-agent\Scripts\python.exe"
set "ORBIT_AGENT=C:\Users\marco.menichelli\Documents\Social\agent\orbit_instagram_agent.py"
set "ORBIT_ACTIONS=C:\Users\marco.menichelli\Documents\Social\agent\orbit_browser_actions.py"
set "ORBIT_CONFIG=C:\Users\marco.menichelli\Documents\Social\.env.agent"
if not exist "%ORBIT_PY%" (
  echo Python agente non trovato: "%ORBIT_PY%"
  pause
  exit /b 1
)
if not exist "%ORBIT_CONFIG%" (
  echo Configurazione agente non trovata: "%ORBIT_CONFIG%"
  pause
  exit /b 1
)
"%ORBIT_PY%" "%ORBIT_AGENT%" setup --config "%ORBIT_CONFIG%" --auth-mode browser
if errorlevel 1 goto failed
echo Profilo Marco verificato. Sincronizzo follower e seguiti...
"%ORBIT_PY%" "%ORBIT_AGENT%" sync --config "%ORBIT_CONFIG%"
if errorlevel 1 goto failed
echo Controllo i post condivisi nelle chat Generali...
"%ORBIT_PY%" "%ORBIT_ACTIONS%" like-general-posts --config "%ORBIT_CONFIG%"
if errorlevel 1 goto failed
echo Controllo i defollow dovuti, esclusi i 549 intoccabili...
"%ORBIT_PY%" "%ORBIT_ACTIONS%" unfollow-due --config "%ORBIT_CONFIG%"
if errorlevel 1 goto failed
powershell -NoProfile -Command "Enable-ScheduledTask -TaskName 'Orbit Instagram General Post Likes' | Out-Null; Enable-ScheduledTask -TaskName 'Orbit Instagram Due Unfollows' | Out-Null"
if errorlevel 1 goto failed
echo Automazioni attive per il profilo Marco Menichelli.
pause
exit /b 0
:failed
echo Accesso o verifica non completati. Automazioni ancora ferme: non usare Primezone.
pause
exit /b 1
