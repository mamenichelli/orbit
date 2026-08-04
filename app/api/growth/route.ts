import { env } from "cloudflare:workers";

export const dynamic = "force-dynamic";

type CandidateInput = {
  externalId: string;
  displayName: string;
  platform: string;
  score?: number;
  lastInteraction?: string;
  followsYou?: boolean | null;
  youFollow?: boolean | null;
};

async function ensureSchema() {
  const db = env.DB;
  await db.batch([
    db.prepare(`CREATE TABLE IF NOT EXISTS protected_profiles (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      external_id TEXT NOT NULL UNIQUE,
      display_name TEXT NOT NULL,
      platform TEXT NOT NULL,
      reason TEXT NOT NULL DEFAULT 'contatto personale',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )`),
    db.prepare(`CREATE TABLE IF NOT EXISTS action_queue (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      external_id TEXT NOT NULL,
      action_type TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )`),
    db.prepare(`CREATE TABLE IF NOT EXISTS audit_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      event_type TEXT NOT NULL,
      payload TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )`),
    db.prepare(`CREATE TABLE IF NOT EXISTS relationship_candidates (
      external_id TEXT PRIMARY KEY,
      display_name TEXT NOT NULL,
      platform TEXT NOT NULL,
      score INTEGER NOT NULL DEFAULT 0,
      last_interaction TEXT,
      follows_you INTEGER,
      you_follow INTEGER,
      last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )`),
    db.prepare(`CREATE TABLE IF NOT EXISTS review_state (
      id INTEGER PRIMARY KEY CHECK (id = 1),
      last_run TEXT,
      next_run TEXT NOT NULL
    )`),
  ]);
}

async function readState() {
  const [protectedRows, queueRows, auditRows, reviewRow] = await Promise.all([
    env.DB.prepare("SELECT * FROM protected_profiles ORDER BY created_at DESC").all(),
    env.DB.prepare(`SELECT q.*, c.display_name, c.platform, c.score, c.last_interaction,
      c.follows_you, c.you_follow
      FROM action_queue q LEFT JOIN relationship_candidates c ON c.external_id = q.external_id
      WHERE q.status IN ('pending', 'approved') ORDER BY q.created_at DESC LIMIT 100`).all(),
    env.DB.prepare("SELECT * FROM audit_events ORDER BY created_at DESC LIMIT 30").all(),
    env.DB.prepare("SELECT * FROM review_state WHERE id = 1").first<{ last_run: string | null; next_run: string }>(),
  ]);
  const nextRun = reviewRow?.next_run ?? new Date().toISOString();
  return {
    protectedProfiles: protectedRows.results,
    queue: queueRows.results,
    audit: auditRows.results,
    review: {
      lastRun: reviewRow?.last_run ?? null,
      nextRun,
      dueInDays: Math.max(0, Math.ceil((Date.parse(nextRun) - Date.now()) / 86_400_000)),
      queued: queueRows.results?.length ?? 0,
    },
  };
}

async function runReviewIfDue() {
  const state = await env.DB.prepare("SELECT next_run FROM review_state WHERE id = 1")
    .first<{ next_run: string }>();
  if (state && Date.parse(state.next_run) > Date.now()) return false;

  const now = new Date().toISOString();
  const nextRun = new Date(Date.now() + 10 * 86_400_000).toISOString();
  await env.DB.prepare(`INSERT INTO action_queue (external_id, action_type, status)
    SELECT c.external_id, 'review_relationship', 'pending'
    FROM relationship_candidates c
    LEFT JOIN protected_profiles p ON p.external_id = c.external_id
    WHERE p.external_id IS NULL
      AND NOT EXISTS (
        SELECT 1 FROM action_queue q
        WHERE q.external_id = c.external_id
          AND q.action_type = 'review_relationship'
          AND q.status IN ('pending', 'approved')
      )`).run();
  await env.DB.prepare(`INSERT INTO review_state (id, last_run, next_run) VALUES (1, ?, ?)
    ON CONFLICT(id) DO UPDATE SET last_run = excluded.last_run, next_run = excluded.next_run`)
    .bind(now, nextRun).run();
  await env.DB.prepare("INSERT INTO audit_events (event_type, payload) VALUES ('automatic_review', ?)")
    .bind(JSON.stringify({ ranAt: now, nextRun })).run();
  return true;
}

