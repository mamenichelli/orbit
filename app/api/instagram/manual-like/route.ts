import { getRawDb } from "@/db";
import { instagramAccount, manualAgentOnline, generalPostPredicate, visibleGeneralPostPredicate } from "@/app/instagram-manual";

export const dynamic = "force-dynamic";
export async function GET(request: Request) {
  const user = request.headers.get("oai-authenticated-user-id");
  if (!user) return Response.json({ error: "Accedi a Orbit" }, { status: 401 });
  const id = new URL(request.url).searchParams.get("id");
  if (!id || !/^[a-zA-Z0-9_-]{1,100}$/.test(id)) return Response.json({ error: "Richiesta non valida" }, { status: 400 });
  const job = await getRawDb().prepare("SELECT id, shortcode, status, message FROM instagram_manual_likes WHERE id = ? AND account_username = ? AND requested_by = ?")
    .bind(id, instagramAccount, user).first();
  return job ? Response.json(job, { headers: { "cache-control": "no-store" } }) : Response.json({ error: "Richiesta non trovata" }, { status: 404 });
}
export async function POST(request: Request) {
  const user = request.headers.get("oai-authenticated-user-id");
  if (!user) return Response.json({ error: "Accedi a Orbit" }, { status: 401 });
  if (request.headers.get("origin") !== new URL(request.url).origin || request.headers.get("x-orbit-manual") !== "1")
    return Response.json({ error: "Comando manuale non valido" }, { status: 403 });
  let body: { id?: string; shortcode?: string };
  try { const raw = await request.text(); if (raw.length > 1000) throw new Error(); body = JSON.parse(raw); }
  catch { return Response.json({ error: "Richiesta non valida" }, { status: 400 }); }
  if (!body || Object.keys(body).length !== 2 || !/^[a-zA-Z0-9_-]{1,100}$/.test(body.id ?? "") || !/^[a-zA-Z0-9_-]{1,100}$/.test(body.shortcode ?? ""))
    return Response.json({ error: "Scegli un singolo post" }, { status: 400 });
  const db = getRawDb();
  const prior = await db.prepare("SELECT id, shortcode, status FROM instagram_manual_likes WHERE id = ? AND requested_by = ?").bind(body.id, user).first();
  if (prior) return Response.json(prior);
  if (!(await manualAgentOnline())) return Response.json({ error: "Agente Instagram offline: il PC deve essere acceso e la sessione verificata" }, { status: 503 });
  const post = await db.prepare(`SELECT status FROM browser_like_events WHERE account_username = ? AND shortcode = ? AND ${generalPostPredicate}`).bind(instagramAccount, body.shortcode).first<{ status: string }>();
  if (!post) return Response.json({ error: "Post non presente nell’elenco" }, { status: 404 });
  if (["applied", "already_liked", "skipped"].includes(post.status)) return Response.json({ error: "Post già completato o saltato" }, { status: 409 });
  // Atomic partial uniqueness prevents parallel clicks from becoming a batch.
  const inserted = await db.prepare(`INSERT OR IGNORE INTO instagram_manual_likes
    (id, account_username, shortcode, requested_by, status, requested_at)
    SELECT ?, ?, ?, ?, 'pending', ? WHERE EXISTS
    (SELECT 1 FROM browser_like_events WHERE account_username=? AND shortcode=? AND ${visibleGeneralPostPredicate})`)
    .bind(body.id, instagramAccount, body.shortcode, user, Date.now(), instagramAccount, body.shortcode).run();
  if (!inserted.meta.changes) return Response.json({ error: "Attendi la conferma del like in corso prima di sceglierne un altro" }, { status: 409 });
  return Response.json({ id: body.id, shortcode: body.shortcode, status: "pending" }, { status: 202 });
}
