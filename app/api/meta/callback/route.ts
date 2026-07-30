import { env } from "cloudflare:workers";
import { cookies } from "next/headers";
import { encryptMetaToken } from "../../../../lib/meta-crypto";

export const dynamic = "force-dynamic";

type MetaPage = {
  id: string;
  name: string;
  access_token: string;
  instagram_business_account?: { id: string; username?: string };
};

async function metaJson<T>(url: URL): Promise<T> {
  const response = await fetch(url);
  const body = await response.json() as T & { error?: { message?: string } };
  if (!response.ok || body.error) throw new Error(body.error?.message ?? "Errore Meta API");
  return body;
}

export async function GET(request: Request) {
  const requestUrl = new URL(request.url);
  const code = requestUrl.searchParams.get("code");
  const state = requestUrl.searchParams.get("state");
  const cookieStore = await cookies();
  const expectedState = cookieStore.get("orbit_meta_oauth_state")?.value;
  cookieStore.delete("orbit_meta_oauth_state");
  if (!code || !state || !expectedState || state !== expectedState) {
    return Response.redirect(new URL("/?meta=invalid-state", request.url));
  }

  const appId = process.env.META_APP_ID;
  const appSecret = process.env.META_APP_SECRET;
  const redirectUri = process.env.META_REDIRECT_URI;
  const graphVersion = process.env.META_GRAPH_VERSION ?? "v25.0";
  if (!appId || !appSecret || !redirectUri) {
    return Response.redirect(new URL("/?meta=not-configured", request.url));
  }

  try {
    const tokenUrl = new URL(`https://graph.facebook.com/${graphVersion}/oauth/access_token`);
    tokenUrl.searchParams.set("client_id", appId);
    tokenUrl.searchParams.set("client_secret", appSecret);
    tokenUrl.searchParams.set("redirect_uri", redirectUri);
    tokenUrl.searchParams.set("code", code);
    const shortToken = await metaJson<{ access_token: string }>(tokenUrl);

    const longTokenUrl = new URL(`https://graph.facebook.com/${graphVersion}/oauth/access_token`);
    longTokenUrl.searchParams.set("grant_type", "fb_exchange_token");
    longTokenUrl.searchParams.set("client_id", appId);
    longTokenUrl.searchParams.set("client_secret", appSecret);
    longTokenUrl.searchParams.set("fb_exchange_token", shortToken.access_token);
    const longToken = await metaJson<{ access_token: string }>(longTokenUrl);

    const accountsUrl = new URL(`https://graph.facebook.com/${graphVersion}/me/accounts`);
    accountsUrl.searchParams.set("fields", "id,name,access_token,instagram_business_account{id,username}");
    accountsUrl.searchParams.set("access_token", longToken.access_token);
    const accounts = await metaJson<{ data: MetaPage[] }>(accountsUrl);

    await env.DB.prepare(`CREATE TABLE IF NOT EXISTS social_accounts (
      id INTEGER PRIMARY KEY AUTOINCREMENT, platform TEXT NOT NULL,
      external_id TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL, username TEXT,
      page_id TEXT, token_ciphertext TEXT NOT NULL, token_iv TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'connected',
      connected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )`).run();

    for (const page of accounts.data) {
      const encrypted = await encryptMetaToken(page.access_token);
      await env.DB.prepare(`INSERT INTO social_accounts
        (platform, external_id, display_name, page_id, token_ciphertext, token_iv)
        VALUES ('facebook', ?, ?, ?, ?, ?)
        ON CONFLICT(external_id) DO UPDATE SET display_name=excluded.display_name,
        token_ciphertext=excluded.token_ciphertext, token_iv=excluded.token_iv,
        status='connected', updated_at=CURRENT_TIMESTAMP`)
        .bind(page.id, page.name, page.id, encrypted.ciphertext, encrypted.iv).run();

      if (page.instagram_business_account) {
        const instagram = page.instagram_business_account;
        await env.DB.prepare(`INSERT INTO social_accounts
          (platform, external_id, display_name, username, page_id, token_ciphertext, token_iv)
          VALUES ('instagram', ?, ?, ?, ?, ?, ?)
          ON CONFLICT(external_id) DO UPDATE SET display_name=excluded.display_name,
          username=excluded.username, page_id=excluded.page_id,
          token_ciphertext=excluded.token_ciphertext, token_iv=excluded.token_iv,
          status='connected', updated_at=CURRENT_TIMESTAMP`)
          .bind(instagram.id, instagram.username ?? page.name, instagram.username ?? null,
            page.id, encrypted.ciphertext, encrypted.iv).run();
      }
    }
    return Response.redirect(new URL("/?meta=connected", request.url));
  } catch (error) {
    console.error("Meta OAuth callback failed", error);
    return Response.redirect(new URL("/?meta=connection-failed", request.url));
  }
}
