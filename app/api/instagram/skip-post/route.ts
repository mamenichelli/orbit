import { getRawDb } from "@/db";
import { instagramAccount } from "@/app/instagram-manual";

export const dynamic = "force-dynamic";
export async function POST(request: Request) {
  if (!request.headers.get("oai-authenticated-user-id")) return Response.json({ error: "Accedi a Orbit" }, { status: 401 });
  if (request.headers.get("origin") !== new URL(request.url).origin || request.headers.get("x-orbit-manual") !== "1")
    return Response.json({ error: "Comando non valido" }, { status: 403 });
  let body: { shortcode?: string };
  try { const raw = await request.text(); if (raw.length > 300) throw new Error(); body = JSON.parse(raw); }
  catch { return Response.json({ error: "Post non valido" }, { status: 400 }); }
  if (!body || Object.keys(body).length !== 1 || typeof body.shortcode !== "string" || !/^[a-zA-Z0-9_-]{1,100}$/.test(body.shortcode))
    return Response.json({ error: "Scegli un singolo post" }, { status: 400 });
  try {
    const result = await getRawDb().prepare(`UPDATE browser_like_events SET status='skipped'
      WHERE account_username=? AND shortcode=? AND NOT EXISTS
      (SELECT 1 FROM instagram_manual_likes WHERE account_username=? AND shortcode=? AND status IN ('pending','executing'))`)
      .bind(instagramAccount, body.shortcode, instagramAccount, body.shortcode).run();
    if (!result.meta.changes) return Response.json({ error: "Post assente o like in corso: attendi la conferma" }, { status: 409 });
    return Response.json({ ok: true, shortcode: body.shortcode }, { headers: { "cache-control": "no-store" } });
  } catch { return Response.json({ error: "Skip non salvato: riprova" }, { status: 503 }); }
}
