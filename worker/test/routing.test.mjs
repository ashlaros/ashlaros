/**
 * The two sites share a script, so the thing worth pinning is that they
 * stay apart: one hostname must never read the other's bucket, and one
 * site's rules must never apply to the other's objects.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';

import worker, { isDocsHost, siteFor } from '../src/index.js';
import { site as isoSite } from '../src/iso.js';
import { site as packagesSite } from '../src/packages.js';
import { bucketOf, get } from './helpers.mjs';

const PACKAGE_KEYS = ['x86_64/ashlaros.db.tar.gz', 'ashlaros.gpg'];
const ISO_KEYS = ['2026.09.10/ashlaros-2026.09.10-x86_64.iso', 'latest/ashlaros.iso'];

const env = () => ({ PACKAGES: bucketOf(PACKAGE_KEYS), ISO: bucketOf(ISO_KEYS) });

test('each hostname reaches its own site', () => {
  assert.equal(siteFor('packages.ashlaros.download'), packagesSite);
  assert.equal(siteFor('iso.ashlaros.download'), isoSite);
});

test('an unknown hostname serves the repository rather than guessing', () => {
  // `wrangler dev` and workers.dev carry neither name; the repository is
  // the safe default because its keys are validated before any bucket read
  assert.equal(siteFor('ashlaros-web.workers.dev'), packagesSite);
});

test('the iso host cannot read the packages bucket', async () => {
  // sharing a script must not share buckets: each site names its own
  // binding, so a key that exists in the other one still misses
  const res = await worker.fetch(get('iso.ashlaros.download', 'x86_64/ashlaros.db.tar.gz'), env());
  assert.equal(res.status, 404);
});

test('the packages host cannot read the iso bucket', async () => {
  const res = await worker.fetch(
    get('packages.ashlaros.download', '2026.09.10/ashlaros-2026.09.10-x86_64.iso'),
    env(),
  );
  assert.equal(res.status, 404);
});

test("the packages site's signing-key route does not exist on the iso host", async () => {
  const onPackages = await worker.fetch(get('packages.ashlaros.download', 'ashlaros.gpg'), env());
  assert.equal(onPackages.status, 200);

  const onIso = await worker.fetch(get('iso.ashlaros.download', 'ashlaros.gpg'), env());
  assert.equal(onIso.status, 404);
});

test('the root of each host renders that host\'s own index', async () => {
  const packages = await worker.fetch(get('packages.ashlaros.download', ''), env());
  assert.match(await packages.text(), /x86_64/);

  const iso = await worker.fetch(get('iso.ashlaros.download', ''), env());
  const body = await iso.text();
  assert.match(body, /latest\/ashlaros\.iso/);
  assert.doesNotMatch(body, /x86_64\/ashlaros\.db/);
});

test('the apex serves the landing page, not a bucket', async () => {
  // the assets binding answers it; if the apex ever fell through to a site
  // handler it would expose bucket keys under the marketing hostname
  let asked;
  const withDocs = {
    ...env(),
    DOCS: { fetch: (request) => ((asked = request.url), new Response('<h1>AshlarOS</h1>')) },
  };

  const res = await worker.fetch(get('ashlaros.download', ''), withDocs);
  assert.match(await res.text(), /AshlarOS/);
  assert.equal(asked, 'https://ashlaros.download/');

  // a key that exists in a bucket is still the landing page here
  const key = await worker.fetch(get('ashlaros.download', 'x86_64/ashlaros.db.tar.gz'), withDocs);
  assert.match(await key.text(), /AshlarOS/);
});

test('only the apex is the docs host', () => {
  assert.ok(isDocsHost('ashlaros.download'));
  assert.ok(isDocsHost('www.ashlaros.download'));
  assert.ok(!isDocsHost('packages.ashlaros.download'));
  assert.ok(!isDocsHost('iso.ashlaros.download'));
});

test('the favicon is served on both hosts', async () => {
  for (const host of ['packages.ashlaros.download', 'iso.ashlaros.download']) {
    const res = await worker.fetch(get(host, 'favicon.svg'), env());
    assert.equal(res.status, 200, host);
    assert.equal(res.headers.get('content-type'), 'image/svg+xml');
  }
});
