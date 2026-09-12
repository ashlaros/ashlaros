/**
 * What the ISO site serves.
 *
 * The load-bearing behaviours are: an ISO downloads rather than renders,
 * a resumed download works, and `latest/` is never cached as if it were
 * immutable - a stale `latest` hands out last month's image forever.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';

import worker from '../src/index.js';
import { renderIndex, versionOf } from '../src/iso.js';
import { bucketOf, get } from './helpers.mjs';

const KEYS = [
  '2026.09.10/ashlaros-2026.09.10-x86_64.iso',
  '2026.09.10/SHA256SUMS',
  '2026.08.01/ashlaros-2026.08.01-x86_64.iso',
  'latest/ashlaros.iso',
  'latest/screenshots/desktop.png',
  'latest/screenshots/tiling.png',
  'latest/video/tour.webm',
];

const env = () => ({ PACKAGES: bucketOf([]), ISO: bucketOf(KEYS) });
const req = (path) => get('iso.ashlaros.download', path);

test('an iso is offered as a download, not rendered', async () => {
  const res = await worker.fetch(req('2026.09.10/ashlaros-2026.09.10-x86_64.iso'), env());
  assert.equal(res.status, 200);
  assert.match(res.headers.get('content-disposition'), /attachment/);
});

test('latest is never cached as immutable', async () => {
  // an immutable latest/ would keep handing out the image that happened to
  // be current when a cache first saw it
  const latest = await worker.fetch(req('latest/ashlaros.iso'), env());
  assert.equal(latest.headers.get('cache-control'), 'no-cache');

  const versioned = await worker.fetch(
    req('2026.09.10/ashlaros-2026.09.10-x86_64.iso'),
    env(),
  );
  assert.match(versioned.headers.get('cache-control'), /immutable/);
});

test('a range request is answered as a range, so a download resumes', async () => {
  const request = new Request(
    'https://iso.ashlaros.download/2026.09.10/ashlaros-2026.09.10-x86_64.iso',
    { headers: { range: 'bytes=1000-2000' } },
  );
  const res = await worker.fetch(request, env());
  assert.equal(res.status, 206);
});

test('an absent image is 404', async () => {
  const res = await worker.fetch(req('2027.01.01/nope.iso'), env());
  assert.equal(res.status, 404);
});

test('the index lists newest first and does not repeat latest as a version', async () => {
  const res = await worker.fetch(req(''), env());
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

test('a screenshot is shown as a picture, never offered as a download', async () => {
  // the index lists what is in the bucket, and the screenshots live in it -
  // without this they read as things to download beside the images
  const body = await (await worker.fetch(req(''), env())).text();
  assert.match(body, /<img class="shot" src="\/latest\/screenshots\/desktop\.png"/);
  assert.doesNotMatch(body, /class="row" href="\/latest\/screenshots/);
});

test('a screenshot renders in the browser rather than downloading', async () => {
  // content-disposition: attachment is right for a 2 GB image and wrong for
  // a picture the README points at
  const res = await worker.fetch(req('latest/screenshots/desktop.png'), env());
  assert.equal(res.status, 200);
  assert.equal(res.headers.get('content-disposition'), null);
});

test('a screenshot is revalidated, like everything else under latest/', async () => {
  // republished in place by every screenshot run, so an immutable cache
  // would pin the first one a cache happened to see
  const res = await worker.fetch(req('latest/screenshots/desktop.png'), env());
  assert.equal(res.headers.get('cache-control'), 'no-cache');
});

test('the tour plays on the page and is never a download row', async () => {
  // same rule as the stills: the listing skips latest/ entirely, so a video
  // there has to be rendered deliberately or it is invisible
  const body = await (await worker.fetch(req(''), env())).text();
  assert.match(body, /<video class="tour" src="\/latest\/video\/tour\.webm"/);
  assert.doesNotMatch(body, /class="row" href="\/latest\/video/);
});

test('the tour is not preloaded for every visitor', async () => {
  // a few hundred KB on a download page that most visitors never play
  const body = await (await worker.fetch(req(''), env())).text();
  assert.match(body, /preload="metadata"/);
});

test('the tour serves as video, not as an attachment', async () => {
  const res = await worker.fetch(req('latest/video/tour.webm'), env());
  assert.equal(res.status, 200);
  assert.equal(res.headers.get('content-disposition'), null);
  // republished by every recording run, so an immutable cache would pin
  // whichever one a cache happened to see first
  assert.equal(res.headers.get('cache-control'), 'no-cache');
});
