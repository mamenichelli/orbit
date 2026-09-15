"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

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

type LikeHistory = {
  accountUsername: string; page: number; pageSize: number; total: number; applied: number; manualOnline: boolean;
  events: { eventId: string; shortcode: string; status: "applied" | "already_liked" | "legacy" | "discovered";
    likedAt: string | null; observedAt: string; groups: { title: string; threadPath: string }[]; metadata?: { authorUsername?: string; publishedAt?: string | null } }[];
};

function likeDate(value: string) {
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? new Intl.DateTimeFormat("it-IT", {
    dateStyle: "short", timeStyle: "medium", timeZone: "Europe/Rome",
  }).format(date) : "Orario non disponibile";
}

type GrowthState = {
  protectedProfiles: ProtectedProfile[];
  queue: QueueItem[];
  audit: AuditItem[];
  review: { lastRun: string | null; nextRun: string; dueInDays: number; queued: number };
};

type PlannerAction = {
  id: number;
  action_date: string;
  action_type: "follow" | "follow_back" | "unfollow" | "lost_follower";
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
  follower_count?: number | null;
  following_count?: number | null;
  media_count?: number | null;
  is_private?: number | null;
  last_post_at?: string | null;
  activity_score?: number | null;
  italian_signal?: number | null;
  female_self_declared?: number | null;
};

type PlannerState = {
  date: string;
  actions: PlannerAction[];
  settings: { follows_per_day: number; comments_per_day: number; unfollows_per_day: number; review_days: number };
  totals: { targets?: number; followers?: number; following?: number; non_followers?: number; lost_followers?: number; exchange_targets?: number };
  summary: { pending: number; completed: number; follows: number; unfollows: number; lostFollowers: number };
  lastImport?: { followers_count: number; following_count: number; imported_at: string } | null;
  agentStatus?: { created_at: string; payload: string } | null;
  importResult?: { followers: number; following: number; compared: number } | null;
};

const nav = ["Oggi", "Opportunità", "Relazioni", "Attività"];
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
  settings: { follows_per_day: 20, comments_per_day: 0, unfollows_per_day: 1000, review_days: 10 },
  totals: {},
  summary: { pending: 0, completed: 0, follows: 0, unfollows: 0, lostFollowers: 0 },
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

