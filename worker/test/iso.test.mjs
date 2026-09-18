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
import { renderIndex, site as isoSite, versionOf } from '../src/iso.js';
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

test('a versioned image is redirected to the bucket that serves it', async () => {
  // Gigabytes no longer stream through an invocation billed per request.
  // What the worker still owes the client is the right target: the same
  // key on the bucket's own hostname.
  //
  // content-disposition moved with it - upload_iso.py stores it on the
  // object, because the bucket hostname serves the object's own metadata
  // and knows nothing about this handler.
  const res = await worker.fetch(req('2026.09.10/ashlaros-2026.09.10-x86_64.iso'), env());
  assert.equal(res.status, 302);
  assert.equal(
    res.headers.get('location'),
    'https://dl.ashlaros.download/2026.09.10/ashlaros-2026.09.10-x86_64.iso',
  );
});

test('latest is never cached as immutable', async () => {
  // an immutable latest/ would keep handing out the image that happened to
  // be current when a cache first saw it
  const latest = await worker.fetch(req('latest/ashlaros.iso'), env());
  assert.equal(latest.headers.get('cache-control'), 'no-cache');
});

test('the alias is served here and the version is not', async () => {
  // latest/ is a pointer this worker reads and answers with its own 302 to
  // the versioned object, so a resumed download aims at an immutable URL.
  // Redirecting the pointer to the bucket instead would hand the client
  // the moving target. The screenshots under latest/ are republished in
  // place, so they stay here too.
  assert.equal(isoSite.direct('latest/ashlaros.iso'), null);
  assert.equal(isoSite.direct('latest/screenshots/desktop.png'), null);
  assert.match(
    isoSite.direct('2026.09.10/ashlaros-2026.09.10-x86_64.iso'),
    /^https:\/\/dl\.ashlaros\.download\//,
  );
});

test('a resumed download is redirected too, not streamed from here', async () => {
  // A resume is the case worth handing off: excluding it would send a
  // partial multi-gigabyte transfer back through the worker, which is the
  // whole cost this redirect exists to avoid. The bucket hostname answers
  // ranges natively, so the client gets its 206 from there.
  const request = new Request(
    'https://ashlaros.download/iso/2026.09.10/ashlaros-2026.09.10-x86_64.iso',
    { headers: { range: 'bytes=1000-2000' } },
  );
  const res = await worker.fetch(request, env());
  assert.equal(res.status, 302);
  assert.match(res.headers.get('location'), /^https:\/\/dl\.ashlaros\.download\//);
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
  assert.match(body, /href="\/iso\/latest\/ashlaros\.iso"/);
});

test('an alias key holding a whole image is refused, not read', async () => {
  // The bug this defends: latest/ashlaros.iso was still the 1.98 GB image
  // it used to be a copy of, and reading it as a pointer killed the
  // isolate - Cloudflare error 1101, a 500 on the download link. A body
  // too large to be a version string is never read.
  const bucket = bucketOf(KEYS);
  const huge = {
    ...(await bucket.get('latest/ashlaros.iso')),
    size: 1_978_718_208,
    text: async () => {
      throw new Error('a whole image must never be read as a pointer');
    },
  };
  const env = { ISO: { ...bucket, get: async () => huge }, ANALYTICS_ENGINE: null };
  const res = await worker.fetch(get('iso.ashlaros.download', 'latest/ashlaros.iso'), env);
  assert.equal(res.status, 404);
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

test('a screenshot is never offered as a download row', async () => {
  // the page no longer shows the stills, but they are still in the bucket
  // under latest/ - and latest/ is skipped, so they must not appear as
  // rows either
  const body = await (await worker.fetch(req(''), env())).text();
  assert.doesNotMatch(body, /class="row" href="\/latest\/screenshots/);
  assert.doesNotMatch(body, /class="shot"/);
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

test('the tour is neither shown nor offered as a download row', async () => {
  // the page shows no media at all now, and latest/ is skipped by the
  // listing - a regression that started listing it would put the video
  // back as a row, which is the failure worth catching
  const body = await (await worker.fetch(req(''), env())).text();
  assert.doesNotMatch(body, /<video/);
  assert.doesNotMatch(body, /class="row" href="\/latest\/video/);
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
  // R2 reports a range for a full read too, so keying off the object
  // answered 206 to every plain GET - which RFC 9110 does not allow
  // without a request range
  assert.equal(res.headers.get('content-range'), null);
});

test('a ranged request reports which bytes it answered with', async () => {
  // Something the worker still streams: a versioned image hops to the
  // bucket, latest/ is a pointer, and the media under latest/ is what is
  // left being served from here.
  const request = new Request('https://ashlaros.download/iso/latest/video/tour.webm', {
    headers: { range: 'bytes=100-199' },
  });
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
    '/iso/2026.09.10/ashlaros-2026.09.10-x86_64.iso',
  );
  // a cached hop would pin every visitor to whichever release they first saw
  assert.match(res.headers.get('cache-control'), /no-cache/);
});

test('the pi alias redirects to its own versioned name, not the iso one', async () => {
  const res = await worker.fetch(req('latest/ashlaros-rpi5.img.xz'), env());
  assert.equal(res.status, 302);
  assert.equal(
    res.headers.get('location'),
    '/iso/2026.09.10/ashlaros-2026.09.10-aarch64-rpi5.img.xz',
  );
});

test('a resume against a stale validator restarts instead of splicing', async () => {
  // R2 does not apply If-Range itself - a stale validator still came back
  // 206 - so serve.js evaluates it and drops the range. It matters for
  // whatever is still served from here: the media under latest/ is
  // republished in place, and a client resuming across a republish would
  // otherwise stitch bytes from two different files.
  const stale = new Request('https://ashlaros.download/iso/latest/video/tour.webm', {
    headers: { range: 'bytes=1000-2000', 'if-range': '"an-older-recording"' },
  });
  const res = await worker.fetch(stale, env());
  assert.equal(res.status, 200);
  assert.equal(res.headers.get('content-range'), null);
});

test('a resume against an unchanged object still resumes', async () => {
  const current = new Request('https://ashlaros.download/iso/latest/video/tour.webm', {
    headers: { range: 'bytes=1000-2000', 'if-range': '"e"' },
  });
  const res = await worker.fetch(current, env());
  assert.equal(res.status, 206);
  assert.match(res.headers.get('content-range'), /^bytes 1000-2000\//);
});

test('the index lists every version, not just the first page', async () => {
  // R2 caps a list at 1000 keys and lists lexically, so a truncated
  // listing loses whatever sorts last - and with 400 versions of three
  // files each, that is 1200 keys and the newest releases are what goes.
  const many = [];
  for (let i = 0; i < 400; i += 1) {
    const v = `2026.01.${String(i).padStart(3, '0')}`;
    many.push(`${v}/ashlaros-${v}-x86_64.iso`, `${v}/SHA256SUMS`, `${v}/SHA256SUMS.sig`);
  }
  many.push('latest/ashlaros.iso');

  const bucket = bucketOf(many);
  const res = await worker.fetch(req(''), { PACKAGES: bucketOf([]), ISO: bucket });
  const body = await res.text();
  // the last version lexically, which is exactly what a truncated listing
  // loses - and the first one, to prove the walk did not simply start late
  assert.match(body, /2026\.01\.399/);
  assert.match(body, /2026\.01\.000/);
});
