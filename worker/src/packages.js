/**
 * packages.ashlaros.download - the pacman repository.
 */

import { escapeHtml, html, humanSize, notFound, page } from './serve.js';

const TITLE = 'ashlaros';

// The two trees the publish workflow writes. Anything else is a typo, and
// answering 404 for it is cheaper than a bucket round trip.
const ARCHES = ['x86_64', 'aarch64'];

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

  return page(prefix ? `${TITLE}/${prefix}` : TITLE, `<table>\n${rows}\n</table>`);
}

export const site = {
  bucket: 'PACKAGES',
  isListing: (key) => key === '' || key.endsWith('/'),

  resolveKey,

  routes: {
    // the signing key, so a new machine can trust the repository before it
    // can install the keyring package the repository serves
    'ashlaros.gpg': async (request, bucket) => {
      const key = await bucket.get('ashlaros.gpg');
      if (!key) return notFound();
      return new Response(key.body, {
        headers: {
          'content-type': 'application/pgp-keys',
          'cache-control': 'public, max-age=3600',
        },
      });
    },
  },

  listing: async (bucket, key) => {
    const listed = await bucket.list({ prefix: key, delimiter: '/' });
    const files = listed.objects.filter((o) => o.key !== key);
    if (!files.length && !listed.delimitedPrefixes.length) return notFound();
    return html(renderListing(key, listed.delimitedPrefixes, files));
  },

  headers: (key) => ({
    // a package is immutable once published - its version is in its name -
    // but the database is rewritten in place on every publish. .zst comes
    // from Arch, .xz from Arch Linux ARM.
    'cache-control': /\.pkg\.tar\.(zst|xz)$/.test(key)
      ? 'public, max-age=31536000, immutable'
      : 'no-cache',
  }),
};