function snapshotWithPlannerFallback(current: Snapshot, planner: PlannerState): Snapshot {
  let agentPayload: Record<string, unknown> = {};
  try {
    agentPayload = planner.agentStatus?.payload
      ? JSON.parse(planner.agentStatus.payload) as Record<string, unknown>
      : {};
  } catch {
    agentPayload = {};
  }
  const followers = Number(planner.totals.followers ?? planner.lastImport?.followers_count ?? agentPayload.followers ?? 0);
  const following = Number(planner.totals.following ?? planner.lastImport?.following_count ?? agentPayload.following ?? 0);
  const username = typeof agentPayload.username === "string" ? agentPayload.username : null;
  const localAccount: SocialAccount | null = planner.agentStatus || planner.lastImport ? {
    id: "local-instagram-agent",
    platform: "instagram",
    displayName: username ? `@${username.replace(/^@/, "")}` : "Instagram",
    username,
    followers,
    followsCount: following,
    mediaCount: null,
    syncStatus: "live",
    capabilities: { profile: true, comments: false, relationships: true, insights: false },
    updatedAt: planner.agentStatus?.created_at ?? planner.lastImport?.imported_at ?? new Date().toISOString(),
  } : null;
  return {
    ...current,
    accounts: current.accounts.length ? current.accounts : localAccount ? [localAccount] : [],
    metrics: {
      ...current.metrics,
      connectedAccounts: Math.max(current.metrics.connectedAccounts, localAccount ? 1 : 0),
      knownFollowers: Math.max(current.metrics.knownFollowers, followers),
      analyzedPeople: Math.max(current.metrics.analyzedPeople, Number(planner.totals.targets ?? 0)),
    },
    capabilities: localAccount && !current.accounts.length
      ? { ...current.capabilities, profile: true, relationships: true }
      : current.capabilities,
    lastSync: current.lastSync ?? planner.agentStatus?.created_at ?? planner.lastImport?.imported_at ?? null,
  };
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

const LIST_PAGE_SIZE = 20;

export default function Home() {
  const [active, setActive] = useState("Oggi");
  const [snapshot, setSnapshot] = useState<Snapshot>(emptySnapshot);
  const [growth, setGrowth] = useState<GrowthState>(emptyGrowth);
  const [planner, setPlanner] = useState<PlannerState>(emptyPlanner);
  const [targetUsername, setTargetUsername] = useState("");
  const [targetSource, setTargetSource] = useState("exchange_group");
  const [targetDetail, setTargetDetail] = useState("");
  const [protectedInput, setProtectedInput] = useState("");
  const [importFollowers, setImportFollowers] = useState<string[] | null>(null);
  const [importFollowing, setImportFollowing] = useState<string[] | null>(null);
  const [showConfig, setShowConfig] = useState(false);
  const [toast, setToast] = useState("");
  const [loading, setLoading] = useState(true);
  const [syncError, setSyncError] = useState("");
  const [hiddenActionIds, setHiddenActionIds] = useState<Set<number>>(() => new Set());
  const [listPages, setListPages] = useState<Record<string, number>>({});
  const [likePage, setLikePage] = useState(1);
  const [likeHistory, setLikeHistory] = useState<LikeHistory | null>(null);
  const [likeHistoryError, setLikeHistoryError] = useState("");
  const [manualLikes, setManualLikes] = useState<Record<string, { id: string; startedAt: number }>>({});
  const manualRequests = useRef<Record<string, { id: string; startedAt: number }>>({});
  const [manualMessage, setManualMessage] = useState("");
  const [collectionMessage,setCollectionMessage]=useState('');
  const likePageRef=useRef(likePage);
  useEffect(()=>{likePageRef.current=likePage;},[likePage]);
  const hiddenPosts = useRef(new Set<string>());
  const skipPost = async (shortcode: string) => {
    if (manualRequests.current[shortcode] || hiddenPosts.current.has(shortcode)) return;
    const previous = likeHistory?.events.find(event => event.shortcode === shortcode);
    hiddenPosts.current.add(shortcode);
    setLikeHistory(current => current ? { ...current, total: Math.max(0, current.total - 1), events: current.events.filter(event => event.shortcode !== shortcode) } : current);
    try {
      const response = await fetch("/api/instagram/skip-post", { method: "POST", headers: { "content-type": "application/json", "x-orbit-manual": "1" }, body: JSON.stringify({ shortcode }) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error ?? "Skip non salvato");
    } catch (error) {
      hiddenPosts.current.delete(shortcode);
      setLikeHistory(current => current ? { ...current, total: current.total + 1, events: previous && !current.events.some(event => event.shortcode === shortcode) ? [previous, ...current.events].slice(0, 20) : current.events } : current);
      setManualMessage(error instanceof Error ? error.message : "Skip non salvato: riprova");
    }
  };

  const requestManualLike = async (shortcode: string) => {
    if (manualRequests.current[shortcode] || hiddenPosts.current.has(shortcode)) return;
    const id = crypto.randomUUID();
    manualRequests.current[shortcode] = { id, startedAt: Date.now() };
    setManualLikes({ ...manualRequests.current }); setManualMessage("");
    try {
      const response = await fetch("/api/instagram/manual-like", { method: "POST", headers: { "content-type": "application/json", "x-orbit-manual": "1" }, body: JSON.stringify({ id, shortcode }) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error ?? "Like non richiesto");
    } catch (error) {
      setManualMessage(error instanceof Error ? error.message : "Richiesta non confermata: controlla prima di riprovare");
      delete manualRequests.current[shortcode];
      setManualLikes({ ...manualRequests.current });
    }
  };

  useEffect(() => {
    let stopped = false;
    let polling = false;
    const poll = async () => {
      if (polling) return;
      polling = true;
      await Promise.all(Object.entries(manualRequests.current).map(async ([shortcode, job]) => {
       try {
        const response = await fetch(`/api/instagram/manual-like?id=${job.id}`, { cache: "no-store" });
        const result = await response.json();
        if (stopped || manualRequests.current[shortcode]?.id !== job.id) return;
        if (["applied", "already_liked", "failed"].includes(result.status)) {
          setManualMessage(result.status === "applied" ? "Mi piace confermato su @ma.menichelli" : result.status === "already_liked" ? "Il tuo Mi piace era già presente" : result.message || "Like non confermato");
          if (result.status !== "failed") {
            hiddenPosts.current.add(shortcode);
            setLikeHistory(current => current ? { ...current, total: Math.max(0, current.total - Number(current.events.some(event => event.shortcode === shortcode))), events: current.events.filter(event => event.shortcode !== shortcode) } : current);
          }
          delete manualRequests.current[shortcode];
          setManualLikes({ ...manualRequests.current });
        } else if (Date.now() - job.startedAt > 130_000) {
          setManualMessage("Conferma non ricevuta: controlla il post prima di riprovare");
          delete manualRequests.current[shortcode]; setManualLikes({ ...manualRequests.current });
        }
       } catch { if (!stopped) setManualMessage("Collegamento interrotto: attendo la conferma, senza ripetere il like"); }
      }));
      polling = false;
    };
    const timer = window.setInterval(() => void poll(), 2000);
    return () => { stopped = true; window.clearInterval(timer); };
  }, []);

  useEffect(()=>{
    const controller=new AbortController();let running=false;let version=0;
    const update=async()=>{
      if(running||controller.signal.aborted)return;running=true;
      try {
        const statusResponse=await fetch('/api/instagram/refresh-posts',{cache:'no-store',signal:controller.signal});
        const status=await statusResponse.json();if(!statusResponse.ok)throw Error(status.error);
        const page=likePageRef.current;
        const response=await fetch(`/api/agent/instagram-likes?page=${page}`,{cache:'no-store',signal:controller.signal});
        const result=await response.json() as LikeHistory;
        if(!response.ok)throw Error('Post temporaneamente non disponibili');
        if(!controller.signal.aborted&&page===likePageRef.current){const hidden=result.events.filter(event=>hiddenPosts.current.has(event.shortcode));setLikeHistory({...result,total:Math.max(0,result.total-hidden.length),events:result.events.filter(event=>!hiddenPosts.current.has(event.shortcode))});}
        if(controller.signal.aborted)return;
        if(version && status.completed_request_at>=version){setCollectionMessage('Aggiornamento Instagram completato');return;}
        setCollectionMessage(status.error || (Date.now()-status.last_seen>120000 ? 'Attendo il collegamento della raccolta Instagram: il PC deve essere acceso' : 'Aggiornamento da Instagram in corso: i post appaiono appena verificati'));
      }catch(error){if(!controller.signal.aborted)setCollectionMessage(error instanceof Error?error.message:'Aggiornamento non completato');}
      finally{running=false;}
    };
    const begin=async()=>{
      setCollectionMessage('Richiedo i nuovi post a Instagram…');
      try{const response=await fetch('/api/instagram/refresh-posts',{method:'POST',headers:{'x-orbit-manual':'1'},signal:controller.signal});const body=await response.json();if(!response.ok)throw Error(body.error);version=body.requested_at;await update();}
      catch(error){if(!controller.signal.aborted)setCollectionMessage(error instanceof Error?error.message:'Aggiornamento non richiesto');}
    };
    void begin();const timer=window.setInterval(()=>void update(),3000);
    return()=>{controller.abort();window.clearInterval(timer);};
  },[]);

  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      try {
        const response = await fetch(`/api/agent/instagram-likes?page=${likePage}`, {
          cache: "no-store", signal: controller.signal,
        });
        const body = await response.json();
        if (!response.ok) throw new Error(body.error ?? "Storico like non disponibile");
        if (!controller.signal.aborted) { const result = body as LikeHistory; const hidden = result.events.filter(event => hiddenPosts.current.has(event.shortcode)); setLikeHistory({ ...result, total: Math.max(0, result.total - hidden.length), events: result.events.filter(event => !hiddenPosts.current.has(event.shortcode)) }); setLikeHistoryError(""); }
      } catch (error) {
        if (!controller.signal.aborted) setLikeHistoryError(error instanceof Error ? error.message : "Storico like non disponibile");
      }
    };
    void load();
    const timer = window.setInterval(() => void load(), 30_000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [likePage]);

  useEffect(() => {
    if (likeHistory) setLikePage(page => Math.min(page, Math.max(1, Math.ceil(likeHistory.total / 20))));
  }, [likeHistory?.total]);

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
    let storedDataLoaded = false;
    let metaLoaded = false;
    let storedError = "";
    try {
      if (manual) setLoading(true);
      const storedResults = await Promise.allSettled([
        fetch("/api/growth", { cache: "no-store" }),
        fetch("/api/planner", { cache: "no-store" }),
      ]);
      const growthResult = storedResults[0];
      if (growthResult.status === "fulfilled" && growthResult.value.ok) {
        applyGrowthState(await growthResult.value.json() as GrowthState);
        storedDataLoaded = true;
      }
      const plannerResult = storedResults[1];
      if (plannerResult.status === "fulfilled" && plannerResult.value.ok) {
        const storedPlanner = await plannerResult.value.json() as PlannerState;
        setPlanner(storedPlanner);
        setSnapshot((current) => snapshotWithPlannerFallback(current, storedPlanner));
        storedDataLoaded = true;
      }
      if (!storedDataLoaded) storedError = "Dati Orbit temporaneamente non disponibili";

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
      metaLoaded = true;
      setSyncError("");

      const candidatePayload = body.opportunities.map((candidate) => ({
        externalId: candidate.externalId,
        username: candidate.username,
        displayName: candidate.name,
        platform: candidate.platform,
        profileUrl: candidate.profileUrl,
        interactions: candidate.interactions,
        score: candidate.score,
        followerCount: candidate.followerCount,
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
    } catch (error) {
      const metaError = error instanceof Error ? error.message : "Sincronizzazione Meta non disponibile";
      setSyncError(storedDataLoaded ? `Meta non disponibile · dati Orbit caricati` : storedError || metaError);
    } finally {
      if (manual) notify(metaLoaded ? "Piano operativo e dati Meta aggiornati" : storedDataLoaded ? "Piano operativo Orbit aggiornato" : "Aggiornamento non disponibile");
      setLoading(false);
    }
  }, [applyGrowthState, notify]);

  useEffect(() => {
    const initialRefresh = window.setTimeout(() => void refresh(), 0);
    const timer = window.setInterval(() => void refresh(), 5 * 60_000);
    return () => {
      window.clearTimeout(initialRefresh);
      window.clearInterval(timer);
    };
  }, [refresh]);

  useEffect(() => {
    const callbackRefresh = window.setTimeout(() => {
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
    }, 0);
    return () => window.clearTimeout(callbackRefresh);
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

  const resolvePlannerAction = (action: PlannerAction, operation: "complete" | "skip") => {
    setHiddenActionIds((current) => new Set(current).add(action.id));
    const message = operation === "complete"
      ? action.action_type === "lost_follower" ? "Segnalazione archiviata" : "Azione completata"
      : undefined;
    void plannerRequest({ operation, actionId: action.id }, message).then((ok) => {
      if (!ok) {
        setHiddenActionIds((current) => {
          const next = new Set(current);
          next.delete(action.id);
          return next;
        });
        void refresh();
      }
    });
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

  const addProtectedUsernames = async () => {
    const usernames = [...new Set(protectedInput.split(/[\s,;]+/).map((value) => value.trim().replace(/^@/, "").toLowerCase()).filter((value) => /^[a-z0-9._]{1,30}$/.test(value)))];
    if (!usernames.length) return notify("Inserisci almeno un username Instagram valido");
    try {
      const response = await fetch("/api/growth", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ operation: "protect_bulk", usernames }),
      });
      const result = await response.json() as GrowthState & { error?: string; imported?: number };
      if (!response.ok) throw new Error(result.error ?? "Importazione non riuscita");
      applyGrowthState(result);
      setProtectedInput("");
      notify(`${result.imported ?? usernames.length} intoccabili salvati`);
      void refresh();
    } catch (error) {
      notify(error instanceof Error ? error.message : "Importazione non riuscita");
    }
  };

  const protectedIds = useMemo(
    () => new Set(growth.protectedProfiles.map((profile) => profile.external_id)),
    [growth.protectedProfiles],
  );
  const approvedIds = useMemo(
    () => new Set(growth.queue.filter((item) => item.action_type === "priority_interaction" && item.status === "approved").map((item) => item.external_id)),
    [growth.queue],
  );
  const visibleCandidates = snapshot.opportunities.filter((candidate) =>
    !approvedIds.has(candidate.externalId)
    && (candidate.interactions > 0 || candidate.followerCount == null || candidate.followerCount <= 10_000));

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

  const pendingActions = planner.actions.filter((action) => action.status === "pending" && !hiddenActionIds.has(action.id));
  const pagination = (key: string, total: number) => {
    if (total <= LIST_PAGE_SIZE) return null;
    const pages = Math.ceil(total / LIST_PAGE_SIZE);
    const current = Math.min(listPages[key] ?? 0, pages - 1);
    const start = current * LIST_PAGE_SIZE + 1;
    const end = Math.min(total, start + LIST_PAGE_SIZE - 1);
    return (
      <div className="list-pagination" aria-label={`Paginazione ${key}`}>
        <span>{start}–{end} di {total}</span>
        <div>
          <button disabled={current === 0} onClick={() => setListPages((value) => ({ ...value, [key]: Math.max(0, current - 1) }))}>← Precedenti</button>
          <strong>{current + 1}/{pages}</strong>
          <button disabled={current >= pages - 1} onClick={() => setListPages((value) => ({ ...value, [key]: Math.min(pages - 1, current + 1) }))}>Successivi →</button>
        </div>
      </div>
    );
  };
  const dailyActionPanel = (
    title: string,
    eyebrow: string,
    actionTypes: PlannerAction["action_type"][],
    emptyMessage: string,
  ) => {
    const actions = pendingActions.filter((action) => actionTypes.includes(action.action_type));
    const pageKey = actionTypes.join("-");
    const pageCount = Math.max(1, Math.ceil(actions.length / LIST_PAGE_SIZE));
    const page = Math.min(listPages[pageKey] ?? 0, pageCount - 1);
    const visibleActions = actions.slice(page * LIST_PAGE_SIZE, (page + 1) * LIST_PAGE_SIZE);
    return (
      <article className="panel daily-action-panel">
        <div className="panel-head"><div><p className="eyebrow">{eyebrow}</p><h2>{title}</h2></div><span className="daily-count">{actions.length}</span></div>
        {!actions.length && <div className="daily-empty">{emptyMessage}</div>}
        {visibleActions.map((action) => (
          <div className="daily-action" key={action.id}>
            <div className="daily-person">
              <span className="avatar mini">{initials(action.display_name || action.username)}</span>
              <div><strong>@{action.username}</strong><small>{action.reason}</small>{action.action_type === "follow" && action.follower_count != null && <small>{formatNumber(action.follower_count)} follower · segue {formatNumber(action.following_count)} · {formatNumber(action.media_count)} post · attività {formatNumber(action.activity_score)}/100{action.italian_signal ? " · Italia" : ""}{action.female_self_declared ? " · donna (bio)" : ""}</small>}</div>
            </div>
            <div className="probability"><strong>{action.action_type === "lost_follower" ? "Rilevato" : `${action.probability}/100`}</strong><span>{action.action_type === "lost_follower" ? formatDate(action.unfollowed_you_at) : "punteggio reciprocità"}</span></div>
            <div className="daily-buttons">
              <a href={action.profile_url} target="_blank" rel="noreferrer">Apri profilo</a>
              <button onClick={() => resolvePlannerAction(action, "complete")}>{action.action_type === "lost_follower" ? "Archivia" : "Fatto"}</button>
              <button className="skip" onClick={() => resolvePlannerAction(action, "skip")}>Salta</button>
            </div>
          </div>
        ))}
        {pagination(pageKey, actions.length)}
      </article>
    );
  };

  const candidatePageCount = Math.max(1, Math.ceil(visibleCandidates.length / LIST_PAGE_SIZE));
  const candidatePage = Math.min(listPages.candidates ?? 0, candidatePageCount - 1);
  const pagedCandidates = visibleCandidates.slice(
    candidatePage * LIST_PAGE_SIZE,
    (candidatePage + 1) * LIST_PAGE_SIZE,
  );
  const candidatePanel = (
    <article className="panel opportunities">
      <div className="panel-head">
        <div><p className="eyebrow">PRIORITÀ AUTOMATICHE</p><h2>Profili con maggiore reciprocità</h2></div>
        <span className="live-pill">● LIVE</span>
      </div>
      <p className="muted">Ranking per affinità italiana, attività recente, interazioni osservate e rapporto seguiti/follower. Le donne che si dichiarano tali nella bio hanno priorità; i profili senza genere dichiarato possono completare la lista. Esclusi account vuoti e grandi profili poco propensi alla reciprocità.</p>
      <div className="candidate-list">
        {loading && !snapshot.opportunities.length && <div className="all-done">Sto verificando attività, relazioni e segnali di reciprocità…</div>}
        {!loading && !visibleCandidates.length && (
          <div className="all-done">
            {snapshot.accounts.length
              ? "Nessun nuovo profilo ancora qualificato. Orbit non inventa probabilità: pubblica un account solo dopo aver verificato segnali reali di attività, affinità e reciprocità."
              : "Collega Instagram professionale per iniziare."}
          </div>
        )}
        {pagedCandidates.map((candidate, index) => (
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
        {pagination("candidates", visibleCandidates.length)}
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
              <span className="nav-icon">{["✓", "✦", "♧", "↗"][index]}</span>{item}
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

        {active === "Oggi" && (
          <>
            <section className="daily-hero">
              <div>
                <p className="eyebrow">PIANO OPERATIVO · {planner.date || "OGGI"}</p>
                <h2>{planner.summary.pending} azioni rimaste</h2>
                <p>Segui l’ordine proposto: prima segnali reali, poi donne italiane attive con alta reciprocità stimata, infine scrematura.</p>
              </div>
              <div className="daily-progress">
                <strong>{planner.summary.completed}</strong><span>completate</span>
                <div><i style={{ width: `${planner.actions.length ? Math.round(planner.summary.completed / planner.actions.length * 100) : 0}%` }} /></div>
              </div>
              <div className="daily-summary">
                <span><strong>{planner.summary.follows}</strong> follow</span>
                <span><strong>{planner.summary.unfollows}</strong> defollow</span>
                <span><strong>{planner.summary.lostFollowers}</strong> ti hanno defollowato</span>
              </div>
            </section>

            <section className="daily-grid">
              {dailyActionPanel("Chi seguire", "FOLLOW STRATEGICI", ["follow", "follow_back"], "Aggiungi target o importa le liste Instagram per creare i follow di oggi.")}
              {dailyActionPanel("Chi defolloware", "SCREMATURA PROTETTA", ["unfollow"], "Nessun non-follower da revisionare. Gli account saltati restano protetti e non vengono riproposti.")}
              {dailyActionPanel("Chi ti ha defollowato", "CONTROLLO PERDITE", ["lost_follower"], planner.lastImport ? "Nessun nuovo defollow rilevato rispetto al confronto precedente." : "Importa oggi le liste; dal confronto successivo Orbit rileverà ogni follower perso, anche se non lo segui.")}
            </section>

            <section className="today-footer-grid">
              <article className="panel routine-panel">
                <p className="eyebrow">STRATEGIA QUOTIDIANA</p><h2>Routine di crescita</h2>
                <div className="routine-step"><span>1</span><div><strong>Reciprocità osservata</strong><small>Prima chi ha già lasciato like o commenti; poi profili vicini con segnali favorevoli.</small></div></div>
                <div className="routine-step"><span>2</span><div><strong>Donne italiane verificate</strong><small>Richiede segnali italiani pubblici e identità femminile dichiarata nella bio; esclude account vuoti, inattivi o sproporzionati.</small></div></div>
                <div className="routine-step"><span>3</span><div><strong>Controllo dopo 10 giorni</strong><small>Ogni follow completato entra automaticamente nella finestra di revisione.</small></div></div>
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

        {active === "Opportunità" && <section className="workspace-grid opportunities-focus">{candidatePanel}<aside className="right-stack">{accountPanel}</aside></section>}

        {active === "Relazioni" && (
          <section className="module-grid">
            <article className="panel review-queue">
              <div className="panel-head"><div><p className="eyebrow">REVISIONE OGNI 10 GIORNI</p><h2>Coda relazioni</h2></div><span className="trend">{growth.review.queued} azioni</span></div>
              <p className="muted">Dopo 10 giorni senza follow-back, l’agente esegue il defollow nel browser. Gli intoccabili restano esclusi.</p>
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
              <label><span>Incolla uno o più @username, oppure carica un file TXT</span><textarea value={protectedInput} onChange={(event) => setProtectedInput(event.target.value)} rows={4} placeholder="@username, uno per riga" /></label>
              <input type="file" accept=".txt,.csv" aria-label="Carica lista intoccabili" onChange={(event) => { const file = event.target.files?.[0]; if (file) void file.text().then((value) => setProtectedInput(value)); }} />
              <button className="primary" disabled={!protectedInput.trim()} onClick={() => void addProtectedUsernames()}>Aggiungi intoccabili</button>
              {!growth.protectedProfiles.length && <p className="account-empty">Premi ♧ accanto a una persona per proteggerla.</p>}
              {growth.protectedProfiles.map((profile) => (
                <div className="protected-row" key={profile.external_id}><span className="avatar mini">{initials(profile.display_name)}</span><div><strong>{profile.display_name}</strong><small>{profile.platform} · dal {formatDate(profile.created_at)}</small></div><button className="text-button" onClick={() => void persist("unprotect", { external_id: profile.external_id, display_name: profile.display_name, platform: profile.platform, action_type: "", status: "", created_at: profile.created_at })}>Rimuovi</button></div>
              ))}
            </article>
            <article className="panel agent-panel">
              <p className="eyebrow">AGENTE OPEN SOURCE</p><h2>Sincronizzazione automatica</h2>
              <p className="muted">Il connettore locale gratuito scarica follower e seguiti, elimina chi già segui e ogni 6 ore prepara soltanto donne italiane attive che lo dichiarano nella bio.</p>
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
              <div className="capability-row"><span>Follower e seguiti</span><strong className={planner.lastImport || planner.agentStatus ? "ok" : "wait"}>{planner.lastImport || planner.agentStatus ? "Attivo" : "In attesa"}</strong></div>
              <div className="capability-row"><span>Filtro Italia e attività</span><strong className={planner.agentStatus ? "ok" : "wait"}>{planner.agentStatus ? "Attivo" : "In attesa"}</strong></div>
              <div className="capability-row"><span>Revisione a 10 giorni</span><strong className="ok">Attiva</strong></div>
              <div className="capability-row"><span>Lista intoccabili</span><strong className="ok">Attiva</strong></div>
            </article>
          </section>
        )}
        {(active === "Oggi" || active === "Attività") && (
          <article className="panel like-history-panel">
            <div className="panel-head"><div><p className="eyebrow">SOLO GENERALE · @{likeHistory?.accountUsername ?? "ma.menichelli"}</p><h2>Post da Generale</h2></div><span className="daily-count">{formatNumber(likeHistory?.total ?? 0)}</span></div>
            <p className="like-history-note">Un clic su «Mi piace» agisce solo su quel post, senza uscire da Orbit. {likeHistory?.manualOnline ? "Collegamento Instagram attivo." : "Collegamento Instagram offline: accendi il PC e avvia l’agente manuale."}</p>
            {manualMessage && <p className="like-history-note" role="status">{manualMessage}</p>}
            {collectionMessage && <p className="like-history-note" role="status">{collectionMessage}</p>}
            {likeHistoryError && <p role="status" className="sync-error">{likeHistoryError}. I dati già caricati restano visibili.</p>}
            {!likeHistory && !likeHistoryError && <p className="like-history-note">Caricamento dello storico…</p>}
            {likeHistory && !likeHistory.total && <p className="like-history-note">Nessun post verificato in Generale. I vecchi record senza provenienza verificata sono esclusi mentre la raccolta riparte.</p>}
            {likeHistory?.events.map(event => <div className="like-history-row" key={event.eventId}>
              <div className="like-history-result">
                <strong>{event.metadata?.authorUsername ? `@${event.metadata.authorUsername}` : "Autore non ancora disponibile"}</strong>
                {event.metadata?.publishedAt ? <time dateTime={event.metadata.publishedAt}>Pubblicato il {likeDate(event.metadata.publishedAt)}</time>
                  : <span>Data di pubblicazione non disponibile</span>}
                <time dateTime={event.observedAt}>Rilevato il {likeDate(event.observedAt)}</time>
              </div>
              <div className="like-history-groups"><span>Gruppi / chat in cui è stato condiviso il post</span>
                {event.groups.length ? event.groups.map(group => <a key={group.threadPath} href={`https://www.instagram.com${group.threadPath}`} target="_blank" rel="noreferrer">{group.title}</a>) : <span>Gruppo non registrato</span>}
              </div>
              <div className="manual-post-actions"><button className="manual-like-button" disabled={Boolean(manualLikes[event.shortcode]) || !likeHistory.manualOnline || ["applied", "already_liked"].includes(event.status)} aria-busy={Boolean(manualLikes[event.shortcode])}
                onClick={() => void requestManualLike(event.shortcode)} aria-label={`Mi piace al post ${event.shortcode}`}>
                {manualLikes[event.shortcode] ? "Conferma in corso…" : ["applied", "already_liked"].includes(event.status) ? "♥ Mi piace presente" : "♡ Mi piace"}
              </button>
              <button className="skip-post-button" disabled={Boolean(manualLikes[event.shortcode])} onClick={() => void skipPost(event.shortcode)} aria-label={`Salta definitivamente il post ${event.shortcode}`}>Skip</button></div>
            </div>)}
            {likeHistory && likeHistory.total > 20 && <div className="list-pagination">
              <span>20 post per pagina · {formatNumber(likeHistory.total)} registrati</span><div>
                <button disabled={likePage <= 1} onClick={() => setLikePage(page => page - 1)}>← Precedenti</button>
                <strong>{likePage} / {Math.ceil(likeHistory.total / 20)}</strong>
                <button disabled={likePage * 20 >= likeHistory.total} onClick={() => setLikePage(page => page + 1)}>Successivi →</button>
              </div>
            </div>}
          </article>
        )}
      </section>

      {showConfig && (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.currentTarget === event.target && setShowConfig(false)}>
          <section className="modal" role="dialog" aria-modal="true" aria-labelledby="config-title">
            <button className="close" onClick={() => setShowConfig(false)} aria-label="Chiudi">×</button>
            <p className="eyebrow">CONFIGURAZIONE</p><h2 id="config-title">Connetti o rinnova i profili</h2>
            <p className="muted">Collega Instagram per leggere i dati autorizzati del profilo. Il connettore locale usa una sessione custodita sul PC e Orbit non salva la password.</p>
            <a className="connect instagram-button" href="/api/instagram/connect">◎ Connetti / rinnova Instagram Creator</a>
            <a className="connect facebook-button" href="/api/meta/connect">f Connetti Pagine Facebook</a>
            <div className="planner-settings">
              <strong>Quote giornaliere</strong>
              <div>
                <label><span>Follow</span><input type="number" min="1" max="30" value={planner.settings.follows_per_day} onChange={(event) => setPlanner((current) => ({ ...current, settings: { ...current.settings, follows_per_day: Number(event.target.value) } }))} /></label>
                <label><span>Defollow mostrati</span><input type="number" min="1" max="5000" value={planner.settings.unfollows_per_day} onChange={(event) => setPlanner((current) => ({ ...current, settings: { ...current.settings, unfollows_per_day: Number(event.target.value) } }))} /></label>
                <label><span>Revisione</span><input type="number" min="1" max="30" value={planner.settings.review_days} onChange={(event) => setPlanner((current) => ({ ...current, settings: { ...current.settings, review_days: Number(event.target.value) } }))} /></label>
              </div>
              <button className="secondary" onClick={() => void plannerRequest({ operation: "settings", settings: { followsPerDay: planner.settings.follows_per_day, unfollowsPerDay: planner.settings.unfollows_per_day, reviewDays: planner.settings.review_days } }, "Quote giornaliere salvate")}>Salva quote</button>
            </div>
            <div className="safety-note"><strong>Azioni browser</strong><span>L’agente locale mette like ai post condivisi nelle chat di Generali ed esegue i defollow dovuti solo con sessione valida e relazioni aggiornate.</span></div>
          </section>
        </div>
      )}
      {toast && <div className="toast" role="status">{toast}</div>}
    </main>
  );
}
