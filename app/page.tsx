"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

type Capabilities = {
  profile?: boolean;
  media?: boolean;
  comments: boolean;
  relationships: boolean;
  insights: boolean;
  reauthorizationRecommended?: boolean;
};

type SocialAccount = {
  id: string;
  platform: "instagram" | "facebook";
  displayName: string;
  username: string | null;
  followers: number | null;
  followsCount: number | null;
  mediaCount: number | null;
  syncStatus: "live" | "connected";
  connectionType?: "instagram_login" | "facebook_login";
  capabilities: Capabilities;
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
  followsYou: boolean | null;
  youFollow: boolean | null;
  verified: boolean | null;
  followerCount: number | null;
  profileUrl: string | null;
};

type MediaPerformance = {
  id: string;
  caption: string;
  mediaType: string;
  permalink: string | null;
  timestamp: string;
  likeCount: number;
  commentsCount: number;
  engagement: number;
};

type Strategy = { key: string; title: string; description: string; ready: boolean };

type Snapshot = {
  accounts: SocialAccount[];
  opportunities: Candidate[];
  recentMedia: MediaPerformance[];
  metrics: {
    connectedAccounts: number;
    knownFollowers: number;
    webhookEvents: number;
    analyzedPeople: number;
    totalInteractions: number;
    recentReach: number | null;
    recentViews: number | null;
  };
  capabilities: Capabilities;
  strategy: Strategy[];
  lastSync: string | null;
};

type ProtectedProfile = {
  external_id: string;
  display_name: string;
  platform: string;
  reason: string;
  created_at: string;
};

type QueueItem = {
  external_id: string;
  action_type: string;
  status: string;
  display_name?: string;
  platform?: string;
  score?: number;
  last_interaction?: string;
  follows_you?: number | null;
  you_follow?: number | null;
  created_at: string;
};

type AuditItem = { id: number; event_type: string; payload: string; created_at: string };

type GrowthState = {
  protectedProfiles: ProtectedProfile[];
  queue: QueueItem[];
  audit: AuditItem[];
  review: { lastRun: string | null; nextRun: string; dueInDays: number; queued: number };
};

type PlannerAction = {
  id: number;
  action_date: string;
  action_type: "follow" | "follow_back" | "comment" | "unfollow" | "lost_follower";
  probability: number;
  reason: string;
  status: "pending" | "completed" | "skipped";
  external_id: string;
  username: string;
  display_name: string;
  profile_url: string;
  source: string;
  source_detail: string | null;
  interactions: number;
  follows_you: number | null;
  you_follow: number | null;
  review_after: string | null;
  unfollowed_you_at?: string | null;
};

type PlannerState = {
  date: string;
  actions: PlannerAction[];
  settings: { follows_per_day: number; comments_per_day: number; unfollows_per_day: number; review_days: number };
  totals: { targets?: number; followers?: number; following?: number; non_followers?: number; lost_followers?: number; exchange_targets?: number };
  summary: { pending: number; completed: number; follows: number; comments: number; unfollows: number; lostFollowers: number };
  lastImport?: { followers_count: number; following_count: number; imported_at: string } | null;
  agentStatus?: { created_at: string; payload: string } | null;
  importResult?: { followers: number; following: number; compared: number } | null;
};

const nav = ["Oggi", "Opportunità", "Relazioni", "Contenuti", "Attività"];
const emptySnapshot: Snapshot = {
  accounts: [],
  opportunities: [],
  recentMedia: [],
  metrics: {
    connectedAccounts: 0,
    knownFollowers: 0,
    webhookEvents: 0,
    analyzedPeople: 0,
    totalInteractions: 0,
    recentReach: null,
    recentViews: null,
  },
  capabilities: { comments: false, relationships: false, insights: false },
  strategy: [],
  lastSync: null,
};
const emptyGrowth: GrowthState = {
  protectedProfiles: [],
  queue: [],
  audit: [],
  review: { lastRun: null, nextRun: new Date().toISOString(), dueInDays: 0, queued: 0 },
};
const emptyPlanner: PlannerState = {
  date: "",
  actions: [],
  settings: { follows_per_day: 12, comments_per_day: 10, unfollows_per_day: 8, review_days: 10 },
  totals: {},
  summary: { pending: 0, completed: 0, follows: 0, comments: 0, unfollows: 0, lostFollowers: 0 },
};

function initials(value: string) {
  return value.split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase() || "OR";
}

function formatNumber(value: number | null | undefined) {
  return value == null ? "—" : new Intl.NumberFormat("it-IT").format(value);
}

