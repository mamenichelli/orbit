@echo off
setlocal EnableExtensions
title ORBIT - ATTIVA PARALLEL
set "ORBIT_ROOT=C:\Users\marco.menichelli\Documents\Social"
set "ORBIT_AGENT=%ORBIT_ROOT%\agent"
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

where curl.exe >nul 2>&1
if errorlevel 1 (
  echo curl.exe non disponibile su questo Windows.
  pause
  exit /b 1
)

echo Aggiorno il bridge Orbit legacy + Orbit Parallel...
curl.exe -fL "%RAW%/orbit_parallel_bridge.py" -o "%ORBIT_AGENT%\orbit_parallel_bridge.py.new" || goto failed
curl.exe -fL "%RAW%/install-collector.ps1" -o "%ORBIT_AGENT%\install-collector.ps1.new" || goto failed
curl.exe -fL "%RAW%/install-manual.ps1" -o "%ORBIT_AGENT%\install-manual.ps1.new" || goto failed

move /Y "%ORBIT_AGENT%\orbit_parallel_bridge.py.new" "%ORBIT_AGENT%\orbit_parallel_bridge.py" >nul || goto failed
move /Y "%ORBIT_AGENT%\install-collector.ps1.new" "%ORBIT_AGENT%\install-collector.ps1" >nul || goto failed
move /Y "%ORBIT_AGENT%\install-manual.ps1.new" "%ORBIT_AGENT%\install-manual.ps1" >nul || goto failed

echo Riavvio raccolta Generali e Like manuali...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ORBIT_AGENT%\install-collector.ps1" || goto failed
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ORBIT_AGENT%\install-manual.ps1" || goto failed

echo.
echo FATTO. Il PC ora collega contemporaneamente Orbit legacy e Orbit Parallel.
echo Non sono state modificate password, cookie o sessioni Instagram.
timeout /t 4 >nul
exit /b 0

:failed
del /Q "%ORBIT_AGENT%\*.new" >nul 2>&1
echo.
echo Aggiornamento non completato. I dati di accesso Instagram non sono stati toccati.
pause
exit /b 1
