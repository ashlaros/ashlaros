/**
 * What the worker serves, and what it refuses.
 *
 * The routes here are the ones a pacman client depends on: an arch-keyed
 * database, the packages it names, and the signing key a machine needs
 * before it can install the keyring package.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';

import worker, { resolveKey } from '../src/index.js';

const KEYS = [
  'x86_64/ashlaros.db.tar.gz',
  'x86_64/ashlaros.db',
  'x86_64/ashlaros-settings-20260910-1-any.pkg.tar.zst',
  'x86_64/swayr-0.27.3-1-x86_64.pkg.tar.zst',
  'aarch64/ashlaros.db.tar.gz',
  'aarch64/ashlaros-settings-20260910-1-any.pkg.tar.zst',
  'aarch64/idlehack-0.r21-1-aarch64.pkg.tar.xz',
  'ashlaros.gpg',
];

function env(keys) {
  return {
    BUCKET: {
      list: async ({ prefix, delimiter }) => {
        const under = keys.filter((k) => k.startsWith(prefix));
        const dirs = new Set();
        const objects = [];
        for (const k of under) {
          const rest = k.slice(prefix.length);
          const cut = rest.indexOf(delimiter);
          if (cut >= 0) dirs.add(prefix + rest.slice(0, cut + 1));
          else objects.push({ key: k, size: 10, uploaded: new Date(0) });
        }
        return { objects, delimitedPrefixes: [...dirs] };
      },
      get: async (k) =>
        keys.includes(k)
          ? { body: 'bytes', writeHttpMetadata: () => {}, httpEtag: '"e"' }
          : null,
    },
  };
}

const get = (path) => new Request(`https://packages.ashlaros.download/${path}`);

test('both architecture trees are served', async () => {
  for (const arch of ['x86_64', 'aarch64']) {
    const res = await worker.fetch(get(`${arch}/ashlaros.db.tar.gz`), env(KEYS));
    assert.equal(res.status, 200, arch);
  }
});

test('a path naming no known tree is refused without touching the bucket', async () => {
  // a typo'd $arch must not become a bucket listing: R2 would answer with
  // an empty page, which reads to a client as an empty repository rather
  // than a misconfiguration
  let listed = false;
  const spy = {
    BUCKET: {
      list: async () => {
        listed = true;
        return { objects: [], delimitedPrefixes: [] };
      },
      get: async () => null,
    },
  };
  const res = await worker.fetch(get('x86_64_v3/ashlaros.db.tar.gz'), spy);
  assert.equal(res.status, 404);
  assert.equal(listed, false);
});

test('the signing key is fetchable, because trusting it precedes installing anything', async () => {
  const res = await worker.fetch(get('ashlaros.gpg'), env(KEYS));
  assert.equal(res.status, 200);
  assert.equal(res.headers.get('content-type'), 'application/pgp-keys');
});

test('packages are immutable, the database is not', async () => {
  // a cached database is a client that cannot see a package published
  // since; a re-fetched package is bandwidth spent on bytes that cannot
  // have changed
  const pkg = await worker.fetch(
    get('x86_64/swayr-0.27.3-1-x86_64.pkg.tar.zst'),
    env(KEYS),
  );
  assert.match(pkg.headers.get('cache-control'), /immutable/);

  const db = await worker.fetch(get('x86_64/ashlaros.db.tar.gz'), env(KEYS));
  assert.equal(db.headers.get('cache-control'), 'no-cache');

  // Arch Linux ARM compresses with xz, and an xz package is no less
  // immutable than a zst one - its version is in its filename either way
  const xz = await worker.fetch(get('aarch64/idlehack-0.r21-1-aarch64.pkg.tar.xz'), env(KEYS));
  assert.match(xz.headers.get('cache-control'), /immutable/);
});

test('a range request is answered as a range', async () => {
  const request = new Request('https://packages.ashlaros.download/x86_64/ashlaros.db.tar.gz', {
    headers: { range: 'bytes=0-3' },
  });
  const res = await worker.fetch(request, env(KEYS));
  assert.equal(res.status, 206);
});

test('an absent object is 404, not an empty 200', async () => {
  const res = await worker.fetch(get('x86_64/nothing-here.pkg.tar.zst'), env(KEYS));
  assert.equal(res.status, 404);
});

test('a write method is refused', async () => {
  const request = new Request('https://packages.ashlaros.download/x86_64/ashlaros.db.tar.gz', {
    method: 'DELETE',
  });
  const res = await worker.fetch(request, env(KEYS));
  assert.equal(res.status, 405);
});

test('resolveKey admits the tree roots and the bucket root, nothing else', () => {
  assert.equal(resolveKey(''), '');
  assert.equal(resolveKey('x86_64/'), 'x86_64/');
  assert.equal(resolveKey('aarch64/ashlaros.db'), 'aarch64/ashlaros.db');
  assert.equal(resolveKey('i686/ashlaros.db'), null);
  assert.equal(resolveKey('../secrets'), null);
});

test('a listing links to paths that resolve', async () => {
  const res = await worker.fetch(get('x86_64/'), env(KEYS));
  const body = await res.text();
  assert.match(body, /href="\/x86_64\/ashlaros\.db\.tar\.gz"/);
  // the parent link from a tree root goes to the bucket root, which lists
  // the trees
  assert.match(body, /href="\/"/);
});
