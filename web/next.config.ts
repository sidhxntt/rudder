import type { NextConfig } from "next";

/**
 * The control plane. Same host in dev, a different one behind a reverse proxy
 * later; either way the browser never learns the address.
 */
const controlPlane = process.env.RUDDER_API_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  reactStrictMode: true,

  /**
   * Everything `lib/api.ts` calls is under `/api`, and this sends it to the
   * control plane.
   *
   * It is not decoration. The control plane mounts no CORS middleware, so a
   * browser fetch from :3000 to :8000 is cross-origin and the response cannot
   * be read — ports are not part of a *site*, which is why the `SameSite=Lax`
   * session cookie is happy, but they are part of an *origin*, which is what
   * CORS keys on. Proxying makes every call same-origin: the `rudder_token`
   * cookie is sent automatically, no preflight happens, and the JWT never has
   * to touch `localStorage`.
   *
   * SSE passes through this rewrite unbuffered — the control plane already
   * sends `Cache-Control: no-transform` and `X-Accel-Buffering: no`.
   */
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${controlPlane}/:path*` }];
  },
};

export default nextConfig;
