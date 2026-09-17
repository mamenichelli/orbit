import { getRawDb } from "@/db";
import { instagramAccount, isInstagramAgent } from "@/app/instagram-manual";

export const dynamic = "force-dynamic";

async function ensureTable() {
  await getRawDb().prepare(`CREATE TABLE IF NOT EXISTS instagram_browser_auth (
    account_username TEXT PRIMARY KEY,
    requested_at INTEGER NOT NULL DEFAULT 0,
    started_request_at INTEGER NOT NULL DEFAULT 0,
    completed_request_at INTEGER NOT NULL DEFAULT 0,
    last_seen INTEGER NOT NULL DEFAULT 0,
    error TEXT NOT NULL DEFAULT ''
  )`).run();
}

export async function POST(request: Request) {
  if (!(await isInstagramAgent(request))) return Response.json({ error: "Non autorizzato" }, { status: 401 });
  let body: { action?: string; accountUsername?: string; version?: number; message?: string };
  try {
    const raw = await request.text();
    if (raw.length > 1500) throw new Error();
    body = JSON.parse(raw);
  } catch {
    return Response.json({ error: "Richiesta non valida" }, { status: 400 });
  }
  const action = body?.action ?? "";
  if (body?.accountUsername !== instagramAccount || !["poll", "started", "finished", "failed", "required"].includes(action)) {
    return Response.json({ error: "Account o azione non validi" }, { status: 400 });
  }
  if (["finished", "failed"].includes(action) && (!Number.isSafeInteger(body.version) || Number(body.version) < 0)) {
    return Response.json({ error: "Versione non valida" }, { status: 400 });
  }

  try {
    await ensureTable();
    const db = getRawDb();
    const now = Date.now();
    await db.prepare(`INSERT INTO instagram_browser_auth (account_username, last_seen)
      VALUES (?, ?) ON CONFLICT(account_username) DO UPDATE SET last_seen=excluded.last_seen`)
      .bind(instagramAccount, now).run();

    if (action === "started") {
      await db.prepare("UPDATE instagram_browser_auth SET started_request_at=requested_at, error='' WHERE account_username=?")
        .bind(instagramAccount).run();
    } else if (action === "finished") {
      await db.prepare(`UPDATE instagram_browser_auth SET completed_request_at=MAX(completed_request_at, ?), error=''
        WHERE account_username=? AND started_request_at=?`).bind(body.version, instagramAccount, body.version).run();
    } else if (action === "failed") {
      await db.prepare(`UPDATE instagram_browser_auth
        SET completed_request_at=MAX(completed_request_at, ?), error=?
        WHERE account_username=? AND started_request_at=?`)
        .bind(body.version, (body.message ?? "Accesso Instagram non completato").slice(0, 300), instagramAccount, body.version).run();
    } else if (action === "required") {
      await db.prepare("UPDATE instagram_browser_auth SET error=? WHERE account_username=?")
        .bind((body.message ?? "Sessione Instagram scaduta").slice(0, 300), instagramAccount).run();
    }

    const row = await db.prepare("SELECT * FROM instagram_browser_auth WHERE account_username=?")
      .bind(instagramAccount).first();
    return Response.json(row, { headers: { "cache-control": "no-store" } });
  } catch {
    return Response.json({ error: "Coordinamento accesso Instagram non disponibile" }, { status: 503 });
  }
}
