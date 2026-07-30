import { env } from "cloudflare:workers";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const mode = url.searchParams.get("hub.mode");
  const token = url.searchParams.get("hub.verify_token");
  const challenge = url.searchParams.get("hub.challenge");
  if (mode === "subscribe" && token === process.env.META_WEBHOOK_VERIFY_TOKEN && challenge) {
    return new Response(challenge);
  }
  return new Response("Forbidden", { status: 403 });
}

export async function POST(request: Request) {
  const payload = await request.text();
  await env.DB.prepare("INSERT INTO audit_events (event_type, payload) VALUES ('meta_webhook', ?)")
    .bind(payload.slice(0, 100_000)).run();
  return new Response("EVENT_RECEIVED");
}
