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
  '2026.09.10/ashlaros-2026.09.10-aarch64-rpi5.img.xz',
  'latest/ashlaros.iso',
  'latest/ashlaros-rpi5.img.xz',
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

test('a version offers the PC and Pi images as separate things', () => {
  // an x86_64 ISO on a Pi is not a slower download, it is the wrong file,
  // and one undifferentiated list is how someone takes it (#29)
  const byVersion = new Map([
    [
      '2026.09.13',
      [
        { key: '2026.09.13/ashlaros-2026.09.13-x86_64.iso', size: 1 },
        { key: '2026.09.13/SHA256SUMS', size: 1 },
        { key: '2026.09.13/ashlaros-2026.09.13-aarch64-rpi5.img.xz', size: 1 },
        { key: '2026.09.13/SHA256SUMS.ashlaros-2026.09.13-aarch64-rpi5.img.xz', size: 1 },
      ],
    ],
  ]);
  // from the version heading down: the intro paragraph above names both
  // machines too, and asserting over the whole page would pass on that
  const listing = renderIndex(byVersion).split('<h2>').pop();

  assert.match(listing, /PC \(x86_64\)/);
  assert.match(listing, /Raspberry Pi 5/);
  // the PC heading comes first, and each image sits under its own
  assert.ok(listing.indexOf('PC (x86_64)') < listing.indexOf('Raspberry Pi 5'));
  assert.ok(
    listing.indexOf('x86_64.iso') < listing.indexOf('Raspberry Pi 5'),
    'the ISO belongs above the Pi heading',
  );
  // a checksum belongs with what it checksums, not in a list of its own
  assert.ok(
    listing.indexOf('SHA256SUMS.ashlaros-2026.09.13-aarch64') >
      listing.indexOf('Raspberry Pi 5'),
    "the image's checksum belongs under the Pi heading",
  );
});

test('a version with only an ISO shows no Raspberry Pi heading', () => {
  const listing = renderIndex(
    new Map([['2026.08.01', [{ key: '2026.08.01/ashlaros-2026.08.01-x86_64.iso', size: 1 }]]]),
  )
    .split('<h2>')
    .pop();
  assert.doesNotMatch(listing, /Raspberry Pi/);
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

test('a media file carries the length and range support a player needs', async () => {
  // a <video> probes with HEAD before it will play: no content-length and
  // no accept-ranges reads as "cannot seek", and the element fails the
  // load with a format error even though the bytes are perfect
  const res = await worker.fetch(req('latest/video/tour.webm'), env(), {});
  assert.equal(res.status, 200);
  assert.equal(res.headers.get('accept-ranges'), 'bytes');
  assert.equal(res.headers.get('content-length'), '334986');
});

test('a ranged request reports which bytes it answered with', async () => {
  // the versioned key, because latest/ is a pointer now and answers 302
  const request = new Request(
    'https://iso.ashlaros.download/2026.09.10/ashlaros-2026.09.10-x86_64.iso',
    { headers: { range: 'bytes=100-199' } },
  );
  const res = await worker.fetch(request, env(), {});
  assert.equal(res.status, 206);
  assert.equal(res.headers.get('content-range'), 'bytes 100-199/334986');
  assert.equal(res.headers.get('content-length'), '100');
});

test('latest is a redirect to the versioned image, not the image', async () => {
  // It used to be a full server-side copy - 1.7 GB duplicated per release,
  // and repointed underneath anyone downloading it. A pointer plus a 302
  // sends the client to an immutable versioned URL instead.
  const res = await worker.fetch(req('latest/ashlaros.iso'), env());
  assert.equal(res.status, 302);
  assert.equal(
    res.headers.get('location'),
    '/2026.09.10/ashlaros-2026.09.10-x86_64.iso',
  );
  // a cached hop would pin every visitor to whichever release they first saw
  assert.match(res.headers.get('cache-control'), /no-cache/);
});

test('the pi alias redirects to its own versioned name, not the iso one', async () => {
  const res = await worker.fetch(req('latest/ashlaros-rpi5.img.xz'), env());
  assert.equal(res.status, 302);
  assert.equal(
    res.headers.get('location'),
    '/2026.09.10/ashlaros-2026.09.10-aarch64-rpi5.img.xz',
  );
});

test('a resumed download across a new release restarts instead of splicing', async () => {
  // The versioned object is immutable, so this is the guarantee that
  // survives: a validator that no longer matches drops the range rather
  // than handing back the tail of a different file to append.
  const stale = new Request(
    'https://iso.ashlaros.download/2026.09.10/ashlaros-2026.09.10-x86_64.iso',
    { headers: { range: 'bytes=1000-2000', 'if-range': '"an-older-release"' } },
  );
  const res = await worker.fetch(stale, env());
  assert.equal(res.status, 200);
  assert.equal(res.headers.get('content-range'), null);
});

test('a resumed download of an unchanged object still resumes', async () => {
  const current = new Request(
    'https://iso.ashlaros.download/2026.09.10/ashlaros-2026.09.10-x86_64.iso',
    { headers: { range: 'bytes=1000-2000', 'if-range': '"e"' } },
  );
  const res = await worker.fetch(current, env());
  assert.equal(res.status, 206);
  assert.match(res.headers.get('content-range'), /^bytes 1000-2000\//);
});

test('the index lists every version, not just the first page', async () => {
  // R2 caps a list at 1000 keys and lists lexically, so `latest/` sorts
  // last: without pagination the screenshots and the tour are the first
  // things to disappear, then the newest releases.
  const many = [];
  for (let i = 0; i < 400; i += 1) {
    const v = `2026.01.${String(i).padStart(3, '0')}`;
    many.push(`${v}/ashlaros-${v}-x86_64.iso`, `${v}/SHA256SUMS`, `${v}/SHA256SUMS.sig`);
  }
  many.push('latest/ashlaros.iso', 'latest/screenshots/desktop.png');

  const bucket = bucketOf(many);
  const res = await worker.fetch(req(''), { PACKAGES: bucketOf([]), ISO: bucket });
  const body = await res.text();
  // the last version lexically, which is exactly what a truncated listing loses
  assert.match(body, /2026\.01\.399/);
  assert.match(body, /screenshots\/desktop\.png/);
});
