# Agente Instagram automatico di Orbit

Questo componente usa `instagrapi`, progetto open source MIT, esclusivamente in lettura.
La password non viene inviata alla dashboard: Windows la conserva nel proprio Gestore credenziali.

## Attivazione

Apri PowerShell nella cartella del progetto ed esegui:

```powershell
.\agent\setup.ps1 -Username TUO_USERNAME -AuthMode session
```

La ricerca automatica ruota sugli argomenti affini italiani configurati in
`ORBIT_DISCOVERY_QUERIES`. I profili indicati con `-Seeds` restano disponibili come
riferimenti manuali, ma non sono necessari per alimentare la lista.
Apri Instagram nel normale Edge/Chrome già autenticato, premi `F12`, quindi vai in
**Applicazione → Cookie → https://www.instagram.com** e copia il valore di `sessionid`.
Incollalo nel prompt nascosto dello script. Non inviarlo in chat: equivale a una password.
La sessione viene salvata nel Gestore credenziali Windows e non viene inviata a Orbit.
Viene usata soltanto come sessione web: lo script non tenta di convertirla in un login mobile.
Se il sito usa la protezione "Sign in with ChatGPT", `ORBIT_SIWC_BYPASS_TOKEN` consente
esclusivamente al task locale di raggiungere il gateway prima della verifica `ORBIT_AGENT_TOKEN`.
Lo script:

1. crea un ambiente Python locale;
2. salva una sessione Instagram sul PC;
3. scarica follower e seguiti;
4. esclude follower attuali e persone già seguite;
5. salva localmente le relazioni e ruota su una ricerca affine italiana alla volta, aprendo pochi profili per non superare i limiti Instagram;
6. mantiene profili con segnali pubblici italiani, dà priorità alle donne dichiarate nella bio ed esclude uomini dichiarati, account vuoti, inattivi o sproporzionati;
7. invia alla dashboard la lista ordinata;
8. registra `Orbit Instagram Sync` ogni 6 ore e `Orbit Instagram Discovery` ogni 30 minuti; ogni lotto cerca 12 candidate verificate, controlla prima i commentatori ricorrenti rilevati tramite il collegamento ufficiale e, se Instagram limita la ricerca dati, completa dalla pagina Esplora/Suggeriti e dalla rete correlata senza cancellare le candidate già verificate.

Per forzare una sincronizzazione:

```powershell
.\.venv-agent\Scripts\python.exe .\agent\orbit_instagram_agent.py sync --config .\.env.agent
```

Per forzare soltanto un piccolo lotto di ricerca, senza riscaricare tutte le relazioni:

```powershell
.\.venv-agent\Scripts\python.exe .\agent\orbit_instagram_agent.py discover --config .\.env.agent
```

Per un account con password Instagram autonoma puoi usare `-AuthMode password`.
La modalità browser automatizzata resta disponibile con `-AuthMode browser`, ma Google può
bloccarla per ragioni di sicurezza; non va usata quando Facebook richiede l’accesso Google.

L'accesso usa API Instagram non ufficiali. Può essere soggetto a challenge o limiti di frequenza;
se Instagram risponde con HTTP 429, Orbit conserva la sessione e pianifica automaticamente il
tentativo successivo senza richiedere di nuovo il cookie. Se Instagram invalida la sessione,
riesegui `setup.ps1`. L'agente non esegue follow, like, commenti o unfollow automatici.
