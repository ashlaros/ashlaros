/**
 * /packages - the pacman repository.
 */

import { escapeHtml, html, humanSize, notFound, page } from './serve.js';

// The same shape every other page uses: the project, then what this page
// is. It was a bare lowercase "ashlaros", which named the repository but
// matched nothing else on the site and was indistinguishable from the ISO
// page in a tab.
const TITLE = 'AshlarOS — Packages';

// Every link this page writes is absolute from the apex, and the bucket
// keys know nothing about the prefix - so it is added on the way out, the
// same place the handler strips it on the way in.
const PREFIX = 'packages';
const href = (key) => `/${PREFIX}/${key}`;

// The two trees the publish workflow writes. Anything else is a typo, and
// answering 404 for it is cheaper than a bucket round trip.
const ARCHES = ['x86_64', 'aarch64'];

// The packages bucket's own custom domain. Object keys are the same there
// as through the worker - <arch>/<file> - so a redirect is a hostname
// swap, not a path rewrite.
const CDN = 'https://cdn.ashlaros.download';

/**
 * The stored key a request path refers to, or null if it names no tree.
 *
 * Clients configure `Server = https://ashlaros.download/packages/$arch`, so
 * every real request carries an architecture as its first segment once the
 * prefix is stripped. The root is allowed so the
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
    prefix
      ? `<tr><td><a href="${escapeHtml(href(parent))}">../</a></td><td></td><td></td></tr>`
      : '',
    ...dirs.map(
      (d) =>
        `<tr><td><a href="${escapeHtml(href(d))}">${escapeHtml(
          d.slice(prefix.length),
        )}</a></td><td></td><td></td></tr>`,
    ),
    ...files.map(
      (f) =>
        `<tr><td><a href="${escapeHtml(href(f.key))}">${escapeHtml(
          f.key.slice(prefix.length),
        )}</a></td><td>${humanSize(f.size)}</td><td>${escapeHtml(
          new Date(f.uploaded).toISOString().slice(0, 16).replace('T', ' '),
        )}</td></tr>`,
    ),
  ].join('\n');

  // the tree a listing is inside, after the page name rather than glued to
  // the project: "AshlarOS — Packages / x86_64/"
  return page(
    prefix ? `${TITLE} / ${prefix}` : TITLE,
    `<table>\n${rows}\n</table>`,
  );
}

export const site = {
  prefix: PREFIX,
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

  // Where a client can fetch this object without going through the worker.
  // run_worker_first means this worker is invoked for every request on
  // every route, so streaming a package spends an invocation on bytes that
  // cannot change. The bucket hostname has no worker in front of it: one
  // invocation for the hop, none for the transfer or a repeat fetch.
  //
  // Packages only, never their .sig: a signature is rewritten when a
  // package is republished at an unchanged version, so it is exactly the
  // file that must not come from a host that may hold an older copy - a
  // stale signature against a fresh package is "signature is invalid" on
  // the client. The database is rewritten on every publish for the same
  // reason and is likewise served here.
  direct: (key) =>
    /\.pkg\.tar\.(zst|xz)$/.test(key) ? `${CDN}/${encodeURI(key)}` : null,
};
