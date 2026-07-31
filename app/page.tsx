"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

type SocialAccount = {
  id: string;
  platform: "instagram" | "facebook";
  displayName: string;
  username: string | null;
  followers: number | null;
  mediaCount: number | null;
  syncStatus: "live" | "connected";
  updatedAt: string;
};

type Candidate = {
  externalId: string;
  name: string;
  username: string | null;
  platform: "Instagram" | "Facebook";
  interactions: number;
  score: number;
  reason: string;
  lastInteraction: string;
};

type Strategy = {
  key: string;
  title: string;
  description: string;
  ready: boolean;
};

type Snapshot = {
  accounts: SocialAccount[];
  opportunities: Candidate[];
  metrics: {
    connectedAccounts: number;
    knownFollowers: number;
    webhookEvents: number;
    analyzedPeople: number;
  };
  strategy: Strategy[];
  lastSync: string | null;
};

const nav = ["Panoramica", "Opportunità", "Relazioni", "Contenuti", "Attività"];
const emptySnapshot: Snapshot = {
  accounts: [],
  opportunities: [],
  metrics: { connectedAccounts: 0, knownFollowers: 0, webhookEvents: 0, analyzedPeople: 0 },
  strategy: [],
  lastSync: null,
};

function initials(value: string) {
  return value.split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase() || "OR";
}

function formatNumber(value: number) {
  return new Intl.NumberFormat("it-IT").format(value);
}

