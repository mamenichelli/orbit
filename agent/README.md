# Agente Instagram automatico di Orbit

Questo componente usa `instagrapi`, progetto open source MIT, esclusivamente in lettura.
La password non viene inviata alla dashboard: Windows la conserva nel proprio Gestore credenziali.

## Attivazione

Apri PowerShell nella cartella del progetto ed esegui:

```powershell
.\agent\setup.ps1 -Username TUO_USERNAME
```

Puoi aggiungere profili affini con `-Seeds "profilo1,profilo2"`; se li ometti,
l’agente usa automaticamente i suggerimenti e la categoria del tuo profilo Instagram.
Inserisci la password e l'eventuale codice 2FA quando richiesti. Lo script:

1. crea un ambiente Python locale;
2. salva una sessione Instagram sul PC;
3. scarica follower e seguiti;
4. esclude follower attuali e persone già seguite;
5. analizza follower recenti dei profili seed;
6. invia alla dashboard la lista ordinata;
7. registra l'attività pianificata `Orbit Instagram Sync` ogni 6 ore.

Per forzare una sincronizzazione:

```powershell
.\.venv-agent\Scripts\python.exe .\agent\orbit_instagram_agent.py sync --config .\.env.agent
```

L'accesso usa API Instagram non ufficiali. Può essere soggetto a challenge o limiti di frequenza;
se Instagram invalida la sessione, riesegui `setup.ps1`. L'agente non esegue follow, like,
commenti o unfollow automatici.
