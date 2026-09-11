/**
 * iso.ashlaros.download - the ISO downloads.
 *
 * The listing is the bucket, not a manifest the publish job has to keep in
 * step: a page rendered from R2 cannot show an image that is not there, or
 * miss one that is.
 */

import { escapeHtml, html, humanSize, json, page } from './serve.js';
import { collect, record } from './stats.js';

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
        Verify a download against the <code>SHA256SUMS</code> beside it.
        <a class="link" href="/stats">Download stats</a>.</p>
${sections || '<p>No images published yet.</p>'}`,
  );
}

const countRow = (label, href, downloads) =>
  `<tr><td>${href ? `<a href="${href}">${escapeHtml(label)}</a>` : escapeHtml(label)}` +
  `</td><td>${downloads.toLocaleString('en-US')}</td></tr>`;

export function renderStats({ configured, archive, versions, files, version }) {
  const parts = [];

  if (!configured) {
    // public page: say what is true rather than answer 500, which reads as
    // "the numbers are broken" when it means "no read token yet"
    parts.push(
      '<p>Live stats are not configured yet. Downloads are still being counted,' +
        ' and any archived months appear below.</p>',
    );
  } else {
    parts.push('<h2>Last three months</h2>');
    parts.push(
      versions.length
        ? `<table>${versions
            .map((row) =>
              countRow(
                row.alias === 'latest' ? 'latest (unpinned)' : row.version,
                row.alias === 'latest' ? null : `/stats?version=${encodeURIComponent(row.version)}`,
                row.downloads,
              ),
            )
            .join('')}</table>`
        : '<p>No downloads recorded yet.</p>',
    );
  }

  if (files) {
    parts.push(`<h2>${escapeHtml(version)}</h2>`);
    parts.push(
      files.length
        ? `<table>${files.map((row) => countRow(row.name, null, row.downloads)).join('')}</table>`
        : '<p>No downloads recorded for this version.</p>',
    );
  }

  for (const { month, totals } of archive) {
    const rows = Object.entries(totals).sort((a, b) => b[1] - a[1]);
    parts.push(`<h2>${escapeHtml(month)}</h2>`);
    parts.push(
      rows.length
        ? `<table>${rows.map(([name, n]) => countRow(name, null, n)).join('')}</table>`
        : '<p>No downloads that month.</p>',
    );
  }

  parts.push(
    '<p>A download is one whole-image GET that transferred.' +
      ' Resumed downloads and revalidations are not counted, and neither is' +
      ' <code>SHA256SUMS</code>. Images taken from <code>/latest/</code> carry no' +
      ' version in their URL, so they are counted as their own row rather than' +
      ' attributed to whichever image was newest.' +
      ' <a class="link" href="/stats.json">stats.json</a></p>',
  );

  return page(TITLE, parts.join('\n'));
}

export const site = {
  bucket: 'ISO',
  isListing: (key) => key === '',

  // no arch trees here: every key is <version>/<file>, and an unknown one
  // simply misses in the bucket
  resolveKey: (path) => path,

  // only this site counts: every `pacman -Sy` is a database fetch, and
  // that event volume would dwarf the signal on the packages side
  record,

  routes: {
    stats: async (request, bucket, env, url) =>
      html(renderStats(await collect(env, url.searchParams.get('version')))),
    'stats.json': async (request, bucket, env, url) =>
      json(await collect(env, url.searchParams.get('version'))),
  },

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
