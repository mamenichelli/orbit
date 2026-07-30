export async function GET() {
  const redirectUri = process.env.META_REDIRECT_URI ?? null;
  return Response.json({
    configured: Boolean(
      process.env.META_APP_ID &&
      process.env.META_APP_SECRET &&
      process.env.META_TOKEN_ENCRYPTION_KEY &&
      redirectUri
    ),
    oauthReady: true,
    passwordStorage: false,
    redirectUri,
    graphVersion: process.env.META_GRAPH_VERSION ?? "v25.0",
    platforms: ["instagram", "facebook"],
  });
}
