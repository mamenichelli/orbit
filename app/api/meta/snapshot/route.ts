export const dynamic = "force-dynamic";

export async function GET() {
  const gateway = process.env.ORBIT_GATEWAY_URL ?? "https://orbit-meta-webhook.l3gan.chatgpt.site";
  const apiKey = process.env.ORBIT_INTERNAL_API_KEY;
  if (!apiKey) {
    return Response.json({ error: "Sincronizzazione non configurata" }, { status: 503 });
  }

  try {
    const response = await fetch(`${gateway}/api/orbit/snapshot`, {
      headers: { authorization: `Bearer ${apiKey}`, accept: "application/json" },
      cache: "no-store",
    });
    const body = await response.text();
    return new Response(body, {
      status: response.status,
      headers: {
        "content-type": response.headers.get("content-type") ?? "application/json; charset=utf-8",
        "cache-control": "no-store",
      },
    });
  } catch {
    return Response.json({ error: "Gateway Meta temporaneamente non raggiungibile" }, { status: 502 });
  }
}
