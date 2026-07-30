import { cookies } from "next/headers";

export const dynamic = "force-dynamic";

const permissions = [
  "pages_show_list", "pages_read_engagement", "pages_manage_posts",
  "pages_manage_engagement", "read_insights", "instagram_basic",
  "instagram_manage_insights", "instagram_manage_comments", "instagram_content_publish",
];

export async function GET(request: Request) {
  const appId = process.env.META_APP_ID;
  const redirectUri = process.env.META_REDIRECT_URI;
  const graphVersion = process.env.META_GRAPH_VERSION ?? "v25.0";
  if (!appId || !redirectUri) return Response.redirect(new URL("/?meta=not-configured", request.url));

  const state = crypto.randomUUID();
  const cookieStore = await cookies();
  cookieStore.set("orbit_meta_oauth_state", state, {
    httpOnly: true, secure: true, sameSite: "lax", maxAge: 600, path: "/",
  });

  const authorize = new URL(`https://www.facebook.com/${graphVersion}/dialog/oauth`);
  authorize.searchParams.set("client_id", appId);
  authorize.searchParams.set("redirect_uri", redirectUri);
  authorize.searchParams.set("state", state);
  authorize.searchParams.set("scope", permissions.join(","));
  authorize.searchParams.set("response_type", "code");
  return Response.redirect(authorize);
}
