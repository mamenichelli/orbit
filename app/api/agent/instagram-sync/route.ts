import { env } from "cloudflare:workers";

export const dynamic = "force-dynamic";

type DiscoveryCandidate = {
  externalId: string;
  username: string;
  displayName?: string;
  sourceDetail?: string;
  score?: number;
  reason?: string;
  followerCount?: number;
  followingCount?: number;
  mediaCount?: number;
  isPrivate?: boolean;
  lastPostAt?: string | null;
  activityScore?: number;
  italianSignal?: boolean;
  femaleSelfDeclared?: boolean;
};

function cleanUsername(value: string) {
  return value.trim().replace(/^@/, "").toLowerCase().replace(/[^a-z0-9._]/g, "");
}

async function sameSecret(provided: string, expected: string) {
  const encode = (value: string) => new TextEncoder().encode(value);
  const [left, right] = await Promise.all([
    crypto.subtle.digest("SHA-256", encode(provided)),
    crypto.subtle.digest("SHA-256", encode(expected)),
  ]);
  const a = new Uint8Array(left);
  const b = new Uint8Array(right);
  let mismatch = a.length ^ b.length;
  for (let index = 0; index < Math.min(a.length, b.length); index += 1) mismatch |= a[index] ^ b[index];
  return mismatch === 0;
}

async function ensureTables() {
  await env.DB.batch([
    env.DB.prepare(`CREATE TABLE IF NOT EXISTS follower_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      external_id TEXT NOT NULL,
      username TEXT NOT NULL,
      event_type TEXT NOT NULL,
      batch_id TEXT NOT NULL,
      detected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      UNIQUE(external_id, event_type, batch_id)
    )`),
    env.DB.prepare(`CREATE TABLE IF NOT EXISTS relation_imports (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      batch_id TEXT NOT NULL UNIQUE,
      followers_count INTEGER NOT NULL,
      following_count INTEGER NOT NULL,
      imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )`),
  ]);
}

async function importRelations(followerValues: string[], followingValues: string[]) {
  const followers = new Set(followerValues.map(cleanUsername).filter(Boolean));
  const following = new Set(followingValues.map(cleanUsername).filter(Boolean));
  const usernames = [...new Set([...followers, ...following])];
  const batchId = crypto.randomUUID();

  for (let offset = 0; offset < usernames.length; offset += 40) {
    const statements = usernames.slice(offset, offset + 40).map((username) => {
      const followsYou = followers.has(username) ? 1 : 0;
      const youFollow = following.has(username) ? 1 : 0;
      const reviewAfter = youFollow && !followsYou ? new Date().toISOString() : null;
      return env.DB.prepare(`INSERT INTO growth_targets
        (external_id, username, display_name, platform, profile_url, source, interactions, score,
         follows_you, you_follow, previous_follows_you, relation_batch, review_after, updated_at)
        VALUES (?, ?, ?, 'Instagram', ?, 'open_source_agent', 0, 35, ?, ?, NULL, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(username) DO UPDATE SET
          previous_follows_you = growth_targets.follows_you,
          follows_you = excluded.follows_you,
          you_follow = excluded.you_follow,
          relation_batch = excluded.relation_batch,
          unfollowed_you_at = CASE
            WHEN growth_targets.follows_you = 1 AND excluded.follows_you = 0 THEN CURRENT_TIMESTAMP
            WHEN excluded.follows_you = 1 THEN NULL
            ELSE growth_targets.unfollowed_you_at
          END,
          review_after = CASE
            WHEN excluded.you_follow = 1 AND excluded.follows_you = 0
              THEN COALESCE(growth_targets.review_after, excluded.review_after)
            ELSE NULL
          END,
          updated_at = CURRENT_TIMESTAMP`)
        .bind(
          `ig:${username}`,
          username,
          username,
          `https://www.instagram.com/${username}/`,
          followsYou,
          youFollow,
          batchId,
          reviewAfter,
        );
    });
    if (statements.length) await env.DB.batch(statements);
  }

  await env.DB.prepare(`INSERT OR IGNORE INTO follower_events
    (external_id, username, event_type, batch_id)
    SELECT external_id, username, 'unfollowed', ? FROM growth_targets
    WHERE relation_batch = ? AND previous_follows_you = 1 AND follows_you = 0`)
    .bind(batchId, batchId).run();
  await env.DB.prepare(`INSERT OR IGNORE INTO follower_events
    (external_id, username, event_type, batch_id)
    SELECT external_id, username, 'unfollowed', ? FROM growth_targets
    WHERE follows_you = 1 AND COALESCE(relation_batch, '') <> ?`)
    .bind(batchId, batchId).run();
  await env.DB.prepare(`UPDATE growth_targets SET
    previous_follows_you = follows_you,
    follows_you = 0,
    relation_batch = ?,
    unfollowed_you_at = CURRENT_TIMESTAMP,
    updated_at = CURRENT_TIMESTAMP
    WHERE follows_you = 1 AND COALESCE(relation_batch, '') <> ?`)
    .bind(batchId, batchId).run();
  await env.DB.prepare(`INSERT INTO relation_imports
    (batch_id, followers_count, following_count) VALUES (?, ?, ?)`)
    .bind(batchId, followers.size, following.size).run();

  return { followers, following };
}

