export const dynamic = "force-dynamic";

function bytesToBase64Url(bytes: Uint8Array) {
  let value = "";
  for (const byte of bytes) value += String.fromCharCode(byte);
  return btoa(value).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

async function createAccessToken(secret: string) {
  const timestamp = String(Date.now());
  const nonce = crypto.randomUUID();
  const payload = `${timestamp}.${nonce}`;
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signature = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(payload));
  return `${payload}.${bytesToBase64Url(new Uint8Array(signature))}`;
}

export async function GET() {
  const gateway = process.env.ORBIT_GATEWAY_URL ?? "https://orbit-meta-webhook.l3gan.chatgpt.site";
  const apiKey = process.env.ORBIT_INTERNAL_API_KEY;
  if (!apiKey) {
    return Response.json({ error: "Sincronizzazione non configurata" }, { status: 503 });
  }

  return Response.json({
    gatewayUrl: `${gateway}/api/orbit/snapshot`,
    accessToken: await createAccessToken(apiKey),
    expiresIn: 120,
  }, {
    headers: { "cache-control": "no-store" },
  });
}
