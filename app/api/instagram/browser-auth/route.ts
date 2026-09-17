import { getRawDb } from "@/db";
import { instagramAccount } from "@/app/instagram-manual";

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

function signedIn(request: Request) {
  return Boolean(request.headers.get("oai-authenticated-user-id"));
}

export async function GET(request: Request) {
  if (!signedIn(request)) return Response.json({ error: "Accedi a Orbit" }, { status: 401 });
  try {
    await ensureTable();
    const row = await getRawDb().prepare("SELECT * FROM instagram_browser_auth WHERE account_username=?")
      .bind(instagramAccount).first();
    return Response.json(row ?? {
      account_username: instagramAccount,
      requested_at: 0,
      started_request_at: 0,
      completed_request_at: 0,
      last_seen: 0,
      error: "",
    }, { headers: { "cache-control": "no-store" } });
  } catch {
    return Response.json({ error: "Stato accesso Instagram non disponibile" }, { status: 503 });
  }
}

export async function POST(request: Request) {
  if (!signedIn(request)) return Response.json({ error: "Accedi a Orbit" }, { status: 401 });
  if (request.headers.get("origin") !== new URL(request.url).origin || request.headers.get("x-orbit-manual") !== "1") {
    return Response.json({ error: "Richiesta non valida" }, { status: 403 });
  }
  try {
    await ensureTable();
    const now = Date.now();
    const row = await getRawDb().prepare(`INSERT INTO instagram_browser_auth (account_username, requested_at, error)
      VALUES (?, ?, '')
      ON CONFLICT(account_username) DO UPDATE SET requested_at=excluded.requested_at, error=''
      RETURNING *`).bind(instagramAccount, now).first();
    return Response.json(row, { status: 202, headers: { "cache-control": "no-store" } });
  } catch {
    return Response.json({ error: "Rinnovo Instagram non richiesto: riprova" }, { status: 503 });
  }
}
