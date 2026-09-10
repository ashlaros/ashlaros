/**
 * What the ISO worker serves.
 *
 * The load-bearing behaviours are: an ISO downloads rather than renders,
 * a resumed download works, and `latest/` is never cached as if it were
 * immutable - a stale `latest` hands out last month's image forever.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';

import worker, { renderIndex, versionOf } from '../src/index.js';

const KEYS = [
  '2026.09.10/ashlaros-2026.09.10-x86_64.iso',
  '2026.09.10/SHA256SUMS',
  '2026.08.01/ashlaros-2026.08.01-x86_64.iso',
  'latest/ashlaros.iso',
];

function env(keys) {
  return {
    BUCKET: {
      list: async () => ({
        objects: keys.map((key) => ({ key, size: 2_000_000_000, uploaded: new Date(0) })),
        delimitedPrefixes: [],
      }),
      get: async (k) =>
        keys.includes(k)
          ? { body: 'bytes', writeHttpMetadata: () => {}, httpEtag: '"e"' }
          : null,
    },
  };
}

const get = (path) => new Request(`https://iso.ashlaros.download/${path}`);

test('an iso is offered as a download, not rendered', async () => {
  const res = await worker.fetch(get('2026.09.10/ashlaros-2026.09.10-x86_64.iso'), env(KEYS));
  assert.equal(res.status, 200);
  assert.match(res.headers.get('content-disposition'), /attachment/);
});

test('latest is never cached as immutable', async () => {
  // an immutable latest/ would keep handing out the image that happened to
  // be current when a cache first saw it
  const latest = await worker.fetch(get('latest/ashlaros.iso'), env(KEYS));
  assert.equal(latest.headers.get('cache-control'), 'no-cache');

  const versioned = await worker.fetch(
    get('2026.09.10/ashlaros-2026.09.10-x86_64.iso'),
    env(KEYS),
  );
  assert.match(versioned.headers.get('cache-control'), /immutable/);
});

test('a range request is answered as a range, so a download resumes', async () => {
  const request = new Request(
    'https://iso.ashlaros.download/2026.09.10/ashlaros-2026.09.10-x86_64.iso',
    { headers: { range: 'bytes=1000-2000' } },
  );
  const res = await worker.fetch(request, env(KEYS));
  assert.equal(res.status, 206);
});

test('an absent image is 404', async () => {
  const res = await worker.fetch(get('2027.01.01/nope.iso'), env(KEYS));
  assert.equal(res.status, 404);
});

test('the index lists newest first and does not repeat latest as a version', async () => {
  const res = await worker.fetch(get(''), env(KEYS));
  const body = await res.text();
  assert.ok(
    body.indexOf('2026.09.10') < body.indexOf('2026.08.01'),
    'newest version should come first',
  );
  // latest/ is an alias of an image already listed under its own version
  assert.doesNotMatch(body, /<h2>latest<\/h2>/);
  assert.match(body, /href="\/latest\/ashlaros\.iso"/);
});

test('versionOf reads the prefix, and rejects a bare key', () => {
  assert.equal(versionOf('2026.09.10/x.iso'), '2026.09.10');
  assert.equal(versionOf('latest/ashlaros.iso'), 'latest');
  assert.equal(versionOf('stray.iso'), null);
});

test('an empty bucket renders a page rather than failing', () => {
  assert.match(renderIndex(new Map()), /No images published yet/);
});
