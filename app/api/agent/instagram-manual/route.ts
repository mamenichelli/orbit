import { getRawDb } from "@/db";
import { instagramAccount, isInstagramAgent, generalPostPredicate } from "@/app/instagram-manual";

export const dynamic = "force-dynamic";
export async function POST(request: Request) {
  if (!(await isInstagramAgent(request))) return Response.json({ error: "Non autorizzato" }, { status: 401 });
  let body: { action?: string; accountUsername?: string; id?: string; status?: string; message?: string };
  try { const raw = await request.text(); if (raw.length > 2000) throw new Error(); body = JSON.parse(raw); }
  catch { return Response.json({ error: "Richiesta non valida" }, { status: 400 }); }
  if (!body || body.accountUsername !== instagramAccount) return Response.json({ error: "Account errato" }, { status: 400 });
  const db = getRawDb(), now = Date.now();
  if (body.action === "claim") {
    await db.batch([
      db.prepare("INSERT INTO instagram_manual_agent (account_username, last_seen) VALUES (?, ?) ON CONFLICT(account_username) DO UPDATE SET last_seen=excluded.last_seen").bind(instagramAccount, now),
      db.prepare("UPDATE instagram_manual_likes SET status='failed', message='Richiesta scaduta o conferma interrotta: controlla il post prima di riprovare', finished_at=? WHERE account_username=? AND status IN ('pending','executing') AND requested_at < ?").bind(now, instagramAccount, now - 120_000),
      db.prepare(`UPDATE instagram_manual_likes SET status='failed', message='Post non verificato nella cartella Generale', finished_at=?
        WHERE account_username=? AND status='pending' AND shortcode NOT IN
          (SELECT shortcode FROM browser_like_events WHERE account_username=? AND ${generalPostPredicate})`).bind(now, instagramAccount, instagramAccount),
    ]);
    const job = await db.prepare(`UPDATE instagram_manual_likes SET status='executing'
      WHERE id=(SELECT id FROM instagram_manual_likes WHERE account_username=? AND status='pending' AND requested_at>=? ORDER BY requested_at LIMIT 1)
      RETURNING id, shortcode, requested_at`).bind(instagramAccount, now - 120_000).first();
    return Response.json({ ok: true, job }, { headers: { "cache-control": "no-store" } });
  }
  if (body.action !== "complete" || !/^[a-zA-Z0-9_-]{1,100}$/.test(body.id ?? "") || !["applied", "already_liked", "failed"].includes(body.status ?? ""))
    return Response.json({ error: "Conferma non valida" }, { status: 400 });
  const job = await db.prepare("SELECT shortcode, status FROM instagram_manual_likes WHERE id=? AND account_username=?").bind(body.id, instagramAccount).first<{ shortcode: string; status: string }>();
  if (!job) return Response.json({ error: "Richiesta non trovata" }, { status: 404 });
  if (job.status !== "executing") return Response.json({ ok: true, status: job.status });
  const statements = [db.prepare("UPDATE instagram_manual_likes SET status=?, message=?, finished_at=? WHERE id=? AND status='executing'")
    .bind(body.status, (body.message ?? "").slice(0, 300), now, body.id)];
  if (body.status !== "failed") statements.push(db.prepare("UPDATE browser_like_events SET status=?, liked_at=? WHERE account_username=? AND shortcode=?")
    .bind(body.status, body.status === "applied" ? new Date(now).toISOString() : null, instagramAccount, job.shortcode));
  await db.batch(statements);
  return Response.json({ ok: true, status: body.status });
}
