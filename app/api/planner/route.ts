import { env } from "cloudflare:workers";

export const dynamic = "force-dynamic";

type CandidateInput = {
  externalId: string;
  username?: string | null;
  displayName: string;
  platform?: string;
  profileUrl?: string | null;
  interactions?: number;
  score?: number;
  lastInteraction?: string | null;
  followsYou?: boolean | null;
  youFollow?: boolean | null;
};

type Settings = {
  follows_per_day: number;
  comments_per_day: number;
  unfollows_per_day: number;
  review_days: number;
};

function todayRome() {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Rome",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

function cleanUsername(value: string) {
  return value.trim().replace(/^@/, "").toLowerCase().replace(/[^a-z0-9._]/g, "");
}

async function ensureSchema() {
  await env.DB.batch([
    env.DB.prepare(`CREATE TABLE IF NOT EXISTS protected_profiles (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      external_id TEXT NOT NULL UNIQUE,
      display_name TEXT NOT NULL,
      platform TEXT NOT NULL,
      reason TEXT NOT NULL DEFAULT 'contatto personale',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )`),
    env.DB.prepare(`CREATE TABLE IF NOT EXISTS growth_targets (
      external_id TEXT PRIMARY KEY,
      username TEXT NOT NULL COLLATE NOCASE,
      display_name TEXT NOT NULL,
      platform TEXT NOT NULL DEFAULT 'Instagram',
      profile_url TEXT,
      source TEXT NOT NULL DEFAULT 'organic_interaction',
      source_detail TEXT,
      interactions INTEGER NOT NULL DEFAULT 0,
      score INTEGER NOT NULL DEFAULT 0,
      follows_you INTEGER,
      you_follow INTEGER,
      previous_follows_you INTEGER,
      relation_batch TEXT,
      unfollowed_you_at TEXT,
      first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      last_interaction TEXT,
      followed_at TEXT,
      review_after TEXT,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )`),
    env.DB.prepare("CREATE UNIQUE INDEX IF NOT EXISTS growth_targets_username_idx ON growth_targets(username)"),
    env.DB.prepare(`CREATE TABLE IF NOT EXISTS follower_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      external_id TEXT NOT NULL,
      username TEXT NOT NULL,
      event_type TEXT NOT NULL,
      batch_id TEXT NOT NULL,
      detected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      UNIQUE(external_id, event_type, batch_id)
    )`),
    env.DB.prepare(`CREATE TABLE IF NOT EXISTS relation_imports (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      batch_id TEXT NOT NULL UNIQUE,
      followers_count INTEGER NOT NULL,
      following_count INTEGER NOT NULL,
      imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )`),
    env.DB.prepare(`CREATE TABLE IF NOT EXISTS daily_actions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      action_date TEXT NOT NULL,
      external_id TEXT NOT NULL,
      action_type TEXT NOT NULL,
      probability INTEGER NOT NULL DEFAULT 0,
      reason TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      completed_at TEXT,
      UNIQUE(action_date, external_id, action_type)
    )`),
    env.DB.prepare(`CREATE TABLE IF NOT EXISTS planner_settings (
      id INTEGER PRIMARY KEY CHECK (id = 1),
      follows_per_day INTEGER NOT NULL DEFAULT 12,
      comments_per_day INTEGER NOT NULL DEFAULT 10,
      unfollows_per_day INTEGER NOT NULL DEFAULT 8,
      review_days INTEGER NOT NULL DEFAULT 10,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )`),
    env.DB.prepare(`INSERT INTO planner_settings
      (id, follows_per_day, comments_per_day, unfollows_per_day, review_days)
      VALUES (1, 12, 10, 8, 10) ON CONFLICT(id) DO NOTHING`),
  ]);
}

async function readSettings() {
  return await env.DB.prepare(`SELECT follows_per_day, comments_per_day, unfollows_per_day, review_days
    FROM planner_settings WHERE id = 1`).first<Settings>() ?? {
    follows_per_day: 12,
    comments_per_day: 10,
    unfollows_per_day: 8,
    review_days: 10,
  };
}

async function syncCandidates(candidates: CandidateInput[]) {
  const usable = candidates.slice(0, 100).filter((candidate) => cleanUsername(candidate.username ?? ""));
  for (let offset = 0; offset < usable.length; offset += 40) {
    const statements = usable.slice(offset, offset + 40).map((candidate) => {
      const username = cleanUsername(candidate.username ?? "");
      return env.DB.prepare(`INSERT INTO growth_targets
        (external_id, username, display_name, platform, profile_url, source, interactions, score,
         follows_you, you_follow, last_interaction, updated_at)
        VALUES (?, ?, ?, ?, ?, 'organic_interaction', ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(username) DO UPDATE SET
          display_name = excluded.display_name,
          profile_url = COALESCE(excluded.profile_url, growth_targets.profile_url),
          interactions = MAX(growth_targets.interactions, excluded.interactions),
          score = MAX(growth_targets.score, excluded.score),
          follows_you = COALESCE(excluded.follows_you, growth_targets.follows_you),
          you_follow = COALESCE(excluded.you_follow, growth_targets.you_follow),
          last_interaction = COALESCE(excluded.last_interaction, growth_targets.last_interaction),
          updated_at = CURRENT_TIMESTAMP`)
        .bind(
          candidate.externalId,
          username,
          candidate.displayName || username,
          candidate.platform ?? "Instagram",
          candidate.profileUrl ?? `https://www.instagram.com/${username}/`,
          Math.max(0, candidate.interactions ?? 0),
          Math.max(0, Math.min(100, Math.round(candidate.score ?? 0))),
          candidate.followsYou == null ? null : candidate.followsYou ? 1 : 0,
          candidate.youFollow == null ? null : candidate.youFollow ? 1 : 0,
          candidate.lastInteraction ?? null,
        );
    });
    if (statements.length) await env.DB.batch(statements);
  }
}

async function importRelations(followers: string[], following: string[]) {
  const followerSet = new Set(followers.map(cleanUsername).filter(Boolean));
  const followingSet = new Set(following.map(cleanUsername).filter(Boolean));
  const usernames = [...new Set([...followerSet, ...followingSet])];
  const batchId = crypto.randomUUID();
  for (let offset = 0; offset < usernames.length; offset += 40) {
    const statements = usernames.slice(offset, offset + 40).map((username) => {
      const followsYou = followerSet.has(username) ? 1 : 0;
      const youFollow = followingSet.has(username) ? 1 : 0;
      const reviewAfter = youFollow && !followsYou ? new Date().toISOString() : null;
      return env.DB.prepare(`INSERT INTO growth_targets
        (external_id, username, display_name, platform, profile_url, source, interactions, score,
         follows_you, you_follow, previous_follows_you, relation_batch, review_after, updated_at)
        VALUES (?, ?, ?, 'Instagram', ?, 'instagram_export', 0, 35, ?, ?, NULL, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(username) DO UPDATE SET
          previous_follows_you = growth_targets.follows_you,
          follows_you = excluded.follows_you,
          you_follow = excluded.you_follow,
          relation_batch = excluded.relation_batch,
          unfollowed_you_at = CASE
            WHEN growth_targets.follows_you = 1 AND excluded.follows_you = 0 THEN CURRENT_TIMESTAMP
            WHEN excluded.follows_you = 1 THEN NULL
            ELSE growth_targets.unfollowed_you_at
          END,
          review_after = CASE
            WHEN excluded.you_follow = 1 AND excluded.follows_you = 0
              THEN COALESCE(growth_targets.review_after, excluded.review_after)
            ELSE NULL
          END,
          source = CASE
            WHEN growth_targets.source IN ('exchange_group', 'manual') THEN growth_targets.source
            ELSE 'instagram_export'
          END,
          updated_at = CURRENT_TIMESTAMP`)
        .bind(
          `username:${username}`,
          username,
          username,
          `https://www.instagram.com/${username}/`,
          followsYou,
          youFollow,
          batchId,
          reviewAfter,
        );
    });
    if (statements.length) await env.DB.batch(statements);
  }
  await env.DB.prepare(`INSERT OR IGNORE INTO follower_events
    (external_id, username, event_type, batch_id)
    SELECT external_id, username, 'unfollowed', ? FROM growth_targets
    WHERE relation_batch = ? AND previous_follows_you = 1 AND follows_you = 0`)
    .bind(batchId, batchId).run();
  await env.DB.prepare(`INSERT OR IGNORE INTO follower_events
    (external_id, username, event_type, batch_id)
    SELECT external_id, username, 'unfollowed', ? FROM growth_targets
    WHERE follows_you = 1 AND COALESCE(relation_batch, '') <> ?`)
    .bind(batchId, batchId).run();
  await env.DB.prepare(`UPDATE growth_targets SET
    previous_follows_you = follows_you,
    follows_you = 0,
    relation_batch = ?,
    unfollowed_you_at = CURRENT_TIMESTAMP,
    updated_at = CURRENT_TIMESTAMP
    WHERE follows_you = 1 AND COALESCE(relation_batch, '') <> ?`)
    .bind(batchId, batchId).run();
  await env.DB.prepare(`INSERT INTO relation_imports
    (batch_id, followers_count, following_count) VALUES (?, ?, ?)`)
    .bind(batchId, followerSet.size, followingSet.size).run();
  return { followers: followerSet.size, following: followingSet.size, compared: usernames.length };
}

async function addTarget(usernameValue: string, source: string, sourceDetail: string | null) {
  const username = cleanUsername(usernameValue);
  if (!username) throw new Error("Username Instagram non valido");
  const normalizedSource = ["exchange_group", "competitor_audience", "manual"].includes(source) ? source : "manual";
  const baseScore = normalizedSource === "exchange_group" ? 58 : normalizedSource === "competitor_audience" ? 46 : 40;
  await env.DB.prepare(`INSERT INTO growth_targets
    (external_id, username, display_name, platform, profile_url, source, source_detail, score, updated_at)
    VALUES (?, ?, ?, 'Instagram', ?, ?, ?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(username) DO UPDATE SET
      source = excluded.source,
      source_detail = excluded.source_detail,
      score = MAX(growth_targets.score, excluded.score),
      updated_at = CURRENT_TIMESTAMP`)
    .bind(
      `username:${username}`,
      username,
      username,
      `https://www.instagram.com/${username}/`,
      normalizedSource,
      sourceDetail,
      baseScore,
    ).run();
}

async function generateToday() {
  const date = todayRome();
  const settings = await readSettings();
  await env.DB.prepare(`UPDATE daily_actions SET status = 'invalid'
    WHERE action_date = ? AND status = 'pending' AND action_type IN ('follow', 'follow_back')
      AND EXISTS (
        SELECT 1 FROM growth_targets t
        WHERE t.external_id = daily_actions.external_id AND t.you_follow IS NOT 0
      )`).bind(date).run();
  await env.DB.prepare(`UPDATE daily_actions SET status = 'pending'
    WHERE action_date = ? AND status = 'invalid' AND action_type IN ('follow', 'follow_back')
      AND EXISTS (
        SELECT 1 FROM growth_targets t
        WHERE t.external_id = daily_actions.external_id AND t.you_follow = 0
      )`).bind(date).run();
  await env.DB.prepare(`UPDATE daily_actions SET status = 'invalid'
    WHERE status = 'pending' AND action_type = 'lost_follower'
      AND EXISTS (
        SELECT 1 FROM growth_targets t
        WHERE t.external_id = daily_actions.external_id AND t.unfollowed_you_at IS NULL
      )`).run();
  await env.DB.prepare(`INSERT OR IGNORE INTO daily_actions
    (action_date, external_id, action_type, probability, reason)
    SELECT ?, t.external_id,
      CASE WHEN t.follows_you = 1 THEN 'follow_back' ELSE 'follow' END,
      MIN(94, 32 + t.score / 2 + MIN(24, t.interactions * 5)
        + CASE t.source WHEN 'exchange_group' THEN 12 WHEN 'organic_interaction' THEN 10 ELSE 3 END),
      CASE
        WHEN t.follows_you = 1 THEN 'Ti segue già: follow-back consigliato per consolidare la relazione'
        WHEN t.source = 'exchange_group' THEN 'Segnalato da un gruppo di scambio: reciprocità più probabile, qualità da verificare'
        WHEN t.interactions > 1 THEN 'Ha interagito più volte: segnale concreto di interesse'
        WHEN t.source = 'competitor_audience' THEN 'Pubblico affine: controlla il profilo prima di seguire'
        ELSE 'Target manuale da qualificare prima del follow'
      END
    FROM growth_targets t
    WHERE t.you_follow = 0
      AND t.username <> ''
      AND NOT EXISTS (
        SELECT 1 FROM daily_actions old
        WHERE old.external_id = t.external_id
          AND old.action_type IN ('follow', 'follow_back')
          AND old.status = 'completed'
      )
    ORDER BY
      CASE t.source WHEN 'organic_interaction' THEN 3 WHEN 'exchange_group' THEN 2 ELSE 1 END DESC,
      t.interactions DESC, t.score DESC, t.last_interaction DESC
    LIMIT ?`).bind(date, settings.follows_per_day).run();

  await env.DB.prepare(`INSERT OR IGNORE INTO daily_actions
    (action_date, external_id, action_type, probability, reason)
    SELECT ?, t.external_id, 'comment',
      MIN(95, 38 + t.score / 2 + MIN(30, t.interactions * 7)),
      CASE
        WHEN t.interactions > 2 THEN 'Commentatore ricorrente: alta probabilità di riaprire la conversazione'
        ELSE 'Ha già interagito: commenta un contenuto recente con un riferimento specifico'
      END
    FROM growth_targets t
    WHERE t.interactions > 0 AND t.username <> ''
    ORDER BY t.interactions DESC, t.score DESC, t.last_interaction DESC
    LIMIT ?`).bind(date, settings.comments_per_day).run();

  await env.DB.prepare(`INSERT OR IGNORE INTO daily_actions
    (action_date, external_id, action_type, probability, reason)
    SELECT ?, t.external_id, 'unfollow', 95,
      'Lo segui ma non ti segue; finestra di reciprocità scaduta e profilo non protetto'
    FROM growth_targets t
    LEFT JOIN protected_profiles p ON p.external_id = t.external_id
    WHERE t.you_follow = 1
      AND t.follows_you = 0
      AND p.external_id IS NULL
      AND t.review_after IS NOT NULL
      AND datetime(t.review_after) <= datetime('now')
    ORDER BY t.review_after ASC, t.score ASC
    LIMIT ?`).bind(date, settings.unfollows_per_day).run();

  await env.DB.prepare(`INSERT OR IGNORE INTO daily_actions
    (action_date, external_id, action_type, probability, reason)
    SELECT ?, t.external_id, 'lost_follower', 100,
      'Compariva tra i follower nel confronto precedente e ora non compare più'
    FROM growth_targets t
    WHERE t.unfollowed_you_at IS NOT NULL
      AND NOT EXISTS (
        SELECT 1 FROM daily_actions old
        WHERE old.external_id = t.external_id
          AND old.action_type = 'lost_follower'
          AND old.status = 'completed'
          AND datetime(old.completed_at) >= datetime(t.unfollowed_you_at)
      )
    ORDER BY t.unfollowed_you_at DESC
    LIMIT 50`).bind(date).run();
}

async function completeAction(id: number) {
  const action = await env.DB.prepare(`SELECT id, external_id, action_type FROM daily_actions WHERE id = ?`)
    .bind(id).first<{ id: number; external_id: string; action_type: string }>();
  if (!action) throw new Error("Azione non trovata");
  await env.DB.prepare("UPDATE daily_actions SET status = 'completed', completed_at = CURRENT_TIMESTAMP WHERE id = ?")
    .bind(id).run();
  if (action.action_type === "follow" || action.action_type === "follow_back") {
    const settings = await readSettings();
    const reviewAfter = new Date(Date.now() + settings.review_days * 86_400_000).toISOString();
    await env.DB.prepare(`UPDATE growth_targets SET you_follow = 1, followed_at = CURRENT_TIMESTAMP,
      review_after = ?, updated_at = CURRENT_TIMESTAMP WHERE external_id = ?`)
      .bind(reviewAfter, action.external_id).run();
  } else if (action.action_type === "unfollow") {
    await env.DB.prepare(`UPDATE growth_targets SET you_follow = 0, followed_at = NULL,
      review_after = NULL, updated_at = CURRENT_TIMESTAMP WHERE external_id = ?`)
      .bind(action.external_id).run();
  }
}

async function readPlanner() {
  const date = todayRome();
  const [actions, settings, totals, lastImport] = await Promise.all([
    env.DB.prepare(`SELECT a.id, a.action_date, a.action_type, a.probability, a.reason, a.status,
      a.created_at, a.completed_at, t.external_id, t.username, t.display_name, t.profile_url,
      t.source, t.source_detail, t.interactions, t.follows_you, t.you_follow, t.review_after,
      t.unfollowed_you_at
      FROM daily_actions a JOIN growth_targets t ON t.external_id = a.external_id
      WHERE a.action_date = ? AND a.status <> 'invalid'
      ORDER BY CASE a.action_type WHEN 'follow' THEN 1 WHEN 'follow_back' THEN 1
        WHEN 'comment' THEN 2 WHEN 'unfollow' THEN 3 WHEN 'lost_follower' THEN 4 ELSE 5 END,
        a.status = 'completed', a.probability DESC`).bind(date).all(),
    readSettings(),
    env.DB.prepare(`SELECT
      COUNT(*) AS targets,
      SUM(CASE WHEN follows_you = 1 THEN 1 ELSE 0 END) AS followers,
      SUM(CASE WHEN you_follow = 1 THEN 1 ELSE 0 END) AS following,
      SUM(CASE WHEN you_follow = 1 AND follows_you = 0 THEN 1 ELSE 0 END) AS non_followers,
      SUM(CASE WHEN unfollowed_you_at IS NOT NULL THEN 1 ELSE 0 END) AS lost_followers,
      SUM(CASE WHEN source = 'exchange_group' THEN 1 ELSE 0 END) AS exchange_targets
      FROM growth_targets`).first(),
    env.DB.prepare(`SELECT followers_count, following_count, imported_at
      FROM relation_imports ORDER BY imported_at DESC LIMIT 1`).first(),
  ]);
  const rows = actions.results ?? [];
  return {
    date,
    actions: rows,
    settings,
    totals,
    lastImport,
    summary: {
      pending: rows.filter((item) => item.status === "pending").length,
      completed: rows.filter((item) => item.status === "completed").length,
      follows: rows.filter((item) => item.action_type === "follow" || item.action_type === "follow_back").length,
      comments: rows.filter((item) => item.action_type === "comment").length,
      unfollows: rows.filter((item) => item.action_type === "unfollow").length,
      lostFollowers: rows.filter((item) => item.action_type === "lost_follower").length,
    },
  };
}

export async function GET() {
  await ensureSchema();
  await generateToday();
  return Response.json(await readPlanner(), { headers: { "cache-control": "no-store" } });
}

export async function POST(request: Request) {
  await ensureSchema();
  const body = await request.json() as {
    operation?: "sync" | "add_target" | "import_relations" | "complete" | "skip" | "settings" | "regenerate";
    candidates?: CandidateInput[];
    username?: string;
    source?: string;
    sourceDetail?: string | null;
    followers?: string[];
    following?: string[];
    actionId?: number;
    settings?: Partial<{ followsPerDay: number; commentsPerDay: number; unfollowsPerDay: number; reviewDays: number }>;
  };

  let importResult: { followers: number; following: number; compared: number } | null = null;
  if (body.operation === "sync") {
    await syncCandidates(Array.isArray(body.candidates) ? body.candidates : []);
  } else if (body.operation === "add_target") {
    await addTarget(body.username ?? "", body.source ?? "manual", body.sourceDetail ?? null);
  } else if (body.operation === "import_relations") {
    importResult = await importRelations(
      Array.isArray(body.followers) ? body.followers : [],
      Array.isArray(body.following) ? body.following : [],
    );
  } else if (body.operation === "complete" && Number.isInteger(body.actionId)) {
    await completeAction(Number(body.actionId));
  } else if (body.operation === "skip" && Number.isInteger(body.actionId)) {
    await env.DB.prepare("UPDATE daily_actions SET status = 'skipped' WHERE id = ?")
      .bind(Number(body.actionId)).run();
  } else if (body.operation === "settings") {
    const current = await readSettings();
    const clamp = (value: number | undefined, fallback: number, max: number) =>
      Math.max(1, Math.min(max, Math.round(value ?? fallback)));
    await env.DB.prepare(`UPDATE planner_settings SET follows_per_day = ?, comments_per_day = ?,
      unfollows_per_day = ?, review_days = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1`)
      .bind(
        clamp(body.settings?.followsPerDay, current.follows_per_day, 30),
        clamp(body.settings?.commentsPerDay, current.comments_per_day, 30),
        clamp(body.settings?.unfollowsPerDay, current.unfollows_per_day, 30),
        clamp(body.settings?.reviewDays, current.review_days, 30),
      ).run();
  } else if (body.operation !== "regenerate") {
    return Response.json({ error: "Operazione non valida" }, { status: 400 });
  }

  await generateToday();
  return Response.json({ ok: true, importResult, ...(await readPlanner()) });
}