async function syncCandidates(candidates: CandidateInput[]) {
  const statements = candidates.slice(0, 50).map((candidate) => env.DB.prepare(
    `INSERT INTO relationship_candidates
      (external_id, display_name, platform, score, last_interaction, follows_you, you_follow, last_seen_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
     ON CONFLICT(external_id) DO UPDATE SET
      display_name = excluded.display_name,
      platform = excluded.platform,
      score = excluded.score,
      last_interaction = excluded.last_interaction,
      follows_you = excluded.follows_you,
      you_follow = excluded.you_follow,
      last_seen_at = CURRENT_TIMESTAMP`,
  ).bind(
    candidate.externalId,
    candidate.displayName,
    candidate.platform,
    Math.max(0, Math.min(100, Math.round(candidate.score ?? 0))),
    candidate.lastInteraction ?? null,
    candidate.followsYou == null ? null : candidate.followsYou ? 1 : 0,
    candidate.youFollow == null ? null : candidate.youFollow ? 1 : 0,
  ));
  if (statements.length) await env.DB.batch(statements);
  await runReviewIfDue();
}

export async function GET() {
  await ensureSchema();
  await runReviewIfDue();
  return Response.json(await readState(), { headers: { "cache-control": "no-store" } });
}

export async function POST(request: Request) {
  await ensureSchema();
  const body = await request.json() as {
    operation?: "protect" | "unprotect" | "approve" | "complete" | "sync";
    externalId?: string;
    displayName?: string;
    platform?: string;
    candidates?: CandidateInput[];
  };

  if (body.operation === "sync") {
    await syncCandidates(Array.isArray(body.candidates) ? body.candidates : []);
    return Response.json({ ok: true, ...(await readState()) });
  }
  if (!body.operation || !body.externalId) {
    return Response.json({ error: "Dati mancanti" }, { status: 400 });
  }

  if (body.operation === "protect") {
    await env.DB.prepare(
      "INSERT INTO protected_profiles (external_id, display_name, platform) VALUES (?, ?, ?) ON CONFLICT(external_id) DO UPDATE SET display_name = excluded.display_name, platform = excluded.platform",
    ).bind(body.externalId, body.displayName ?? body.externalId, body.platform ?? "Instagram").run();
    await env.DB.prepare("UPDATE action_queue SET status = 'protected' WHERE external_id = ? AND status IN ('pending', 'approved')")
      .bind(body.externalId).run();
  } else if (body.operation === "unprotect") {
    await env.DB.prepare("DELETE FROM protected_profiles WHERE external_id = ?")
      .bind(body.externalId).run();
  } else if (body.operation === "approve") {
    await env.DB.prepare(`INSERT INTO action_queue (external_id, action_type, status)
      SELECT ?, 'priority_interaction', 'approved'
      WHERE NOT EXISTS (
        SELECT 1 FROM action_queue WHERE external_id = ? AND action_type = 'priority_interaction' AND status = 'approved'
      )`).bind(body.externalId, body.externalId).run();
  } else if (body.operation === "complete") {
    await env.DB.prepare("UPDATE action_queue SET status = 'completed' WHERE external_id = ? AND status IN ('pending', 'approved')")
      .bind(body.externalId).run();
  }

  await env.DB.prepare("INSERT INTO audit_events (event_type, payload) VALUES (?, ?)")
    .bind(body.operation, JSON.stringify(body)).run();
  return Response.json({ ok: true, ...(await readState()) });
}