async function importCandidates(candidates: DiscoveryCandidate[], followers: Set<string>, following: Set<string>) {
  const usable = candidates.filter((candidate) => {
    const username = cleanUsername(candidate.username ?? "");
    const followerCount = Math.max(0, Math.round(candidate.followerCount ?? 0));
    const followingCount = Math.max(0, Math.round(candidate.followingCount ?? 0));
    const mediaCount = Math.max(0, Math.round(candidate.mediaCount ?? 0));
    const ratio = followingCount / Math.max(followerCount, 1);
    return username
      && !followers.has(username)
      && !following.has(username)
      && candidate.italianSignal === true
      && candidate.femaleSelfDeclared === true
      && mediaCount >= 3
      && followingCount >= 50
      && !(followerCount > 10_000 && ratio < 0.5)
      && !(followerCount > 500 && ratio < 0.2);
  }).slice(0, 200);

  for (let offset = 0; offset < usable.length; offset += 40) {
    const statements = usable.slice(offset, offset + 40).map((candidate) => {
      const username = cleanUsername(candidate.username);
      const score = Math.max(0, Math.min(100, Math.round(candidate.score ?? 50)));
      return env.DB.prepare(`INSERT INTO growth_targets
        (external_id, username, display_name, platform, profile_url, source, source_detail,
         interactions, score, follower_count, following_count, media_count, is_private,
         last_post_at, activity_score, italian_signal, female_self_declared, follows_you, you_follow, updated_at)
        VALUES (?, ?, ?, 'Instagram', ?, 'open_source_discovery', ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, CURRENT_TIMESTAMP)
        ON CONFLICT(username) DO UPDATE SET
          display_name = excluded.display_name,
          profile_url = excluded.profile_url,
          source = excluded.source,
          source_detail = excluded.source_detail,
          score = excluded.score,
          follower_count = excluded.follower_count,
          following_count = excluded.following_count,
          media_count = excluded.media_count,
          is_private = excluded.is_private,
          last_post_at = excluded.last_post_at,
          activity_score = excluded.activity_score,
          italian_signal = excluded.italian_signal,
          female_self_declared = excluded.female_self_declared,
          follows_you = 0,
          you_follow = 0,
          updated_at = CURRENT_TIMESTAMP`)
        .bind(
          candidate.externalId || `ig:${username}`,
          username,
          candidate.displayName || username,
          `https://www.instagram.com/${username}/`,
          candidate.sourceDetail || candidate.reason || "scoperta automatica",
          score,
          Math.max(0, Math.round(candidate.followerCount ?? 0)),
          Math.max(0, Math.round(candidate.followingCount ?? 0)),
          Math.max(0, Math.round(candidate.mediaCount ?? 0)),
          candidate.isPrivate == null ? null : candidate.isPrivate ? 1 : 0,
          candidate.lastPostAt ?? null,
          Math.max(0, Math.min(100, Math.round(candidate.activityScore ?? 0))),
          candidate.italianSignal == null ? null : candidate.italianSignal ? 1 : 0,
          candidate.femaleSelfDeclared == null ? null : candidate.femaleSelfDeclared ? 1 : 0,
        );
    });
    if (statements.length) await env.DB.batch(statements);
  }
  return usable.length;
}

export async function POST(request: Request) {
  const expected = process.env.ORBIT_AGENT_TOKEN ?? "";
  const provided = request.headers.get("authorization")?.replace(/^Bearer\s+/i, "") ?? "";
  if (!expected || !provided || !(await sameSecret(provided, expected))) {
    return Response.json({ error: "Agente non autorizzato" }, { status: 401 });
  }

  const body = await request.json() as {
    followers?: string[];
    following?: string[];
    candidates?: DiscoveryCandidate[];
    username?: string;
  };
  if (!Array.isArray(body.followers) || !Array.isArray(body.following)) {
    return Response.json({ error: "Liste follower/seguiti mancanti" }, { status: 400 });
  }
  if (body.followers.length > 100_000 || body.following.length > 100_000) {
    return Response.json({ error: "Snapshot troppo grande" }, { status: 413 });
  }

  await ensureTables();
  const relationResult = await importRelations(body.followers, body.following);
  const candidates = await importCandidates(
    Array.isArray(body.candidates) ? body.candidates : [],
    relationResult.followers,
    relationResult.following,
  );
  await env.DB.prepare(`INSERT INTO audit_events (event_type, payload)
    VALUES ('open_source_instagram_sync', ?)`)
    .bind(JSON.stringify({
      username: cleanUsername(body.username ?? ""),
      followers: relationResult.followers.size,
      following: relationResult.following.size,
      candidates,
    })).run();

  return Response.json({
    ok: true,
    followers: relationResult.followers.size,
    following: relationResult.following.size,
    candidates,
  });
}
