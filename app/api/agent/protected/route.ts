import { env } from "cloudflare:workers";

export const dynamic = "force-dynamic";

async function authorized(request: Request) {
  const expected = process.env.ORBIT_AGENT_TOKEN ?? "";
  const actual = request.headers.get("authorization")?.replace(/^Bearer\s+/i, "") ?? "";
  if (!expected || !actual) return false;
  const [a, b] = await Promise.all([expected, actual].map((value) =>
    crypto.subtle.digest("SHA-256", new TextEncoder().encode(value))));
  const left = new Uint8Array(a);
  const right = new Uint8Array(b);
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

export async function GET(request: Request) {
  if (!(await authorized(request))) return Response.json({ error: "Non autorizzato" }, { status: 401 });
  const rows = await env.DB.prepare(`SELECT p.external_id, p.display_name, t.username
    FROM protected_profiles p LEFT JOIN growth_targets t ON t.external_id = p.external_id
    WHERE p.platform = 'Instagram'`).all<{
      external_id: string;
      display_name: string;
      username: string | null;
    }>();
  const usernames = new Set<string>();
  for (const item of rows.results ?? []) {
    const value = item.username ?? (/^(?:ig:|username:)/.test(item.external_id)
      ? item.external_id.replace(/^(?:ig:|username:)/, "") : "");
    if (/^[a-z0-9._]{1,30}$/.test(value)) usernames.add(value);
  }
  return Response.json({ usernames: [...usernames] }, { headers: { "cache-control": "no-store" } });
}
