# Orbit — strategia di prodotto

## Obiettivo

Trasformare interazioni reali su Instagram e Facebook in relazioni misurabili,
senza mettere a rischio gli account con bot, scraping o credenziali salvate.

## Ciclo di crescita

1. **Ascolto (giorni 1–7):** importare via Meta OAuth dati consentiti su contenuti,
   commenti, audience e performance.
2. **Scoring:** ordinare le opportunità usando frequenza e recenza delle
   interazioni, affinità tematica, qualità del profilo e probabilità di relazione.
3. **Coda giornaliera:** proporre poche azioni ad alta qualità: rispondere,
   visitare il profilo, interagire o valutare un follow. Ogni azione richiede
   approvazione umana.
4. **Revisione ogni 10 giorni:** presentare le relazioni da rivedere, escludendo
   sempre whitelist, contatti personali e amministratori dei gruppi.
5. **Misurazione:** attribuire follower, engagement e conversazioni alle azioni
   precedenti; adattare lo scoring in base ai risultati.

## Regole di sicurezza

- OAuth Meta, mai password dei social nel database.
- Nessun follow/unfollow automatico.
- Whitelist con motivazione, autore e data di inserimento.
- Limiti giornalieri configurabili e pausa immediata per account.
- Audit log completo di suggerimenti, approvazioni ed esiti.
- Conservazione minima dei dati e revoca della connessione in qualsiasi momento.

## Roadmap

### MVP

- Dashboard multi-account Instagram/Facebook.
- Growth Score e KPI.
- Opportunità generate dalle interazioni.
- Coda di approvazione.
- Revisione relazioni ogni 10 giorni.
- Lista “intoccabili”.
- Configurazione OAuth e audit log.

### Fase 2

- Calendario editoriale e analisi dei contenuti che convertono.
- Segmenti personalizzati per nicchia, lingua e area geografica.
- Suggerimenti di risposta con tono del brand.
- Esperimenti e attribuzione della crescita.

### Fase 3

- Team, ruoli, approvazioni multiple e report.
- Modelli predittivi addestrati sui risultati del singolo account.
- Estensione ad altri canali supportati da API ufficiali.

## KPI dei primi 30 giorni

- Tasso di conversione interazione → follower.
- Follower rilevanti netti, non volume lordo.
- Reply rate e conversazioni avviate.
- Engagement dei nuovi follower dopo 7 e 30 giorni.
- Numero di azioni suggerite, approvate e completate.
- Zero blocchi, challenge o violazioni dell’account.
