import { defineMiddleware } from 'astro:middleware';

/**
 * When the site is mounted at a subpath (e.g. anshumanbuilds.dev/beacon),
 * Vercel rewrites the apex request upstream to the beacon project's
 * *.vercel.app URL. Astro/Starlight issue 3xx redirects with absolute
 * Location headers pointing at the upstream origin, which would leak the
 * *.vercel.app URL into the user's address bar. We rewrite those Location
 * headers back to the apex origin so the browser stays on
 * anshumanbuilds.dev/beacon.
 *
 * No-op when the site is mounted at root (BASE_PATH is "/" or empty).
 */
const UPSTREAM_HOST_RE = /\.(?:vercel\.app|vercel\.sh|now\.sh)$/i;

export const onRequest = defineMiddleware(async (context, next) => {
  const response = await next();

  const base = import.meta.env.BASE_URL.replace(/\/$/, '');
  if (!base) return response;

  const location = response.headers.get('Location');
  if (!location) return response;

  try {
    const target = new URL(location);
    if (!UPSTREAM_HOST_RE.test(target.hostname)) return response;

    const headers = new Headers(response.headers);
    headers.set(
      'Location',
      context.url.origin + target.pathname + target.search + target.hash,
    );
    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers,
    });
  } catch {
    return response;
  }
});