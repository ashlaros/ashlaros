/**
 * Serves the AshlarOS pacman repository from R2, with directory listings.
 *
 * R2 has no directories: a listing is a delimited list() over the key
 * prefix. Object reads stream straight through, so pacman gets plain bytes
 * with working range requests.
 */

import { FAVICON } from './favicon.js';

const REPO_NAME = 'ashlaros';

// The two trees the publish workflow writes. Anything else is a typo, and
// answering 404 for it is cheaper than a bucket round trip.
const ARCHES = ['x86_64', 'aarch64'];

const escapeHtml = (s) => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

function humanSize(bytes) {
  const units = ['B', 'KiB', 'MiB', 'GiB'];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${unit === 0 ? value : value.toFixed(1)} ${units[unit]}`;
}

export function renderListing(prefix, dirs, files) {
  const parent = prefix.replace(/[^/]+\/$/, '');
  const rows = [
    prefix ? `<tr><td><a href="/${escapeHtml(parent)}">../</a></td><td></td><td></td></tr>` : '',
    ...dirs.map(
      (d) =>
        `<tr><td><a href="/${escapeHtml(d)}">${escapeHtml(
          d.slice(prefix.length),
        )}</a></td><td></td><td></td></tr>`,
    ),
    ...files.map(
      (f) =>
        `<tr><td><a href="/${escapeHtml(f.key)}">${escapeHtml(
          f.key.slice(prefix.length),
        )}</a></td><td>${humanSize(f.size)}</td><td>${escapeHtml(
          new Date(f.uploaded).toISOString().slice(0, 16).replace('T', ' '),
        )}</td></tr>`,
    ),
  ].join('\n');

  return `<!DOCTYPE html>
<html lang="en">
  <head>
    <title>${escapeHtml(prefix || REPO_NAME)}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <link rel="icon" href="/favicon.svg" type="image/svg+xml" />
    <style>
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
      table { margin: 20px; border-collapse: collapse; font-family: monospace; }
      td { padding: 2px 20px 2px 0; white-space: nowrap; }
      td:not(:first-child) { color: #8a8f98; }
      a:hover { color: #c9ccd1; }
    </style>
  </head>
  <body>
    <h1>${escapeHtml(prefix ? `${REPO_NAME}/${prefix}` : REPO_NAME)}</h1>
    <table>
${rows}
    </table>
  </body>
</html>
`;
}

/**
 * The stored key a request path refers to, or null if it names no tree.
 *
 * Clients configure `Server = https://.../$arch`, so every real request
 * carries an architecture as its first segment. The root is allowed so the
 * listing has somewhere to start.
 */
export function resolveKey(path) {
  if (path === '') return '';
  const [arch] = path.split('/');
  return ARCHES.includes(arch) ? path : null;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const requested = decodeURIComponent(url.pathname.slice(1));

    if (request.method !== 'GET' && request.method !== 'HEAD') {
      return new Response('method not allowed', { status: 405 });
    }

    if (requested === 'favicon.svg' || requested === 'favicon.ico') {
      // .ico callers accept an svg body, so one file serves both
      return new Response(FAVICON, {
        headers: {
          'content-type': 'image/svg+xml',
          'cache-control': 'public, max-age=86400',
        },
      });
    }

    // the signing key, so a new machine can trust the repository before it
    // can install the keyring package the repository serves
    if (requested === 'ashlaros.gpg') {
      const key = await env.BUCKET.get('ashlaros.gpg');
      if (!key) return new Response('not found', { status: 404 });
      return new Response(key.body, {
        headers: {
          'content-type': 'application/pgp-keys',
          'cache-control': 'public, max-age=3600',
        },
      });
    }

    const key = resolveKey(requested);
    if (key === null) return new Response('not found', { status: 404 });

    if (key === '' || key.endsWith('/')) {
      const listed = await env.BUCKET.list({ prefix: key, delimiter: '/' });
      const files = listed.objects.filter((o) => o.key !== key);
      if (!files.length && !listed.delimitedPrefixes.length) {
        return new Response('not found', { status: 404 });
      }
      return new Response(renderListing(key, listed.delimitedPrefixes, files), {
        headers: { 'content-type': 'text/html; charset=utf-8' },
      });
    }

    const object = await env.BUCKET.get(key, {
      range: request.headers,
      onlyIf: request.headers,
    });
    if (!object) return new Response('not found', { status: 404 });

    const headers = new Headers();
    object.writeHttpMetadata(headers);
    headers.set('etag', object.httpEtag);
    // a package is immutable once published - its version is in its name -
    // but the database is rewritten in place on every publish
    headers.set(
      'cache-control',
      key.endsWith('.pkg.tar.zst')
        ? 'public, max-age=31536000, immutable'
        : 'no-cache',
    );

    const status = object.body ? (request.headers.get('range') ? 206 : 200) : 304;
    return new Response(request.method === 'HEAD' ? null : object.body, {
      status,
      headers,
    });
  },
};
