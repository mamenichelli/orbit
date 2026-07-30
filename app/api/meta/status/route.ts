export async function GET() {
  return Response.json({
    configured: Boolean(process.env.META_APP_ID && process.env.META_APP_SECRET),
    oauthReady: true,
    passwordStorage: false,
    platforms: ["instagram", "facebook"],
  });
}