function formatDate(value: string | null | undefined) {
  if (!value) return "in attesa dei primi dati";
  return new Intl.DateTimeFormat("it-IT", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function activityLabel(type: string) {
  const labels: Record<string, string> = {
    automatic_review: "Revisione automatica creata",
    protect: "Profilo aggiunto agli intoccabili",
    unprotect: "Profilo rimosso dagli intoccabili",
    approve: "Interazione aggiunta alle priorità",
    complete: "Azione completata",
  };
  return labels[type] ?? type.replaceAll("_", " ");
}

async function usernamesFromInstagramFile(file: File) {
  const text = await file.text();
  const usernames = new Set<string>();
  const add = (value: unknown) => {
    if (typeof value !== "string") return;
    const normalized = value.trim().replace(/^@/, "").toLowerCase();
    if (/^[a-z0-9._]{1,30}$/.test(normalized)) usernames.add(normalized);
  };
  try {
    const parsed = JSON.parse(text) as unknown;
    const visit = (value: unknown) => {
      if (Array.isArray(value)) {
        value.forEach(visit);
      } else if (value && typeof value === "object") {
        const record = value as Record<string, unknown>;
        if (Array.isArray(record.string_list_data)) {
          for (const item of record.string_list_data) {
            if (item && typeof item === "object") add((item as Record<string, unknown>).value);
          }
        }
        Object.values(record).forEach(visit);
      }
    };
    visit(parsed);
  } catch {
    for (const match of text.matchAll(/instagram\.com\/([a-z0-9._]+)/gi)) add(match[1]);
    for (const token of text.split(/[\s,;]+/)) add(token.replace(/^.*\//, ""));
  }
  return [...usernames];
}

export default function Home() {
  const [active, setActive] = useState("Oggi");
  const [snapshot, setSnapshot] = useState<Snapshot>(emptySnapshot);
  const [growth, setGrowth] = useState<GrowthState>(emptyGrowth);
  const [planner, setPlanner] = useState<PlannerState>(emptyPlanner);
  const [targetUsername, setTargetUsername] = useState("");
  const [targetSource, setTargetSource] = useState("exchange_group");
  const [targetDetail, setTargetDetail] = useState("");
  const [importFollowers, setImportFollowers] = useState<string[] | null>(null);
  const [importFollowing, setImportFollowing] = useState<string[] | null>(null);
  const [showConfig, setShowConfig] = useState(false);
  const [toast, setToast] = useState("");
  const [loading, setLoading] = useState(true);
  const [syncError, setSyncError] = useState("");

  const notify = useCallback((message: string) => {
    setToast(message);
    window.setTimeout(() => setToast(""), 2800);
  }, []);

  const applyGrowthState = useCallback((state: GrowthState) => {
    setGrowth({
      protectedProfiles: state.protectedProfiles ?? [],
      queue: state.queue ?? [],
      audit: state.audit ?? [],
      review: state.review ?? emptyGrowth.review,
    });
  }, []);

  const refresh = useCallback(async (manual = false) => {
    try {
      if (manual) setLoading(true);
      const sessionResponse = await fetch("/api/meta/snapshot", { cache: "no-store" });
      const session = await sessionResponse.json() as { gatewayUrl?: string; accessToken?: string; error?: string };
      if (!sessionResponse.ok || !session.gatewayUrl || !session.accessToken) {
        throw new Error(session.error ?? "Sincronizzazione non disponibile");
      }
      const response = await fetch(session.gatewayUrl, {
        headers: { authorization: `Bearer ${session.accessToken}` },
        cache: "no-store",
      });
      const body = await response.json() as Snapshot & { error?: string };
      if (!response.ok) throw new Error(body.error ?? "Sincronizzazione non disponibile");
      setSnapshot(body);
      setSyncError("");

      const candidatePayload = body.opportunities.map((candidate) => ({
        externalId: candidate.externalId,
        username: candidate.username,
        displayName: candidate.name,
        platform: candidate.platform,
        profileUrl: candidate.profileUrl,
        interactions: candidate.interactions,
        score: candidate.score,
        lastInteraction: candidate.lastInteraction,
        followsYou: candidate.followsYou,
        youFollow: candidate.youFollow,
      }));
      const [growthResponse, plannerResponse] = await Promise.all([fetch("/api/growth", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          operation: "sync",
          candidates: body.opportunities.map((candidate) => ({
            externalId: candidate.externalId,
            displayName: candidate.name,
            platform: candidate.platform,
            score: candidate.score,
            lastInteraction: candidate.lastInteraction,
            followsYou: candidate.followsYou,
            youFollow: candidate.youFollow,
          })),
        }),
      }), fetch("/api/planner", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ operation: "sync", candidates: candidatePayload }),
      })]);
      if (growthResponse.ok) applyGrowthState(await growthResponse.json() as GrowthState);
      if (plannerResponse.ok) setPlanner(await plannerResponse.json() as PlannerState);
      if (manual) notify("Piano operativo di oggi aggiornato");
    } catch (error) {
      setSyncError(error instanceof Error ? error.message : "Sincronizzazione non disponibile");
    } finally {
      setLoading(false);
    }
  }, [applyGrowthState, notify]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5 * 60_000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("instagram") === "connected" || params.get("meta") === "connected") {
      notify("Profilo collegato. Analisi automatica avviata.");
      window.history.replaceState({}, "", window.location.pathname);
      void refresh();
    }
    if (params.get("instagram") === "connection-failed") {
      notify("Il collegamento Instagram non è stato completato.");
      window.history.replaceState({}, "", window.location.pathname);
    }
  }, [notify, refresh]);

  const plannerRequest = async (payload: Record<string, unknown>, successMessage?: string) => {
    try {
      const response = await fetch("/api/planner", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload),
      });
      const result = await response.json() as PlannerState & { error?: string };
      if (!response.ok) throw new Error(result.error ?? "Operazione non riuscita");
      setPlanner(result);
      if (successMessage) notify(successMessage);
      return true;
    } catch (error) {
      notify(error instanceof Error ? error.message : "Operazione non riuscita");
      return false;
    }
  };

  const addManualTarget = async () => {
    const ok = await plannerRequest({
      operation: "add_target",
      username: targetUsername,
      source: targetSource,
      sourceDetail: targetDetail || null,
    }, "Target aggiunto al motore giornaliero");
    if (ok) {
      setTargetUsername("");
      setTargetDetail("");
    }
  };

  const importInstagramRelations = async () => {
    if (!importFollowers || !importFollowing) {
      notify("Seleziona sia il file Follower sia il file Seguiti");
      return;
    }
    const ok = await plannerRequest({
      operation: "import_relations",
      followers: importFollowers,
      following: importFollowing,
    }, `Confronto completato: ${importFollowers.length} follower e ${importFollowing.length} seguiti`);
    if (ok) setActive("Oggi");
  };

  const protectedIds = useMemo(
    () => new Set(growth.protectedProfiles.map((profile) => profile.external_id)),
    [growth.protectedProfiles],
  );
  const approvedIds = useMemo(
    () => new Set(growth.queue.filter((item) => item.action_type === "priority_interaction" && item.status === "approved").map((item) => item.external_id)),
    [growth.queue],
  );
  const visibleCandidates = snapshot.opportunities.filter((candidate) => !approvedIds.has(candidate.externalId));
  const growthScore = useMemo(() => {
    if (!snapshot.accounts.length) return 0;
    const live = snapshot.accounts.some((account) => account.syncStatus === "live") ? 20 : 8;
    const people = Math.min(30, snapshot.metrics.analyzedPeople * 3);
    const content = Math.min(20, snapshot.recentMedia.length * 2);
    const signals = Math.min(20, Math.round(Math.log10(snapshot.metrics.totalInteractions + 1) * 8));
    return Math.min(100, 10 + live + people + content + signals);
  }, [snapshot]);

  const persist = async (operation: "protect" | "unprotect" | "approve" | "complete", candidate: Candidate | QueueItem) => {
    const externalId = "externalId" in candidate ? candidate.externalId : candidate.external_id;
    const displayName = "name" in candidate ? candidate.name : candidate.display_name ?? externalId;
    const platform = "platform" in candidate ? candidate.platform : candidate.platform ?? "Instagram";
    try {
      const response = await fetch("/api/growth", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ operation, externalId, displayName, platform }),
      });
      if (!response.ok) throw new Error("Salvataggio non riuscito");
      applyGrowthState(await response.json() as GrowthState);
    } catch {
      notify("Azione non salvata: riprova tra poco");
    }
  };

  const strategies = snapshot.strategy.length ? snapshot.strategy : [
    { key: "reciprocity", title: "Reciprocità selettiva", description: "In attesa dei primi segnali Instagram.", ready: false },
    { key: "recency", title: "Finestra di recenza", description: "In attesa dei primi segnali Instagram.", ready: false },
    { key: "consistency", title: "Continuità editoriale", description: "In attesa dei primi contenuti.", ready: false },
  ];

  const pendingActions = planner.actions.filter((action) => action.status === "pending");
  const dailyActionPanel = (
    title: string,
    eyebrow: string,
    actionTypes: PlannerAction["action_type"][],
    emptyMessage: string,
  ) => {
    const actions = pendingActions.filter((action) => actionTypes.includes(action.action_type));
    return (
      <article className="panel daily-action-panel">
        <div className="panel-head"><div><p className="eyebrow">{eyebrow}</p><h2>{title}</h2></div><span className="daily-count">{actions.length}</span></div>
        {!actions.length && <div className="daily-empty">{emptyMessage}</div>}
        {actions.map((action) => (
          <div className="daily-action" key={action.id}>
            <div className="daily-person">
              <span className="avatar mini">{initials(action.display_name || action.username)}</span>
              <div><strong>@{action.username}</strong><small>{action.reason}</small></div>
            </div>
            <div className="probability"><strong>{action.action_type === "lost_follower" ? "Rilevato" : `${action.probability}%`}</strong><span>{action.action_type === "lost_follower" ? formatDate(action.unfollowed_you_at) : "reciprocità stimata"}</span></div>
            <div className="daily-buttons">
              <a href={action.profile_url} target="_blank" rel="noreferrer">Apri profilo</a>
              <button onClick={() => void plannerRequest({ operation: "complete", actionId: action.id }, action.action_type === "lost_follower" ? "Segnalazione archiviata" : "Azione completata")}>{action.action_type === "lost_follower" ? "Archivia" : "Fatto"}</button>
              <button className="skip" onClick={() => void plannerRequest({ operation: "skip", actionId: action.id })}>Salta</button>
            </div>
          </div>
        ))}
      </article>
    );
  };

  const candidatePanel = (
    <article className="panel opportunities">
      <div className="panel-head">
        <div><p className="eyebrow">PRIORITÀ AUTOMATICHE</p><h2>Persone con cui interagire</h2></div>
        <span className="live-pill">● LIVE</span>
      </div>
      <p className="muted">Ranking calcolato da frequenza, recenza, commenti e relazione reciproca.</p>
      <div className="candidate-list">
        {loading && !snapshot.opportunities.length && <div className="all-done">Sto leggendo profilo, contenuti e commenti…</div>}
        {!loading && !visibleCandidates.length && (
          <div className="all-done">
            {snapshot.accounts.length
              ? "Profilo connesso. Ricollegalo con i permessi estesi oppure attendi i primi commenti sui contenuti."
              : "Collega Instagram professionale per iniziare."}
          </div>
        )}
        {visibleCandidates.map((candidate, index) => (
          <div className="candidate" key={`${candidate.platform}-${candidate.externalId}`}>
            <span className="avatar" style={{ background: ["#ffb1bf", "#ffd989", "#b7d8ff", "#bde8d0"][index % 4] }}>{initials(candidate.name)}</span>
            <div className="candidate-copy">
              <strong>
                {candidate.profileUrl
                  ? <a href={candidate.profileUrl} target="_blank" rel="noreferrer">{candidate.name}</a>
                  : candidate.name}
                <span className="platform">{candidate.platform === "Instagram" ? "◎" : "f"}</span>
              </strong>
              <span>{candidate.username ? `@${candidate.username.replace(/^@/, "")}` : candidate.platform}</span>
              <small>{candidate.reason} · ultima {formatDate(candidate.lastInteraction)}</small>
            </div>
            <div className="match"><strong>{candidate.score}%</strong><span>priorità</span></div>
            <button
              className={protectedIds.has(candidate.externalId) ? "protect selected" : "protect"}
              aria-label={protectedIds.has(candidate.externalId) ? "Rimuovi dagli intoccabili" : "Aggiungi agli intoccabili"}
              onClick={() => {
                const isProtected = protectedIds.has(candidate.externalId);
                void persist(isProtected ? "unprotect" : "protect", candidate);
                notify(isProtected ? "Profilo rimosso dagli intoccabili" : "Profilo aggiunto agli intoccabili");
              }}
            >♧</button>
            <button className="approve" onClick={() => {
              void persist("approve", candidate);
              notify(`${candidate.name} aggiunto alla coda prioritaria`);
            }}>Priorità</button>
          </div>
        ))}
      </div>
    </article>
  );

  const accountPanel = (
    <article className="panel account-panel">
      <div className="panel-head"><div><p className="eyebrow">PROFILI CONNESSI</p><h2>Account reali</h2></div><button className="text-button" onClick={() => setShowConfig(true)}>Gestisci</button></div>
      {!snapshot.accounts.length && !loading && <p className="account-empty">Nessun account ricevuto dal gateway.</p>}
      {snapshot.accounts.map((account) => (
        <div className="account-row" key={`${account.platform}-${account.id}`}>
          <span className={`social-icon ${account.platform}`}>{account.platform === "instagram" ? "◎" : "f"}</span>
          <div>
            <strong>{account.username ? `@${account.username.replace(/^@/, "")}` : account.displayName}</strong>
            <small>{account.platform === "instagram" ? "Instagram Creator diretto" : "Pagina Facebook"}{account.followers !== null ? ` · ${formatNumber(account.followers)} follower` : ""}</small>
          </div>
          <span className={account.syncStatus === "live" ? "status live" : "status"}>{account.syncStatus === "live" ? "Live" : "Connesso"}</span>
        </div>
      ))}
    </article>
  );

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark">O</span><span>Orbit</span></div>
        <nav aria-label="Navigazione principale">
          {nav.map((item, index) => (
            <button key={item} className={active === item ? "nav-item active" : "nav-item"} onClick={() => setActive(item)}>
              <span className="nav-icon">{["✓", "✦", "♧", "▧", "↗"][index]}</span>{item}
              {item === "Oggi" && planner.summary.pending > 0 && <span className="badge">{planner.summary.pending}</span>}
              {item === "Opportunità" && snapshot.metrics.analyzedPeople > 0 && <span className="badge">{snapshot.metrics.analyzedPeople}</span>}
              {item === "Relazioni" && growth.review.queued > 0 && <span className="badge">{growth.review.queued}</span>}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <button className="nav-item" onClick={() => setShowConfig(true)}><span className="nav-icon">⚙</span>Impostazioni</button>
          <div className="profile"><span className="avatar mini">MM</span><div><strong>Marco M.</strong><small>Amministratore</small></div><span className="more">•••</span></div>
        </div>
      </aside>

      <section className="content">
        <header className="topbar">
          <div>
            <p className="eyebrow">CONTROLLO CRESCITA META</p>
            <h1>{active === "Oggi" ? "Azioni da fare oggi" : active}</h1>
            <p className="sync-copy">{loading ? "Sincronizzazione…" : `Ultimo aggiornamento: ${formatDate(snapshot.lastSync)}`}{syncError && <span className="sync-error"> · {syncError}</span>}</p>
          </div>
          <div className="top-actions">
            <button className="icon-button refresh-button" aria-label="Aggiorna dati" onClick={() => void refresh(true)}>↻</button>
            <button className="primary" onClick={() => setShowConfig(true)}>＋ Connetti profilo</button>
          </div>
        </header>

        {snapshot.capabilities.reauthorizationRecommended && snapshot.accounts.length > 0 && (
          <section className="permission-banner">
            <div><strong>Completa l’automazione Instagram</strong><span>Il login attuale è valido, ma va rinnovato una volta per autorizzare commenti, insight, messaggi e pubblicazione.</span></div>
            <a href="/api/instagram/connect">Rinnova permessi</a>
          </section>
        )}

        {active === "Oggi" && (
          <>
            <section className="daily-hero">
              <div>
                <p className="eyebrow">PIANO OPERATIVO · {planner.date || "OGGI"}</p>
                <h2>{planner.summary.pending} azioni rimaste</h2>
                <p>Segui l’ordine proposto: prima profili ad alta reciprocità, poi conversazioni calde, infine scrematura.</p>
              </div>
              <div className="daily-progress">
                <strong>{planner.summary.completed}</strong><span>completate</span>
                <div><i style={{ width: `${planner.actions.length ? Math.round(planner.summary.completed / planner.actions.length * 100) : 0}%` }} /></div>
              </div>
              <div className="daily-summary">
                <span><strong>{planner.summary.follows}</strong> follow</span>
                <span><strong>{planner.summary.comments}</strong> commenti</span>
                <span><strong>{planner.summary.unfollows}</strong> defollow</span>
                <span><strong>{planner.summary.lostFollowers}</strong> ti hanno defollowato</span>
              </div>
            </section>

            <section className="daily-grid">
              {dailyActionPanel("Chi seguire", "FOLLOW STRATEGICI", ["follow", "follow_back"], "Aggiungi target o importa le liste Instagram per creare i follow di oggi.")}
              {dailyActionPanel("Chi commentare", "CONVERSAZIONI CALDE", ["comment"], "I profili compariranno quando commentano o interagiscono con i tuoi contenuti.")}
              {dailyActionPanel("Chi defolloware", "SCREMATURA PROTETTA", ["unfollow"], "Importa Follower e Seguiti: Orbit escluderà gli intoccabili e proporrà solo i non reciproci.")}
              {dailyActionPanel("Chi ti ha defollowato", "CONTROLLO PERDITE", ["lost_follower"], planner.lastImport ? "Nessun nuovo defollow rilevato rispetto al confronto precedente." : "Importa oggi le liste; dal confronto successivo Orbit rileverà ogni follower perso, anche se non lo segui.")}
            </section>

            <section className="today-footer-grid">
              <article className="panel routine-panel">
                <p className="eyebrow">STRATEGIA QUOTIDIANA</p><h2>Routine di crescita</h2>
                <div className="routine-step"><span>1</span><div><strong>Follow selettivo</strong><small>Apri il profilo, verifica affinità e attività recente, poi segui soltanto target coerenti.</small></div></div>
                <div className="routine-step"><span>2</span><div><strong>Commento specifico</strong><small>Evita emoji generiche: cita un dettaglio del contenuto e aggiungi un punto di vista.</small></div></div>
                <div className="routine-step"><span>3</span><div><strong>Reciprocità entro 10 giorni</strong><small>Il follow completato entra automaticamente nella finestra di revisione.</small></div></div>
              </article>
              <article className="panel relation-snapshot">
                <p className="eyebrow">BASE RELAZIONI</p><h2>Dati per decidere</h2>
                <div className="relation-number"><span>Target caricati</span><strong>{formatNumber(planner.totals.targets)}</strong></div>
                <div className="relation-number"><span>Non ricambiano</span><strong>{formatNumber(planner.totals.non_followers)}</strong></div>
                <div className="relation-number"><span>Defollow rilevati</span><strong>{formatNumber(planner.totals.lost_followers)}</strong></div>
                <div className="relation-number"><span>Da gruppi di scambio</span><strong>{formatNumber(planner.totals.exchange_targets)}</strong></div>
                <button className="primary" onClick={() => setActive("Relazioni")}>Importa o aggiungi target</button>
              </article>
            </section>
          </>
        )}

        {active === "Panoramica" && (
          <>
            <section className="hero-grid">
              <article className="growth-card">
                <div className="section-heading"><div><p className="eyebrow">GROWTH SCORE LIVE</p><h2>{snapshot.accounts.length ? "Il motore di analisi è attivo" : "Collega il primo profilo"}</h2></div><span className="trend">{snapshot.metrics.connectedAccounts} account</span></div>
                <div className="score-row">
                  <div className="score-ring" style={{ background: `conic-gradient(#3b8e70 0 ${growthScore}%,#e7eeeb ${growthScore}%)` }}><div><strong>{growthScore}</strong><span>/100</span></div></div>
                  <div className="score-copy">
                    <p>Orbit aggiorna automaticamente dati, contenuti e ranking. Il punteggio cresce quando aumenta la qualità dei segnali reali.</p>
                    <div className="mini-stats">
                      <div><span>Follower rilevati</span><strong>{formatNumber(snapshot.metrics.knownFollowers)}</strong><small>dato live Instagram</small></div>
                      <div><span>Persone analizzate</span><strong>{snapshot.metrics.analyzedPeople}</strong><small>commenti e messaggi</small></div>
                      <div><span>Interazioni contenuti</span><strong>{formatNumber(snapshot.metrics.totalInteractions)}</strong><small>like + commenti</small></div>
                    </div>
                  </div>
                </div>
              </article>
              <article className="review-card">
                <div className="calendar-icon"><span>{growth.review.dueInDays}</span><small>GIORNI</small></div>
                <div><p className="eyebrow">REVISIONE RELAZIONI</p><h2>Scrematura protetta</h2><p>La revisione si rigenera ogni 10 giorni ed esclude sempre gli account intoccabili.</p></div>
                <button className="secondary" onClick={() => setActive("Relazioni")}>Apri la revisione <span>→</span></button>
              </article>
            </section>
            <section className="workspace-grid">
              {candidatePanel}
              <aside className="right-stack">
                {accountPanel}
                <article className="panel activity-panel">
                  <div className="panel-head"><div><p className="eyebrow">MOTORE AUTOMATICO</p><h2>Stato operativo</h2></div></div>
                  <div className="activity"><span className="activity-mark green">↻</span><p><strong>Sincronizzazione attiva</strong><small>Aggiornamento ogni 5 minuti</small></p><time>live</time></div>
                  <div className="activity"><span className="activity-mark violet">✦</span><p><strong>Ranking interazioni</strong><small>Recenza, frequenza e reciprocità</small></p><time>{snapshot.metrics.analyzedPeople}</time></div>
                  <div className="activity"><span className="activity-mark amber">♧</span><p><strong>Lista intoccabili</strong><small>Esclusa da ogni revisione</small></p><time>{growth.protectedProfiles.length}</time></div>
                </article>
              </aside>
            </section>
            <section className="strategy strategy-live">
              <div><p className="eyebrow">STRATEGIA COMPORTAMENTALE</p><h2>Relazioni che convertono</h2></div>
              <div className="strategy-cards">{strategies.map((item, index) => <div className={item.ready ? "strategy-item ready" : "strategy-item"} key={item.key}><span>{index + 1}</span><p><strong>{item.title}</strong><small>{item.description}</small></p></div>)}</div>
              <p>Orbit privilegia chi mostra interesse reale e trasforma i segnali in una lista operativa. Le API Meta non consentono follow, unfollow o like automatici: queste azioni restano guidate per proteggere l’account.</p>
            </section>
          </>
        )}

        {active === "Opportunità" && <section className="workspace-grid opportunities-focus">{candidatePanel}<aside className="right-stack">{accountPanel}</aside></section>}

        {active === "Relazioni" && (
          <section className="module-grid">
            <article className="panel review-queue">
              <div className="panel-head"><div><p className="eyebrow">REVISIONE OGNI 10 GIORNI</p><h2>Coda relazioni</h2></div><span className="trend">{growth.review.queued} azioni</span></div>
              <p className="muted">Orbit crea automaticamente la coda e rimuove gli intoccabili. Tu confermi l’azione sul profilo Instagram.</p>
              {!growth.queue.length && <div className="all-done">Nessuna relazione da revisionare in questo momento.</div>}
              {growth.queue.slice(0, 30).map((item) => (
                <div className="queue-row" key={`${item.action_type}-${item.external_id}-${item.created_at}`}>
                  <span className="avatar">{initials(item.display_name ?? item.external_id)}</span>
                  <div><strong>{item.display_name ?? item.external_id}</strong><small>{item.action_type === "priority_interaction" ? "Interazione prioritaria" : "Revisione relazione"} · punteggio {item.score ?? 0}</small></div>
                  <button className="secondary" onClick={() => void persist("complete", item)}>Completa</button>
                </div>
              ))}
            </article>
            <article className="panel protected-panel">
              <div className="panel-head"><div><p className="eyebrow">SEMPRE ESCLUSI</p><h2>Intoccabili</h2></div><span className="live-pill">{growth.protectedProfiles.length}</span></div>
              {!growth.protectedProfiles.length && <p className="account-empty">Premi ♧ accanto a una persona per proteggerla.</p>}
              {growth.protectedProfiles.map((profile) => (
                <div className="protected-row" key={profile.external_id}><span className="avatar mini">{initials(profile.display_name)}</span><div><strong>{profile.display_name}</strong><small>{profile.platform} · dal {formatDate(profile.created_at)}</small></div><button className="text-button" onClick={() => void persist("unprotect", { external_id: profile.external_id, display_name: profile.display_name, platform: profile.platform, action_type: "", status: "", created_at: profile.created_at })}>Rimuovi</button></div>
              ))}
            </article>
            <article className="panel agent-panel">
              <p className="eyebrow">AGENTE OPEN SOURCE</p><h2>Sincronizzazione automatica</h2>
              <p className="muted">Il connettore locale gratuito scarica follower e seguiti, elimina chi già segui e prepara candidati da audience affini ogni 6 ore.</p>
              <div className={planner.agentStatus ? "agent-state active" : "agent-state"}>
                <span>{planner.agentStatus ? "● ATTIVO" : "○ DA ATTIVARE"}</span>
                <strong>{planner.agentStatus ? `Ultimo invio ${formatDate(planner.agentStatus.created_at)}` : "Esegui una volta agent/setup.ps1 sul PC"}</strong>
              </div>
              <small className="agent-note">Password e sessione restano nel Gestore credenziali Windows; Orbit riceve soltanto dati di relazione e punteggi.</small>
            </article>
            <article className="panel import-panel">
              <p className="eyebrow">FALLBACK MANUALE</p><h2>Importa Follower e Seguiti</h2>
              <p className="muted">Usa questi file solo se l’agente locale richiede una nuova verifica Instagram.</p>
              {planner.lastImport && <p className="last-import">Ultimo confronto: {formatDate(planner.lastImport.imported_at)} · {formatNumber(planner.lastImport.followers_count)} follower · {formatNumber(planner.lastImport.following_count)} seguiti</p>}
              <div className="file-import-grid">
                <label className={importFollowers ? "file-box ready" : "file-box"}>
                  <strong>{importFollowers ? `${importFollowers.length} follower letti` : "File Follower"}</strong>
                  <span>{importFollowers ? "Pronto" : "Seleziona followers_1.json"}</span>
                  <input type="file" accept=".json,.csv,.txt,.html" onChange={(event) => {
                    const file = event.target.files?.[0];
                    if (file) void usernamesFromInstagramFile(file).then(setImportFollowers);
                  }} />
                </label>
                <label className={importFollowing ? "file-box ready" : "file-box"}>
                  <strong>{importFollowing ? `${importFollowing.length} seguiti letti` : "File Seguiti"}</strong>
                  <span>{importFollowing ? "Pronto" : "Seleziona following.json"}</span>
                  <input type="file" accept=".json,.csv,.txt,.html" onChange={(event) => {
                    const file = event.target.files?.[0];
                    if (file) void usernamesFromInstagramFile(file).then(setImportFollowing);
                  }} />
                </label>
              </div>
              <button className="primary import-button" disabled={!importFollowers || !importFollowing} onClick={() => void importInstagramRelations()}>Confronta e genera il piano</button>
            </article>
            <article className="panel target-panel">
              <p className="eyebrow">SORGENTI STRATEGICHE</p><h2>Aggiungi target</h2>
              <p className="muted">Inserisci persone trovate in gruppi di scambio, audience affini o ricerche manuali.</p>
              <div className="target-form">
                <label><span>Username Instagram</span><input value={targetUsername} onChange={(event) => setTargetUsername(event.target.value)} placeholder="@username" /></label>
                <label><span>Origine</span><select value={targetSource} onChange={(event) => setTargetSource(event.target.value)}><option value="exchange_group">Gruppo scambio follow</option><option value="competitor_audience">Audience affine</option><option value="manual">Ricerca manuale</option></select></label>
                <label className="wide"><span>Gruppo o nota</span><input value={targetDetail} onChange={(event) => setTargetDetail(event.target.value)} placeholder="Nome gruppo, tema o motivo" /></label>
                <button className="primary wide" disabled={!targetUsername.trim()} onClick={() => void addManualTarget()}>Aggiungi alle azioni giornaliere</button>
              </div>
            </article>
          </section>
        )}

        {active === "Contenuti" && (
          <section className="module-grid content-module">
            <article className="panel media-panel">
              <div className="panel-head"><div><p className="eyebrow">PERFORMANCE REALI</p><h2>Contenuti da replicare</h2></div><span className="trend">{snapshot.recentMedia.length} analizzati</span></div>
              <p className="muted">Ordinati per like + commenti ponderati. I commenti valgono di più perché indicano coinvolgimento attivo.</p>
              {!snapshot.recentMedia.length && <div className="all-done">Rinnova i permessi Instagram per analizzare i contenuti.</div>}
              {snapshot.recentMedia.slice(0, 12).map((media, index) => (
                <div className="media-row" key={media.id}><span className="rank-number">{index + 1}</span><div><strong>{media.caption}</strong><small>{media.mediaType} · {formatDate(media.timestamp)}</small></div><div className="media-stats"><span>♥ {formatNumber(media.likeCount)}</span><span>● {formatNumber(media.commentsCount)}</span></div>{media.permalink && <a href={media.permalink} target="_blank" rel="noreferrer">Apri</a>}</div>
              ))}
            </article>
            <article className="panel playbook-panel">
              <p className="eyebrow">PIANO DI CRESCITA</p><h2>Schema editoriale</h2>
              <div className="playbook-step"><span>1</span><div><strong>Hook riconoscibile</strong><small>Apri con un problema specifico o un risultato concreto, senza promesse vaghe.</small></div></div>
              <div className="playbook-step"><span>2</span><div><strong>Serie ricorrente</strong><small>Trasforma il formato migliore in un appuntamento riconoscibile.</small></div></div>
              <div className="playbook-step"><span>3</span><div><strong>CTA conversazionale</strong><small>Chiudi con una domanda facile e pertinente per aumentare commenti autentici.</small></div></div>
              <div className="playbook-step"><span>4</span><div><strong>Risposta rapida</strong><small>Rispondi entro 24 ore e privilegia chi torna più volte.</small></div></div>
            </article>
          </section>
        )}

        {active === "Attività" && (
          <section className="module-grid">
            <article className="panel audit-panel">
              <div className="panel-head"><div><p className="eyebrow">REGISTRO AUTOMATICO</p><h2>Attività recenti</h2></div></div>
              {!growth.audit.length && <div className="all-done">Le prossime azioni compariranno qui.</div>}
              {growth.audit.map((item) => <div className="audit-row" key={item.id}><span className="activity-mark green">✓</span><div><strong>{activityLabel(item.event_type)}</strong><small>{formatDate(item.created_at)}</small></div></div>)}
            </article>
            <article className="panel capability-panel">
              <p className="eyebrow">COPERTURA API</p><h2>Dati disponibili</h2>
              <div className="capability-row"><span>Profilo e follower</span><strong className={snapshot.accounts.some((account) => account.capabilities.profile) ? "ok" : "wait"}>{snapshot.accounts.some((account) => account.capabilities.profile) ? "Attivo" : "In attesa"}</strong></div>
              <div className="capability-row"><span>Contenuti recenti</span><strong className={snapshot.accounts.some((account) => account.capabilities.media) ? "ok" : "wait"}>{snapshot.accounts.some((account) => account.capabilities.media) ? "Attivo" : "Rinnova"}</strong></div>
              <div className="capability-row"><span>Commenti e ranking</span><strong className={snapshot.capabilities.comments ? "ok" : "wait"}>{snapshot.capabilities.comments ? "Attivo" : "Rinnova"}</strong></div>
              <div className="capability-row"><span>Insight account</span><strong className={snapshot.capabilities.insights ? "ok" : "wait"}>{snapshot.capabilities.insights ? "Attivo" : "Rinnova"}</strong></div>
            </article>
          </section>
        )}
      </section>

      {showConfig && (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.currentTarget === event.target && setShowConfig(false)}>
          <section className="modal" role="dialog" aria-modal="true" aria-labelledby="config-title">
            <button className="close" onClick={() => setShowConfig(false)} aria-label="Chiudi">×</button>
            <p className="eyebrow">CONFIGURAZIONE</p><h2 id="config-title">Connetti o rinnova i profili</h2>
            <p className="muted">Ricollega Instagram una volta per autorizzare commenti, insight, messaggi e pubblicazione. Orbit non vede né salva la password.</p>
            <a className="connect instagram-button" href="/api/instagram/connect">◎ Connetti / rinnova Instagram Creator</a>
            <a className="connect facebook-button" href="/api/meta/connect">f Connetti Pagine Facebook</a>
            <div className="planner-settings">
              <strong>Quote giornaliere</strong>
              <div>
                <label><span>Follow</span><input type="number" min="1" max="30" value={planner.settings.follows_per_day} onChange={(event) => setPlanner((current) => ({ ...current, settings: { ...current.settings, follows_per_day: Number(event.target.value) } }))} /></label>
                <label><span>Commenti</span><input type="number" min="1" max="30" value={planner.settings.comments_per_day} onChange={(event) => setPlanner((current) => ({ ...current, settings: { ...current.settings, comments_per_day: Number(event.target.value) } }))} /></label>
                <label><span>Defollow</span><input type="number" min="1" max="30" value={planner.settings.unfollows_per_day} onChange={(event) => setPlanner((current) => ({ ...current, settings: { ...current.settings, unfollows_per_day: Number(event.target.value) } }))} /></label>
                <label><span>Revisione</span><input type="number" min="1" max="30" value={planner.settings.review_days} onChange={(event) => setPlanner((current) => ({ ...current, settings: { ...current.settings, review_days: Number(event.target.value) } }))} /></label>
              </div>
              <button className="secondary" onClick={() => void plannerRequest({ operation: "settings", settings: { followsPerDay: planner.settings.follows_per_day, commentsPerDay: planner.settings.comments_per_day, unfollowsPerDay: planner.settings.unfollows_per_day, reviewDays: planner.settings.review_days } }, "Quote giornaliere salvate")}>Salva quote</button>
            </div>
            <div className="safety-note"><strong>Automazione conforme</strong><span>Analisi, ranking, revisione e priorità sono automatici. Follow, unfollow e like personali non sono disponibili nelle API ufficiali e restano azioni guidate.</span></div>
          </section>
        </div>
      )}
      {toast && <div className="toast" role="status">{toast}</div>}
    </main>
  );
}
