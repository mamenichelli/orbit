@echo off
setlocal EnableExtensions
title ORBIT - RIPARA E ATTIVA PARALLEL
set "ORBIT_ROOT=C:\Users\marco.menichelli\Documents\Social"
set "ORBIT_AGENT=%ORBIT_ROOT%\agent"
set "ORBIT_PY=%ORBIT_ROOT%\.venv-agent\Scripts\python.exe"
set "RAW=https://raw.githubusercontent.com/mamenichelli/orbit/main/agent"

if not exist "%ORBIT_AGENT%" (
  echo Cartella Orbit non trovata: "%ORBIT_AGENT%"
  pause
  exit /b 1
)
if not exist "%ORBIT_ROOT%\.env.agent" (
  echo Configurazione .env.agent non trovata. Nessuna modifica eseguita.
  pause
  exit /b 1
)
if not exist "%ORBIT_PY%" (
  echo Python agente non trovato: "%ORBIT_PY%"
  pause
  exit /b 1
)
where curl.exe >nul 2>&1
if errorlevel 1 (
  echo curl.exe non disponibile su questo Windows.
  pause
  exit /b 1
)

set FILES=orbit_parallel_bridge.py orbit_instagram_directs.py orbit_manual_instagram.py orbit_browser_actions.py orbit_instagram_agent.py install-collector.ps1 install-manual.ps1 requirements.txt

echo.
echo [1/4] Scarico il runtime Orbit aggiornato...
for %%F in (%FILES%) do (
  echo   %%F
  curl.exe -fsSL "%RAW%/%%F" -o "%ORBIT_AGENT%\%%F.new"
  if errorlevel 1 goto failed
)

echo.
echo [2/4] Sostituisco i file agente...
for %%F in (%FILES%) do (
  move /Y "%ORBIT_AGENT%\%%F.new" "%ORBIT_AGENT%\%%F" >nul
  if errorlevel 1 goto failed
)

echo.
echo [3/4] Testo ENTRAMBE le dashboard prima di avviare i task...
"%ORBIT_PY%" "%ORBIT_AGENT%\orbit_parallel_bridge.py" test --config "%ORBIT_ROOT%\.env.agent"
if errorlevel 1 goto testfailed

echo.
echo [4/4] Reinstallo e riavvio raccolta Generali e Like manuali...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ORBIT_AGENT%\install-collector.ps1"
if errorlevel 1 goto failed
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ORBIT_AGENT%\install-manual.ps1"
if errorlevel 1 goto failed

echo.
echo ============================================================
echo FATTO. Orbit legacy + Orbit Parallel sono collegati insieme.
echo Se avevi gia' richiesto il rinnovo, Edge dovrebbe aprirsi entro pochi secondi.
echo Non sono state modificate password, cookie o sessioni Instagram.
echo ============================================================
pause
exit /b 0

:testfailed
echo.
echo ============================================================
echo TEST DI COLLEGAMENTO FALLITO.
echo Leggi la riga ERRORE qui sopra e mandami una foto della finestra.
echo I task esistenti non sono stati reinstallati.
echo ============================================================
pause
exit /b 2

:failed
for %%F in (%FILES%) do del /Q "%ORBIT_AGENT%\%%F.new" >nul 2>&1
echo.
echo Aggiornamento non completato. I dati di accesso Instagram non sono stati toccati.
pause
exit /b 1
