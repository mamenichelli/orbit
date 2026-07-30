"use client";

import { useMemo, useState } from "react";

type Candidate = {
  id: number;
  initials: string;
  name: string;
  handle: string;
  reason: string;
  score: number;
  accent: string;
  platform: "Instagram" | "Facebook";
};

const candidates: Candidate[] = [
  { id: 1, initials: "GF", name: "Giulia Ferri", handle: "@giulia.crea", reason: "3 commenti · pubblico affine", score: 94, accent: "#ffb1bf", platform: "Instagram" },
  { id: 2, initials: "MS", name: "Marco Sala", handle: "@marco.foodlab", reason: "Ha salvato 4 post", score: 89, accent: "#ffd989", platform: "Instagram" },
  { id: 3, initials: "AN", name: "Alice Neri", handle: "@alicenstudio", reason: "Interazione ricorrente", score: 86, accent: "#b7d8ff", platform: "Instagram" },
  { id: 4, initials: "LC", name: "Luca Conti", handle: "Luca Conti", reason: "Attivo nel gruppo Creator Italia", score: 81, accent: "#bde8d0", platform: "Facebook" },
];

const nav = ["Panoramica", "Opportunità", "Relazioni", "Contenuti", "Attività"];

export default function Home() {
  const [active, setActive] = useState("Panoramica");
  const [approved, setApproved] = useState<number[]>([]);
  const [protectedIds, setProtectedIds] = useState<number[]>([4]);
  const [showConfig, setShowConfig] = useState(false);
  const [toast, setToast] = useState("");
  const visibleCandidates = useMemo(
    () => candidates.filter((candidate) => !approved.includes(candidate.id)),
    [approved],
  );

  const notify = (message: string) => {
    setToast(message);
    window.setTimeout(() => setToast(""), 2600);
  };

  const persist = async (
    operation: "protect" | "unprotect" | "approve",
    candidate: Candidate,
  ) => {
    try {
      await fetch("/api/growth", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          operation,
          externalId: String(candidate.id),
          displayName: candidate.name,
          platform: candidate.platform,
        }),
      });
    } catch {
      notify("Azione salvata nella sessione; sincronizzazione in attesa");
    }
  };

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark">O</span><span>Orbit</span></div>
        <nav aria-label="Navigazione principale">
          {nav.map((item, index) => (
            <button key={item} className={active === item ? "nav-item active" : "nav-item"} onClick={() => setActive(item)}>
              <span className="nav-icon">{["⌂", "✦", "♧", "▧", "↗"][index]}</span>{item}
              {item === "Opportunità" && <span className="badge">12</span>}
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
            <p className="eyebrow">GIOVEDÌ, 30 LUGLIO</p>
            <h1>{active === "Panoramica" ? "Bentornato, Marco" : active}</h1>
          </div>
          <div className="top-actions">
            <button className="icon-button" aria-label="Notifiche">♢<span className="dot" /></button>
            <button className="primary" onClick={() => setShowConfig(true)}>＋ Connetti profilo</button>
          </div>
        </header>

        {active !== "Panoramica" ? (
          <section className="empty-view">
            <span>✦</span><h2>{active}</h2>
            <p>Questa area è pronta per il prossimo modulo. La panoramica contiene già il flusso operativo completo della prima release.</p>
            <button className="primary" onClick={() => setActive("Panoramica")}>Torna alla panoramica</button>
          </section>
        ) : (
          <>
            <section className="hero-grid">
              <article className="growth-card">
                <div className="section-heading">
                  <div><p className="eyebrow">GROWTH SCORE</p><h2>La tua crescita è in salute</h2></div>
                  <span className="trend">↗ 8,4%</span>
                </div>
                <div className="score-row">
                  <div className="score-ring"><div><strong>82</strong><span>/100</span></div></div>
                  <div className="score-copy">
                    <p>Il profilo sta attirando persone rilevanti. Mantieni il ritmo: le relazioni autentiche stanno convertendo meglio.</p>
                    <div className="mini-stats">
                      <div><span>Follower</span><strong>12.842</strong><small>+126 questa settimana</small></div>
                      <div><span>Engagement</span><strong>5,8%</strong><small>+0,6% vs periodo prec.</small></div>
                    </div>
                  </div>
                </div>
              </article>

              <article className="review-card">
                <div className="calendar-icon"><span>10</span><small>GIORNI</small></div>
                <div>
                  <p className="eyebrow">PROSSIMA REVISIONE</p>
                  <h2>Relazioni da rivedere</h2>
                  <p>18 profili non hanno ricambiato. Controlla la lista prima di qualsiasi azione.</p>
                </div>
                <button className="secondary" onClick={() => notify("Revisione aperta: 18 profili, 3 già protetti")}>Rivedi la lista <span>→</span></button>
              </article>
            </section>

            <section className="workspace-grid">
              <article className="panel opportunities">
                <div className="panel-head">
                  <div><p className="eyebrow">OPPORTUNITÀ DI OGGI</p><h2>Persone con cui interagire</h2></div>
                  <button className="text-button" onClick={() => setActive("Opportunità")}>Vedi tutte →</button>
                </div>
                <p className="muted">Suggerite in base a interazioni, affinità e qualità del pubblico.</p>
                <div className="candidate-list">
                  {visibleCandidates.map((candidate) => (
                    <div className="candidate" key={candidate.id}>
                      <span className="avatar" style={{ background: candidate.accent }}>{candidate.initials}</span>
                      <div className="candidate-copy">
                        <strong>{candidate.name}<span className="platform">{candidate.platform === "Instagram" ? "◎" : "f"}</span></strong>
                        <span>{candidate.handle}</span><small>{candidate.reason}</small>
                      </div>
                      <div className="match"><strong>{candidate.score}%</strong><span>affinità</span></div>
                      <button
                        className={protectedIds.includes(candidate.id) ? "protect selected" : "protect"}
                        aria-label="Proteggi profilo"
                        onClick={() => {
                          const isProtected = protectedIds.includes(candidate.id);
                          setProtectedIds((ids) => isProtected ? ids.filter((id) => id !== candidate.id) : [...ids, candidate.id]);
                          void persist(isProtected ? "unprotect" : "protect", candidate);
                          notify(isProtected ? "Profilo rimosso dagli intoccabili" : "Profilo aggiunto agli intoccabili");
                        }}
                      >♧</button>
                      <button className="approve" onClick={() => { setApproved([...approved, candidate.id]); void persist("approve", candidate); notify(`${candidate.name} aggiunto alla coda approvata`); }}>Approva</button>
                    </div>
                  ))}
                  {visibleCandidates.length === 0 && <div className="all-done">Tutte le opportunità di oggi sono state valutate ✓</div>}
                </div>
              </article>

              <aside className="right-stack">
                <article className="panel account-panel">
                  <div className="panel-head"><div><p className="eyebrow">PROFILI CONNESSI</p><h2>Account attivi</h2></div><button className="text-button" onClick={() => setShowConfig(true)}>Gestisci</button></div>
                  <div className="account-row"><span className="social-icon instagram">◎</span><div><strong>@marco.creative</strong><small>Instagram Business</small></div><span className="status">Connesso</span></div>
                  <div className="account-row"><span className="social-icon facebook">f</span><div><strong>Marco Creative Studio</strong><small>Pagina Facebook</small></div><span className="status">Connesso</span></div>
                </article>
                <article className="panel activity-panel">
                  <div className="panel-head"><div><p className="eyebrow">ATTIVITÀ</p><h2>Ultime 24 ore</h2></div></div>
                  <div className="activity"><span className="activity-mark green">↗</span><p><strong>+31 nuovi follower</strong><small>18 da interazioni organiche</small></p><time>2h</time></div>
                  <div className="activity"><span className="activity-mark violet">♡</span><p><strong>12 nuove opportunità</strong><small>Pronte per la revisione</small></p><time>5h</time></div>
                  <div className="activity"><span className="activity-mark amber">♧</span><p><strong>3 profili protetti</strong><small>Aggiunti agli intoccabili</small></p><time>ieri</time></div>
                </article>
              </aside>
            </section>

            <section className="strategy">
              <div><p className="eyebrow">STRATEGIA · PRIMI 30 GIORNI</p><h2>Crescita sana, un passo alla volta</h2></div>
              <div className="strategy-steps">
                <span className="step done">1<small>Connetti</small></span><i />
                <span className="step current">2<small>Ascolta</small></span><i />
                <span className="step">3<small>Interagisci</small></span><i />
                <span className="step">4<small>Misura</small></span>
              </div>
              <p>Orbit osserva per 7 giorni, individua le relazioni ad alto potenziale e propone azioni personali da approvare. Ogni 10 giorni rivede le connessioni senza mai toccare la tua whitelist.</p>
            </section>
          </>
        )}
      </section>

      {showConfig && (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.currentTarget === event.target && setShowConfig(false)}>
          <section className="modal" role="dialog" aria-modal="true" aria-labelledby="config-title">
            <button className="close" onClick={() => setShowConfig(false)} aria-label="Chiudi">×</button>
            <p className="eyebrow">CONFIGURAZIONE</p><h2 id="config-title">Connetti un profilo</h2>
            <p className="muted">La connessione avviene tramite Meta OAuth. Orbit non vede né salva la tua password.</p>
            <button className="connect instagram-button" onClick={() => notify("Flusso OAuth Instagram pronto per le credenziali Meta")}>◎ Continua con Instagram</button>
            <button className="connect facebook-button" onClick={() => notify("Flusso OAuth Facebook pronto per le credenziali Meta")}>f Continua con Facebook</button>
            <div className="safety-note"><strong>Protezione account attiva</strong><span>Nessun follow o unfollow automatico. Ogni suggerimento resta in coda finché non lo approvi.</span></div>
          </section>
        </div>
      )}
      {toast && <div className="toast" role="status">{toast}</div>}
    </main>
  );
}