function formatDate(value: string | null) {
  if (!value) return "in attesa dei primi dati";
  return new Intl.DateTimeFormat("it-IT", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export default function Home() {
  const [active, setActive] = useState("Panoramica");
  const [snapshot, setSnapshot] = useState<Snapshot>(emptySnapshot);
  const [approved, setApproved] = useState<string[]>([]);
  const [protectedIds, setProtectedIds] = useState<string[]>([]);
  const [showConfig, setShowConfig] = useState(false);
  const [toast, setToast] = useState("");
  const [loading, setLoading] = useState(true);
  const [syncError, setSyncError] = useState("");

  const refresh = useCallback(async (manual = false) => {
    try {
      if (manual) setLoading(true);
      const sessionResponse = await fetch("/api/meta/snapshot", { cache: "no-store" });
      const sessionText = await sessionResponse.text();
      let session: { gatewayUrl?: string; accessToken?: string; error?: string };
      try {
        session = JSON.parse(sessionText) as typeof session;
      } catch {
        throw new Error("Il servizio di sincronizzazione non ha risposto correttamente");
      }
      if (!sessionResponse.ok || !session.gatewayUrl || !session.accessToken) {
        throw new Error(session.error ?? "Sincronizzazione non disponibile");
      }

      const response = await fetch(session.gatewayUrl, {
        headers: { authorization: `Bearer ${session.accessToken}` },
        cache: "no-store",
      });
      const responseText = await response.text();
      let body: Snapshot & { error?: string };
      try {
        body = JSON.parse(responseText) as typeof body;
      } catch {
        throw new Error("Il gateway Meta è temporaneamente lento: riprova tra poco");
      }
      if (!response.ok) throw new Error(body.error ?? "Sincronizzazione non disponibile");
      setSnapshot(body);
      setSyncError("");
      if (manual) {
        setToast("Profili e interazioni aggiornati");
        window.setTimeout(() => setToast(""), 2600);
      }
    } catch (error) {
      setSyncError(error instanceof Error ? error.message : "Sincronizzazione non disponibile");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 60_000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("meta") === "connected") {
      setToast("Profili Meta collegati. Sincronizzazione avviata.");
      window.setTimeout(() => setToast(""), 3200);
      window.history.replaceState({}, "", window.location.pathname);
      void refresh();
    }
  }, [refresh]);

  const visibleCandidates = useMemo(
    () => snapshot.opportunities.filter((candidate) => !approved.includes(candidate.externalId)),
    [approved, snapshot.opportunities],
  );

  const growthScore = useMemo(() => {
    if (!snapshot.accounts.length) return 0;
    const dataScore = Math.min(30, snapshot.metrics.webhookEvents * 2);
    const relationshipScore = Math.min(30, snapshot.metrics.analyzedPeople * 4);
    const liveScore = snapshot.accounts.some((account) => account.syncStatus === "live") ? 20 : 8;
    return Math.min(100, 20 + dataScore + relationshipScore + liveScore);
  }, [snapshot]);

  const notify = (message: string) => {
    setToast(message);
    window.setTimeout(() => setToast(""), 2600);
  };

  const persist = async (
    operation: "protect" | "unprotect" | "approve",
    candidate: Candidate,
  ) => {
    try {
      const response = await fetch("/api/growth", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          operation,
          externalId: candidate.externalId,
          displayName: candidate.name,
          platform: candidate.platform,
        }),
      });
      if (!response.ok) throw new Error("Salvataggio non riuscito");
    } catch {
      notify("Azione non salvata: riprova tra poco");
    }
  };

  const strategies: Strategy[] = snapshot.strategy.length ? snapshot.strategy : [
    { key: "reciprocity", title: "Reciprocità selettiva", description: "In attesa dei primi segnali Meta.", ready: false },
    { key: "recency", title: "Finestra di recenza", description: "In attesa dei primi segnali Meta.", ready: false },
    { key: "consistency", title: "Continuità editoriale", description: "In attesa dei primi segnali Meta.", ready: false },
  ];

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark">O</span><span>Orbit</span></div>
        <nav aria-label="Navigazione principale">
          {nav.map((item, index) => (
            <button key={item} className={active === item ? "nav-item active" : "nav-item"} onClick={() => setActive(item)}>
              <span className="nav-icon">{["⌂", "✦", "♧", "▧", "↗"][index]}</span>{item}
              {item === "Opportunità" && snapshot.metrics.analyzedPeople > 0 && (
                <span className="badge">{snapshot.metrics.analyzedPeople}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <button className="nav-item" onClick={() => setShowConfig(true)}><span className="nav-icon">⚙</span>Impostazioni</button>
          <div className="profile">
            <span className="avatar mini">MM</span>
            <div><strong>Marco M.</strong><small>Amministratore</small></div>
            <span className="more">•••</span>
          </div>
        </div>
      </aside>

      <section className="content">
        <header className="topbar">
          <div>
            <p className="eyebrow">CONTROLLO CRESCITA META</p>
            <h1>{active === "Panoramica" ? "Bentornato, Marco" : active}</h1>
            <p className="sync-copy">
              {loading ? "Sincronizzazione…" : `Ultimo aggiornamento: ${formatDate(snapshot.lastSync)}`}
              {syncError && <span className="sync-error"> · {syncError}</span>}
            </p>
          </div>
          <div className="top-actions">
            <button className="icon-button refresh-button" aria-label="Aggiorna dati" onClick={() => void refresh(true)}>↻</button>
            <button className="primary" onClick={() => setShowConfig(true)}>＋ Connetti profilo</button>
          </div>
        </header>

        {active !== "Panoramica" && active !== "Opportunità" ? (
          <section className="empty-view">
            <span>✦</span><h2>{active}</h2>
            <p>I dati collegati alimentano automaticamente questo modulo. Le prossime azioni conformi saranno attivate quando i relativi permessi Meta saranno approvati.</p>
            <button className="primary" onClick={() => setActive("Panoramica")}>Torna alla panoramica</button>
          </section>
        ) : (
          <>
            {active === "Panoramica" && (
              <section className="hero-grid">
                <article className="growth-card">
                  <div className="section-heading">
                    <div><p className="eyebrow">GROWTH SCORE LIVE</p><h2>{snapshot.accounts.length ? "Il motore di analisi è attivo" : "Collega il primo profilo"}</h2></div>
                    <span className="trend">{snapshot.metrics.connectedAccounts} account</span>
                  </div>
                  <div className="score-row">
                    <div className="score-ring" style={{ background: `conic-gradient(#3b8e70 0 ${growthScore}%,#e7eeeb ${growthScore}%)` }}>
                      <div><strong>{growthScore}</strong><span>/100</span></div>
                    </div>
                    <div className="score-copy">
                      <p>Il punteggio cresce con dati live, interazioni ricevute e relazioni ricorrenti. Orbit aggiorna l’analisi ogni minuto.</p>
                      <div className="mini-stats">
                        <div><span>Follower rilevati</span><strong>{formatNumber(snapshot.metrics.knownFollowers)}</strong><small>dati disponibili via Meta</small></div>
                        <div><span>Persone analizzate</span><strong>{snapshot.metrics.analyzedPeople}</strong><small>{snapshot.metrics.webhookEvents} eventi ricevuti</small></div>
                      </div>
                    </div>
                  </div>
                </article>

                <article className="review-card">
                  <div className="calendar-icon"><span>10</span><small>GIORNI</small></div>
                  <div>
                    <p className="eyebrow">REVISIONE RELAZIONI</p>
                    <h2>Scrematura protetta</h2>
                    <p>Orbit prepara ogni 10 giorni la revisione e non include mai gli account segnati come intoccabili.</p>
                  </div>
                  <button className="secondary" onClick={() => setActive("Opportunità")}>Apri le priorità <span>→</span></button>
                </article>
              </section>
            )}

            <section className={active === "Opportunità" ? "workspace-grid opportunities-focus" : "workspace-grid"}>
              <article className="panel opportunities">
                <div className="panel-head">
                  <div><p className="eyebrow">PRIORITÀ AUTOMATICHE</p><h2>Persone con cui interagire</h2></div>
                  <span className="live-pill">● LIVE</span>
                </div>
                <p className="muted">Ordinate per frequenza, recenza e valore dell’interazione ricevuta.</p>
                <div className="candidate-list">
                  {loading && !snapshot.opportunities.length && <div className="all-done">Sto leggendo le interazioni Meta…</div>}
                  {!loading && !visibleCandidates.length && (
                    <div className="all-done">
                      {snapshot.accounts.length
                        ? "Profili connessi. Le persone compariranno qui appena Meta invierà commenti, reazioni o messaggi tramite webhook."
                        : "Collega Instagram professionale o una Pagina Facebook per iniziare."}
                    </div>
                  )}
                  {visibleCandidates.map((candidate, index) => (
                    <div className="candidate" key={`${candidate.platform}-${candidate.externalId}`}>
                      <span className="avatar" style={{ background: ["#ffb1bf", "#ffd989", "#b7d8ff", "#bde8d0"][index % 4] }}>{initials(candidate.name)}</span>
                      <div className="candidate-copy">
                        <strong>{candidate.name}<span className="platform">{candidate.platform === "Instagram" ? "◎" : "f"}</span></strong>
                        <span>{candidate.username ? `@${candidate.username.replace(/^@/, "")}` : candidate.platform}</span>
                        <small>{candidate.reason} · ultima {formatDate(candidate.lastInteraction)}</small>
                      </div>
                      <div className="match"><strong>{candidate.score}%</strong><span>priorità</span></div>
                      <button
                        className={protectedIds.includes(candidate.externalId) ? "protect selected" : "protect"}
                        aria-label="Proteggi profilo"
                        onClick={() => {
                          const isProtected = protectedIds.includes(candidate.externalId);
                          setProtectedIds((ids) => isProtected ? ids.filter((id) => id !== candidate.externalId) : [...ids, candidate.externalId]);
                          void persist(isProtected ? "unprotect" : "protect", candidate);
                          notify(isProtected ? "Profilo rimosso dagli intoccabili" : "Profilo aggiunto agli intoccabili");
                        }}
                      >♧</button>
                      <button className="approve" onClick={() => {
                        setApproved((items) => [...items, candidate.externalId]);
                        void persist("approve", candidate);
                        notify(`${candidate.name} aggiunto alla coda prioritaria`);
                      }}>Priorità</button>
                    </div>
                  ))}
                </div>
              </article>

              <aside className="right-stack">
                <article className="panel account-panel">
                  <div className="panel-head"><div><p className="eyebrow">PROFILI CONNESSI</p><h2>Account reali</h2></div><button className="text-button" onClick={() => setShowConfig(true)}>Gestisci</button></div>
                  {!snapshot.accounts.length && !loading && <p className="account-empty">Nessun account ricevuto dal gateway.</p>}
                  {snapshot.accounts.map((account) => (
                    <div className="account-row" key={`${account.platform}-${account.id}`}>
                      <span className={`social-icon ${account.platform}`}>{account.platform === "instagram" ? "◎" : "f"}</span>
                      <div>
                        <strong>{account.username ? `@${account.username.replace(/^@/, "")}` : account.displayName}</strong>
                        <small>{account.platform === "instagram" ? "Instagram professionale" : "Pagina Facebook"}{account.followers !== null ? ` · ${formatNumber(account.followers)} follower` : ""}</small>
                      </div>
                      <span className={account.syncStatus === "live" ? "status live" : "status"}>{account.syncStatus === "live" ? "Live" : "Connesso"}</span>
                    </div>
                  ))}
                </article>

                <article className="panel activity-panel">
                  <div className="panel-head"><div><p className="eyebrow">MOTORE AUTOMATICO</p><h2>Stato operativo</h2></div></div>
                  <div className="activity"><span className="activity-mark green">↻</span><p><strong>Sincronizzazione attiva</strong><small>Aggiornamento automatico ogni minuto</small></p><time>live</time></div>
                  <div className="activity"><span className="activity-mark violet">✦</span><p><strong>Ranking interazioni</strong><small>Recenza, frequenza e qualità dei segnali</small></p><time>{snapshot.metrics.analyzedPeople}</time></div>
                  <div className="activity"><span className="activity-mark amber">♧</span><p><strong>Lista intoccabili</strong><small>Esclusa da ogni revisione</small></p><time>{protectedIds.length}</time></div>
                </article>
              </aside>
            </section>

            <section className="strategy strategy-live">
              <div><p className="eyebrow">STRATEGIA COMPORTAMENTALE</p><h2>Relazioni che convertono</h2></div>
              <div className="strategy-cards">
                {strategies.map((item, index) => (
                  <div className={item.ready ? "strategy-item ready" : "strategy-item"} key={item.key}>
                    <span>{index + 1}</span><p><strong>{item.title}</strong><small>{item.description}</small></p>
                  </div>
                ))}
              </div>
              <p>Orbit privilegia chi mostra interesse reale. Follow, unfollow e like personali non sono eseguibili dalle API ufficiali Meta; la revisione resta una coda guidata e protetta, mentre analisi e priorità sono automatiche.</p>
            </section>
          </>
        )}
      </section>

      {showConfig && (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.currentTarget === event.target && setShowConfig(false)}>
          <section className="modal" role="dialog" aria-modal="true" aria-labelledby="config-title">
            <button className="close" onClick={() => setShowConfig(false)} aria-label="Chiudi">×</button>
            <p className="eyebrow">CONFIGURAZIONE</p><h2 id="config-title">Connetti o rinnova i profili</h2>
            <p className="muted">La connessione avviene tramite Meta OAuth. Orbit non vede né salva la tua password.</p>
            <a className="connect instagram-button" href="/api/meta/connect">◎ Connetti Instagram professionale</a>
            <a className="connect facebook-button" href="/api/meta/connect">f Connetti Pagine Facebook</a>
            <div className="safety-note"><strong>Automazione conforme</strong><span>Profili, metriche e interazioni si sincronizzano in automatico. Le azioni che Meta non espone vengono trasformate in una coda prioritaria, mai simulate con bot o password.</span></div>
          </section>
        </div>
      )}
      {toast && <div className="toast" role="status">{toast}</div>}
    </main>
  );
}
