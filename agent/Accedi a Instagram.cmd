@echo off
setlocal
title ORBIT - ACCESSO MARCO MENICHELLI
set "ORBIT_PY=C:\Users\marco.menichelli\Documents\Social\.venv-agent\Scripts\python.exe"
set "ORBIT_AGENT=C:\Users\marco.menichelli\Documents\Social\agent\orbit_instagram_agent.py"
set "ORBIT_MANUAL=C:\Users\marco.menichelli\Documents\Social\agent\orbit_manual_instagram.py"
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
echo Avvio il collegamento dei like scelti singolarmente dalla dashboard...
"%ORBIT_PY%" "%ORBIT_MANUAL%" worker --config "%ORBIT_CONFIG%"
if errorlevel 1 goto failed
echo Collegamento manuale terminato.
pause
exit /b 0
:failed
echo Accesso o verifica non completati. Automazioni ancora ferme: non usare Primezone.
pause
exit /b 1
