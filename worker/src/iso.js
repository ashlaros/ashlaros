/**
 * iso.ashlaros.download - the ISO downloads.
 *
 * The listing is the bucket, not a manifest the publish job has to keep in
 * step: a page rendered from R2 cannot show an image that is not there, or
 * miss one that is.
 */

import { escapeHtml, html, humanSize, page } from './serve.js';

const TITLE = 'AshlarOS';

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
            )}</span><span>${humanSize(o.size)}</span></a>`,
        )
        .join('\n');
      return `<h2>${escapeHtml(version)}</h2>\n${rows}`;
    })
    .join('\n');

  return page(
    TITLE,
    `      <p>The newest image is always at
        <a href="/latest/ashlaros.iso"><code>/latest/ashlaros.iso</code></a>.
        Verify a download against the <code>SHA256SUMS</code> beside it.</p>
${sections || '<p>No images published yet.</p>'}`,
  );
}

export const site = {
  bucket: 'ISO',
  isListing: (key) => key === '',

  // no arch trees here: every key is <version>/<file>, and an unknown one
  // simply misses in the bucket
  resolveKey: (path) => path,

  listing: async (bucket) => {
    const listed = await bucket.list({ limit: 1000 });
    const byVersion = new Map();
    for (const object of listed.objects) {
      const version = versionOf(object.key);
      // latest/ is an alias of an image already listed under its version
      if (!version || version === 'latest') continue;
      if (!byVersion.has(version)) byVersion.set(version, []);
      byVersion.get(version).push(object);
    }
    return html(renderIndex(byVersion));
  },

  headers: (key) => {
    const headers = {
      // a versioned image never changes; latest/ is repointed every release
      'cache-control':
        versionOf(key) === 'latest'
          ? 'no-cache'
          : 'public, max-age=31536000, immutable',
    };
    if (key.endsWith('.iso')) {
      // browsers otherwise try to render several gigabytes of ISO
      headers['content-disposition'] = `attachment; filename="${key.split('/').pop()}"`;
    }
    return headers;
  },
};
