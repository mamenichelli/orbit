import { getRawDb } from "@/db";
import { generalPostPredicate, manualAgentOnline, visibleGeneralPostPredicate } from "@/app/instagram-manual";

export const dynamic = "force-dynamic";
const account = process.env.ORBIT_INSTAGRAM_USERNAME ?? "ma.menichelli";

async function agentAuthorized(request: Request) {
  const expected = process.env.ORBIT_AGENT_TOKEN ?? "";
  const actual = request.headers.get("authorization")?.replace(/^Bearer\s+/i, "") ?? "";
  if (!expected || !actual) return false;
  const [a, b] = await Promise.all([expected, actual].map(value =>
    crypto.subtle.digest("SHA-256", new TextEncoder().encode(value))));
  const left = new Uint8Array(a), right = new Uint8Array(b);
  return left.every((value, index) => value === right[index]);
}

type Group = { title: string; threadPath: string; folder?: "general"; verification?: "general-roster-v2" };
type LikeEvent = { eventId: string; shortcode: string; status: string; likedAt: string | null; observedAt: string; groups: Group[]; metadata?: { caption?: string; previewUrl?: string; authorUsername?: string; publishedAt?: string | null } };
function safePreview(value: unknown) {
  if (value === undefined || value === "") return true;
  try { const url = new URL(String(value)); return url.protocol === "https:" && !url.username && !url.password && ["cdninstagram.com", "fbcdn.net"].some(domain => url.hostname === domain || url.hostname.endsWith(`.${domain}`)); } catch { return false; }
}

function validDate(value: unknown) {
  return typeof value === "string" && Number.isFinite(Date.parse(value))
    && Date.parse(value) <= Date.now() + 300_000;
}

export async function POST(request: Request) {
  if (!(await agentAuthorized(request))) return Response.json({ error: "Non autorizzato" }, { status: 401 });
  let body: { accountUsername?: string; events?: LikeEvent[] };
  try {
    const raw = await request.text();
    if (raw.length > 250_000) return Response.json({ error: "Registro troppo grande" }, { status: 413 });
    body = JSON.parse(raw);
  } catch { return Response.json({ error: "Registro non valido" }, { status: 400 }); }
  if (!body || typeof body !== "object" || body.accountUsername !== account || !Array.isArray(body.events) || body.events.length > 40) {
    return Response.json({ error: "Account o registro non valido" }, { status: 400 });
  }
  for (const event of body.events) {
    if (!event || typeof event.eventId !== "string" || !/^[a-zA-Z0-9_-]{1,128}$/.test(event.eventId)
      || typeof event.shortcode !== "string" || !/^[a-zA-Z0-9_-]{1,100}$/.test(event.shortcode)
      || !["applied", "already_liked", "legacy", "discovered"].includes(event.status)
      || !validDate(event.observedAt)
      || (event.metadata !== undefined && (!event.metadata || typeof event.metadata.caption !== "string" || event.metadata.caption.length > 2000 || !safePreview(event.metadata.previewUrl)))
      || (event.metadata?.authorUsername !== undefined && event.metadata.authorUsername !== "" && !/^[a-zA-Z0-9._]{1,30}$/.test(event.metadata.authorUsername))
      || (event.metadata?.publishedAt !== undefined && event.metadata.publishedAt !== null && !validDate(event.metadata.publishedAt))
      || (event.status === "applied" ? !validDate(event.likedAt) : event.likedAt !== null)
      || !Array.isArray(event.groups)
      || event.groups.some(group => !group || typeof group.title !== "string" || !group.title.trim()
        || group.title.length > 200 || !/^\/direct\/t\/[^/?#\s]+\/$/.test(group.threadPath ?? "")
        || (group.folder !== undefined && group.folder !== "general")
        || (group.verification !== undefined && (group.verification !== "general-roster-v2" || group.folder !== "general")))) {
      return Response.json({ error: "Evento non valido" }, { status: 400 });
    }
  }
  const db = getRawDb();
  if (body.events.length) await db.batch(body.events.map(event =>
    db.prepare(`INSERT INTO browser_like_events
      (event_id, account_username, shortcode, status, liked_at, observed_at, groups_json, metadata_json)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(account_username, shortcode) DO UPDATE SET
        groups_json = (SELECT json_group_array(json(value)) FROM
          (SELECT value FROM json_each(browser_like_events.groups_json)
           UNION SELECT value FROM json_each(excluded.groups_json))),
        metadata_json = CASE WHEN excluded.metadata_json != '{}' THEN excluded.metadata_json ELSE browser_like_events.metadata_json END`)
      .bind(event.eventId, account, event.shortcode, event.status, event.likedAt,
        event.observedAt, JSON.stringify(event.groups), JSON.stringify(event.metadata ?? {}))));
  return Response.json({ ok: true, accepted: body.events.length });
}

export async function GET(request: Request) {
  // Browser access is protected by the Site's owner-only policy; agents need their own token.
  if (!request.headers.get("oai-authenticated-user-id") && !(await agentAuthorized(request))) {
    return Response.json({ error: "Accedi a Orbit per leggere lo storico" }, { status: 401 });
  }
  try {
    const db = getRawDb();
    const [rows, counts, verifiedCounts] = await Promise.all([
      db.prepare(`SELECT event_id, shortcode, status, liked_at, observed_at, groups_json, metadata_json
        FROM browser_like_events WHERE account_username = ? AND ${visibleGeneralPostPredicate}
        ORDER BY COALESCE(liked_at, observed_at) DESC, event_id DESC`)
        .bind(account).all<{ event_id: string; shortcode: string; status: string; liked_at: string | null; observed_at: string; groups_json: string; metadata_json: string }>(),
      db.prepare(`SELECT COUNT(*) AS total, SUM(status = 'applied') AS applied
        FROM browser_like_events WHERE account_username = ? AND ${visibleGeneralPostPredicate}`).bind(account).first<{ total: number; applied: number | null }>(),
      db.prepare(`SELECT COUNT(*) AS total
        FROM browser_like_events WHERE account_username = ? AND ${generalPostPredicate}`).bind(account).first<{ total: number }>(),
    ]);
    return Response.json({
      accountUsername: account, page: 1, pageSize: counts?.total ?? 0, total: counts?.total ?? 0, applied: counts?.applied ?? 0,
      verifiedTotal: verifiedCounts?.total ?? 0,
      handledTotal: Math.max(0, (verifiedCounts?.total ?? 0) - (counts?.total ?? 0)),
      manualOnline: await manualAgentOnline(),
      events: (rows.results ?? []).map(row => ({ eventId: row.event_id, shortcode: row.shortcode,
        status: row.status, likedAt: row.liked_at, observedAt: row.observed_at,
        groups: (JSON.parse(row.groups_json) as Group[]).filter(group => group.folder === "general" && group.verification === "general-roster-v2"),
        metadata: (() => { const metadata = JSON.parse(row.metadata_json); return { authorUsername: metadata.authorUsername ?? "", publishedAt: metadata.publishedAt ?? null }; })() })),
    }, { headers: { "cache-control": "no-store" } });
  } catch {
    return Response.json({ error: "Storico like temporaneamente non disponibile" }, { status: 503 });
  }
}
