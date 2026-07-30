import { env } from "cloudflare:workers";

export const dynamic = "force-dynamic";

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
      status TEXT NOT NULL DEFAULT 'approved',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )`),
    db.prepare(`CREATE TABLE IF NOT EXISTS audit_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      event_type TEXT NOT NULL,
      payload TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )`),
  ]);
}

export async function GET() {
  await ensureSchema();
  const [protectedRows, queueRows, auditRows] = await Promise.all([
    env.DB.prepare("SELECT * FROM protected_profiles ORDER BY created_at DESC").all(),
    env.DB.prepare("SELECT * FROM action_queue ORDER BY created_at DESC LIMIT 50").all(),
    env.DB.prepare("SELECT * FROM audit_events ORDER BY created_at DESC LIMIT 20").all(),
  ]);

  return Response.json({
    protectedProfiles: protectedRows.results,
    queue: queueRows.results,
    audit: auditRows.results,
  });
}

export async function POST(request: Request) {
  await ensureSchema();
  const body = await request.json() as {
    operation?: "protect" | "unprotect" | "approve";
    externalId?: string;
    displayName?: string;
    platform?: string;
  };

  if (!body.operation || !body.externalId) {
    return Response.json({ error: "Dati mancanti" }, { status: 400 });
  }

  if (body.operation === "protect") {
    await env.DB.prepare(
      "INSERT INTO protected_profiles (external_id, display_name, platform) VALUES (?, ?, ?) ON CONFLICT(external_id) DO UPDATE SET display_name = excluded.display_name, platform = excluded.platform",
    ).bind(body.externalId, body.displayName ?? body.externalId, body.platform ?? "Instagram").run();
  } else if (body.operation === "unprotect") {
    await env.DB.prepare("DELETE FROM protected_profiles WHERE external_id = ?")
      .bind(body.externalId).run();
  } else {
    await env.DB.prepare(
      "INSERT INTO action_queue (external_id, action_type, status) VALUES (?, 'review_profile', 'approved')",
    ).bind(body.externalId).run();
  }

  await env.DB.prepare("INSERT INTO audit_events (event_type, payload) VALUES (?, ?)")
    .bind(body.operation, JSON.stringify(body)).run();

  return Response.json({ ok: true });
}
