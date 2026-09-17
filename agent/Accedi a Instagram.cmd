@echo off
setlocal
title ORBIT - ACCESSO MARCO MENICHELLI
set "ORBIT_ROOT=C:\Users\marco.menichelli\Documents\Social"
set "ORBIT_PY=%ORBIT_ROOT%\.venv-agent\Scripts\python.exe"
set "ORBIT_AGENT=%ORBIT_ROOT%\agent\orbit_instagram_agent.py"
set "ORBIT_CONFIG=%ORBIT_ROOT%\.env.agent"
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
echo Aggiorno i task Generali e Like manuali...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ORBIT_ROOT%\agent\install-collector.ps1"
if errorlevel 1 goto failed
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ORBIT_ROOT%\agent\install-manual.ps1"
if errorlevel 1 goto failed
echo Accesso rinnovato. Da ora puoi usare il pulsante Rigenera accesso Instagram nella dashboard Orbit.
pause
exit /b 0
:failed
echo Accesso o verifica non completati. Nessuna azione Instagram automatica e' stata eseguita.
pause
exit /b 1
