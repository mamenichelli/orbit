export const dynamic = "force-dynamic";

const permissions = [
  "pages_show_list", "pages_read_engagement", "pages_manage_posts",
  "pages_manage_engagement", "read_insights", "instagram_basic",
  "instagram_manage_insights", "instagram_manage_comments", "instagram_content_publish",
];

function base64Url(bytes: Uint8Array) {
  let value = "";
  for (const byte of bytes) value += String.fromCharCode(byte);
  return btoa(value).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

async function signedState() {
  const secret = process.env.META_OAUTH_STATE_SECRET;
  if (!secret) throw new Error("META_OAUTH_STATE_SECRET non configurato");
  const payload = `${Date.now()}.${crypto.randomUUID()}`;
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"],
  );
  const signature = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(payload));
  return `${payload}.${base64Url(new Uint8Array(signature))}`;
}

export async function GET(request: Request) {
  const appId = process.env.META_APP_ID;
  const redirectUri = process.env.META_REDIRECT_URI;
  const graphVersion = process.env.META_GRAPH_VERSION ?? "v25.0";
  if (!appId || !redirectUri) return Response.redirect(new URL("/?meta=not-configured", request.url));

  const state = await signedState();

  const authorize = new URL(`https://www.facebook.com/${graphVersion}/dialog/oauth`);
  authorize.searchParams.set("client_id", appId);
  authorize.searchParams.set("redirect_uri", redirectUri);
  authorize.searchParams.set("state", state);
  authorize.searchParams.set("scope", permissions.join(","));
  authorize.searchParams.set("response_type", "code");
  return Response.redirect(authorize);
}
