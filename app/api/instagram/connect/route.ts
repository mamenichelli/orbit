export const dynamic = "force-dynamic";

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
  const appId = process.env.INSTAGRAM_APP_ID ?? process.env.META_APP_ID;
  const redirectUri = process.env.INSTAGRAM_REDIRECT_URI
    ?? "https://orbit-meta-webhook.l3gan.chatgpt.site/api/instagram/callback";
  if (!appId) return Response.redirect(new URL("/?instagram=not-configured", request.url));

  const authorize = new URL("https://www.instagram.com/oauth/authorize");
  authorize.searchParams.set("client_id", appId);
  authorize.searchParams.set("redirect_uri", redirectUri);
  authorize.searchParams.set("response_type", "code");
  authorize.searchParams.set(
    "scope",
    [
      "instagram_business_basic",
      "instagram_business_manage_comments",
      "instagram_business_manage_messages",
      "instagram_business_manage_insights",
      "instagram_business_content_publish",
    ].join(","),
  );
  authorize.searchParams.set("state", await signedState());
  authorize.searchParams.set("enable_fb_login", "0");
  authorize.searchParams.set("force_authentication", "1");
  return Response.redirect(authorize);
}
