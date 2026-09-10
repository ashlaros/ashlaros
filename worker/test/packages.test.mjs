/**
 * What the packages site serves, and what it refuses.
 *
 * The routes here are the ones a pacman client depends on: an arch-keyed
 * database, the packages it names, and the signing key a machine needs
 * before it can install the keyring package.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';

import worker from '../src/index.js';
import { resolveKey } from '../src/packages.js';
import { bucketOf, get } from './helpers.mjs';

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

const env = () => ({ PACKAGES: bucketOf(KEYS), ISO: bucketOf([]) });
const req = (path) => get('packages.ashlaros.download', path);

test('both architecture trees are served', async () => {
  for (const arch of ['x86_64', 'aarch64']) {
    const res = await worker.fetch(req(`${arch}/ashlaros.db.tar.gz`), env());
    assert.equal(res.status, 200, arch);
  }
});

test('a path naming no known tree is refused without touching the bucket', async () => {
  // a typo'd $arch must not become a bucket listing: R2 would answer with
  // an empty page, which reads to a client as an empty repository rather
  // than a misconfiguration
  let listed = false;
  const bucket = bucketOf(KEYS);
  const spy = {
    PACKAGES: {
      ...bucket,
      list: async (...args) => {
        listed = true;
        return bucket.list(...args);
      },
    },
    ISO: bucketOf([]),
  };
  const res = await worker.fetch(req('x86_64_v3/ashlaros.db.tar.gz'), spy);
  assert.equal(res.status, 404);
  assert.equal(listed, false);
});

test('the signing key is fetchable, because trusting it precedes installing anything', async () => {
  const res = await worker.fetch(req('ashlaros.gpg'), env());
  assert.equal(res.status, 200);
  assert.equal(res.headers.get('content-type'), 'application/pgp-keys');
});

test('packages are immutable, the database is not', async () => {
  // a cached database is a client that cannot see a package published
  // since; a re-fetched package is bandwidth spent on bytes that cannot
  // have changed
  const pkg = await worker.fetch(req('x86_64/swayr-0.27.3-1-x86_64.pkg.tar.zst'), env());
  assert.match(pkg.headers.get('cache-control'), /immutable/);

  const db = await worker.fetch(req('x86_64/ashlaros.db.tar.gz'), env());
  assert.equal(db.headers.get('cache-control'), 'no-cache');

  // Arch Linux ARM compresses with xz, and an xz package is no less
  // immutable than a zst one - its version is in its filename either way
  const xz = await worker.fetch(req('aarch64/idlehack-0.r21-1-aarch64.pkg.tar.xz'), env());
  assert.match(xz.headers.get('cache-control'), /immutable/);
});

test('a range request is answered as a range', async () => {
  const request = new Request('https://packages.ashlaros.download/x86_64/ashlaros.db.tar.gz', {
    headers: { range: 'bytes=0-3' },
  });
  const res = await worker.fetch(request, env());
  assert.equal(res.status, 206);
});

test('an absent object is 404, not an empty 200', async () => {
  const res = await worker.fetch(req('x86_64/nothing-here.pkg.tar.zst'), env());
  assert.equal(res.status, 404);
});

test('a write method is refused', async () => {
  const request = new Request('https://packages.ashlaros.download/x86_64/ashlaros.db.tar.gz', {
    method: 'DELETE',
  });
  const res = await worker.fetch(request, env());
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
  const res = await worker.fetch(req('x86_64/'), env());
  const body = await res.text();
  assert.match(body, /href="\/x86_64\/ashlaros\.db\.tar\.gz"/);
  // the parent link from a tree root goes to the bucket root, which lists
  // the trees
  assert.match(body, /href="\/"/);
});
