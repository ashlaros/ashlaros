/**
 * The two sites share a script and a hostname, so the thing worth pinning
 * is that they stay apart: one prefix must never read the other's bucket,
 * one site's rules must never apply to the other's objects, and neither
 * may swallow the static site.
 *
 * This replaced a file that tested the same separation by hostname, back
 * when packages. and iso. were their own domains.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';

import worker, { siteFor } from '../src/index.js';
import { site as isoSite } from '../src/iso.js';
import { site as packagesSite } from '../src/packages.js';
import { bucketOf, get } from './helpers.mjs';

const PACKAGE_KEYS = ['x86_64/ashlaros.db.tar.gz', 'ashlaros.gpg'];
const ISO_KEYS = ['2026.09.10/ashlaros-2026.09.10-x86_64.iso', 'latest/ashlaros.iso'];

const env = () => ({ PACKAGES: bucketOf(PACKAGE_KEYS), ISO: bucketOf(ISO_KEYS) });
const docs = () => ({
  ...env(),
  DOCS: { fetch: (request) => new Response(`docs:${new URL(request.url).pathname}`) },
});

test('each prefix reaches its own site', () => {
  assert.equal(siteFor('/packages/x86_64/ashlaros.db.tar.gz'), packagesSite);
  assert.equal(siteFor('/iso/latest/ashlaros.iso'), isoSite);
});

test('everything outside the two prefixes is the static site', () => {
  // including paths that merely start with the same letters: a page at
  // /packaging would otherwise be handed to the repository handler
  for (const path of ['/', '/privacy', '/terms', '/game/', '/packaging', '/isolation']) {
    assert.equal(siteFor(path), null, path);
  }
});

test('the iso prefix cannot read the packages bucket', async () => {
  // sharing a script must not share buckets: each site names its own
  // binding, so a key that exists in the other one still misses
  const res = await worker.fetch(get('iso.ashlaros.download', 'x86_64/ashlaros.db.tar.gz'), env());
  assert.equal(res.status, 404);
});

test('the packages prefix cannot read the iso bucket', async () => {
  const res = await worker.fetch(
    get('packages.ashlaros.download', '2026.09.10/ashlaros-2026.09.10-x86_64.iso'),
    env(),
  );
  assert.equal(res.status, 404);
});

test("the packages site's signing-key route does not exist under /iso", async () => {
  const onPackages = await worker.fetch(get('packages.ashlaros.download', 'ashlaros.gpg'), env());
  assert.equal(onPackages.status, 200);

  const onIso = await worker.fetch(get('iso.ashlaros.download', 'ashlaros.gpg'), env());
  assert.equal(onIso.status, 404);
});

test('the root of each prefix renders that site\'s own index', async () => {
  const packages = await worker.fetch(get('packages.ashlaros.download', ''), env());
  assert.match(await packages.text(), /x86_64/);

  const iso = await worker.fetch(get('iso.ashlaros.download', ''), env());
  const body = await iso.text();
  assert.match(body, /latest\/ashlaros\.iso/);
  assert.doesNotMatch(body, /x86_64\/ashlaros\.db/);
});

test('a bucket key at the apex is the landing page, not the object', async () => {
  // the assets binding answers everything outside the prefixes; if a
  // bucket key reached a site handler from the bare apex, the repository
  // would be readable at two different paths
  const res = await worker.fetch(get('ashlaros.download', 'x86_64/ashlaros.db.tar.gz'), docs());
  assert.match(await res.text(), /^docs:/);
});

test('the apex itself is the landing page', async () => {
  const res = await worker.fetch(get('ashlaros.download', ''), docs());
  assert.equal(await res.text(), 'docs:/');
});

test('the shared assets answer at the apex, where every page links them', async () => {
  // A listing under /packages/ links /site.css and /favicon.svg, not
  // /packages/site.css - so they have to resolve from the root, with no
  // docs binding needed to answer them
  for (const [path, type] of [
    ['site.css', 'text/css; charset=utf-8'],
    ['background.svg', 'image/svg+xml'],
    ['favicon.svg', 'image/svg+xml'],
    ['favicon.ico', 'image/svg+xml'],
  ]) {
    const res = await worker.fetch(get('ashlaros.download', path), env());
    assert.equal(res.status, 200, path);
    assert.equal(res.headers.get('content-type'), type, path);
  }
});

test('a shared asset is not also reachable under a prefix', async () => {
  // one URL per file: a second path would be a second thing to cache and
  // a second thing for a page to disagree about
  const res = await worker.fetch(get('packages.ashlaros.download', 'site.css'), env());
  assert.equal(res.status, 404);
});
