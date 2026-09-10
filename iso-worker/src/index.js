/**
 * Serves the AshlarOS ISOs from R2, with a listing per version.
 *
 * The listing is the bucket, not a manifest the publish job has to keep in
 * step: a page rendered from R2 cannot show an image that is not there, or
 * miss one that is.
 */

import { FAVICON } from './favicon.js';

const TITLE = 'AshlarOS';

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

/**
 * The version prefix a key belongs to.
 *
 * upload_iso.py writes <version>/<name>.iso and latest/ashlaros.iso, so the
 * first segment is the version and `latest` is an alias rather than one.
 */
export function versionOf(key) {
  const cut = key.indexOf('/');
  return cut === -1 ? null : key.slice(0, cut);
}

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
.row {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.15rem 0;
  font-family: monospace;
}
.row:hover { color: #c9ccd1; }
.meta { color: #8a8f98; }
p { color: #8a8f98; font-size: 0.85rem; }
code { font-family: monospace; color: #c9ccd1; }
`;

export function renderIndex(byVersion) {
  // version prefixes sort chronologically, so the newest is last
  const versions = [...byVersion.keys()].sort().reverse();
  const sections = versions
    .map((version) => {
      const rows = byVersion
        .get(version)
        .map(
          (o) =>
            `<a class="row" href="/${escapeHtml(o.key)}"><span>${escapeHtml(
              o.key.slice(version.length + 1),
            )}</span><span class="meta">${humanSize(o.size)}</span></a>`,
        )
        .join('\n');
      return `<h2>${escapeHtml(version)}</h2>\n${rows}`;
    })
    .join('\n');

  return `<!DOCTYPE html>
<html lang="en">
  <head>
    <title>${TITLE}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <link rel="icon" href="/favicon.svg" type="image/svg+xml" />
    <style>${STYLE}</style>
  </head>
  <body>
    <h1>${TITLE}</h1>
    <main>
      <p>The newest image is always at
        <a href="/latest/ashlaros.iso"><code>/latest/ashlaros.iso</code></a>.
        Verify a download against the <code>SHA256SUMS</code> beside it.</p>
${sections || '<p>No images published yet.</p>'}
    </main>
  </body>
</html>
`;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const key = decodeURIComponent(url.pathname.slice(1));

    if (request.method !== 'GET' && request.method !== 'HEAD') {
      return new Response('method not allowed', { status: 405 });
    }

    if (key === 'favicon.svg' || key === 'favicon.ico') {
      return new Response(FAVICON, {
        headers: {
          'content-type': 'image/svg+xml',
          'cache-control': 'public, max-age=86400',
        },
      });
    }

    if (key === '') {
      const listed = await env.BUCKET.list({ limit: 1000 });
      const byVersion = new Map();
      for (const object of listed.objects) {
        const version = versionOf(object.key);
        // latest/ is an alias of an image already listed under its version
        if (!version || version === 'latest') continue;
        if (!byVersion.has(version)) byVersion.set(version, []);
        byVersion.get(version).push(object);
      }
      return new Response(renderIndex(byVersion), {
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
    // a versioned image never changes; latest/ is repointed on every release
    headers.set(
      'cache-control',
      versionOf(key) === 'latest'
        ? 'no-cache'
        : 'public, max-age=31536000, immutable',
    );
    if (key.endsWith('.iso')) {
      // browsers otherwise try to render several gigabytes of ISO
      headers.set('content-disposition', `attachment; filename="${key.split('/').pop()}"`);
    }

    const status = object.body ? (request.headers.get('range') ? 206 : 200) : 304;
    return new Response(request.method === 'HEAD' ? null : object.body, {
      status,
      headers,
    });
  },
};
