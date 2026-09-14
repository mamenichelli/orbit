@echo off
setlocal
set "ORBIT_PY=%~dp0..\.venv-agent\Scripts\python.exe"
set "ORBIT_AGENT=%~dp0orbit_instagram_agent.py"
set "ORBIT_CONFIG=%~dp0..\.env.agent"
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
if errorlevel 1 (
  echo Accesso non completato. Lascia aperta la finestra e riprova.
) else (
  echo Accesso salvato. Puoi chiudere questa finestra.
)
pause
