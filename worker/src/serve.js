/**
 * What serving a bucket over HTTP has in common, whichever bucket it is.
 *
 * R2 has no directories: a listing is a delimited list() over the key
 * prefix. Object reads stream straight through, so a client gets plain
 * bytes with working range requests.
 */

import { FAVICON } from './favicon.js';

export const escapeHtml = (s) => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

export function humanSize(bytes) {
  const units = ['B', 'KiB', 'MiB', 'GiB'];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${unit === 0 ? value : value.toFixed(1)} ${units[unit]}`;
}

/**
 * The design language from sway-repo/_layouts/default.html, with the
 * Manjaro green replaced by our stone accent. Both sites render with it,
 * which is the point of having one worker.
 */
const STYLE = `
* { color: #eee; text-decoration: none; }
body {
  background: #282828;
  margin: 0;
  font-family: Roboto, Helvetica, Arial, sans-serif;
}
h1 {
  background: #141a1b;
  color: #8a8f98;
  font-size: 0.8rem;
  font-weight: 500;
  line-height: 30px;
  padding: 0 20px;
  margin: 0;
}
main { margin: 20px; max-width: 60rem; }
h2 {
  color: #8a8f98;
  font-size: 0.8rem;
  font-weight: 500;
  margin: 1.6rem 0 0.3rem;
}
table { border-collapse: collapse; font-family: monospace; }
td { padding: 2px 20px 2px 0; white-space: nowrap; }
td:not(:first-child) { color: #8a8f98; }
.row {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.15rem 0;
  font-family: monospace;
}
a:hover, .row:hover { color: #c9ccd1; }
p { color: #8a8f98; font-size: 0.85rem; line-height: 1.6; }
code { font-family: monospace; color: #c9ccd1; }
`;

export function page(title, body) {
  return `<!DOCTYPE html>
<html lang="en">
  <head>
    <title>${escapeHtml(title)}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <link rel="icon" href="/favicon.svg" type="image/svg+xml" />
    <style>${STYLE}</style>
  </head>
  <body>
    <h1>${escapeHtml(title)}</h1>
    <main>
${body}
    </main>
  </body>
</html>
`;
}

export const html = (body) =>
  new Response(body, { headers: { 'content-type': 'text/html; charset=utf-8' } });

export const json = (body) =>
  new Response(`${JSON.stringify(body)}\n`, {
    headers: { 'content-type': 'application/json' },
  });

export const notFound = () => new Response('not found', { status: 404 });

/**
 * Stream one object, with the caching and headers the site asks for.
 *
 * Range and conditional requests are handed to R2 rather than reimplemented:
 * a resumed 1.7 GB ISO download depends on both.
 */
export async function serveObject(request, bucket, key, extraHeaders = {}) {
  const object = await bucket.get(key, {
    range: request.headers,
    onlyIf: request.headers,
  });
  if (!object) return notFound();

  const headers = new Headers();
  object.writeHttpMetadata(headers);
  headers.set('etag', object.httpEtag);
  for (const [name, value] of Object.entries(extraHeaders)) headers.set(name, value);

  const status = object.body ? (request.headers.get('range') ? 206 : 200) : 304;
  return new Response(request.method === 'HEAD' ? null : object.body, { status, headers });
}

/**
 * Turn a site definition into a fetch handler.
 *
 * A site supplies: `bucket` (the binding name), `title`, `resolveKey`,
 * `listing`, `headers`, and optionally `routes` for anything it serves
 * that is not a bucket object. A route is called with
 * (request, bucket, env, url).
 */
export function handler(site) {
  return async (request, env) => {
    if (request.method !== 'GET' && request.method !== 'HEAD') {
      return new Response('method not allowed', { status: 405 });
    }

    const url = new URL(request.url);
    const requested = decodeURIComponent(url.pathname.slice(1));
    const bucket = env[site.bucket];

    if (requested === 'favicon.svg' || requested === 'favicon.ico') {
      // .ico callers accept an svg body, so one file serves both
      return new Response(FAVICON, {
        headers: {
          'content-type': 'image/svg+xml',
          'cache-control': 'public, max-age=86400',
        },
      });
    }

    // (request, bucket, env, url) rather than just the bucket: /geo needs
    // request.cf, and a stats route would need env and the query. One
    // signature covering both beats each adding its own parameter.
    const route = site.routes?.[requested];
    if (route) return route(request, bucket, env, url);

    const key = site.resolveKey(requested);
    if (key === null) return notFound();

    if (site.isListing(key)) return site.listing(bucket, key);

    const response = await serveObject(request, bucket, key, site.headers(key));
    // after the response, because only its status says whether anything was
    // transferred. Optional and site-specific: the packages site defines no
    // record, so pacman traffic is never counted.
    site.record?.(env, key, response.status, request.method);
    return response;
  };
}
