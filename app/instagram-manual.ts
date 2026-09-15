import { getRawDb } from "@/db";

export const instagramAccount = process.env.ORBIT_INSTAGRAM_USERNAME ?? "ma.menichelli";
// Keep uncertain historic records in storage, but exclude them from the General feed.
export const generalPostPredicate = "EXISTS (SELECT 1 FROM json_each(browser_like_events.groups_json) AS origin WHERE json_extract(origin.value, '$.folder') = 'general' AND json_extract(origin.value, '$.verification') = 'general-roster-v2')";
export const visibleGeneralPostPredicate = generalPostPredicate + " AND browser_like_events.status NOT IN ('applied', 'already_liked', 'skipped')";
export async function isInstagramAgent(request: Request) {
  const expected = process.env.ORBIT_AGENT_TOKEN ?? "";
  const actual = request.headers.get("authorization")?.replace(/^Bearer\s+/i, "") ?? "";
  if (!expected || !actual) return false;
  const hashes = await Promise.all([expected, actual].map(value => crypto.subtle.digest("SHA-256", new TextEncoder().encode(value))));
  return new Uint8Array(hashes[0]).every((value, index) => value === new Uint8Array(hashes[1])[index]);
}
export async function manualAgentOnline() {
  const row = await getRawDb().prepare("SELECT last_seen FROM instagram_manual_agent WHERE account_username = ?")
    .bind(instagramAccount).first<{ last_seen: number }>();
  return Boolean(row && Date.now() - row.last_seen < 45_000);
}
