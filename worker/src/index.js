/**
 * One worker for both of AshlarOS's public buckets.
 *
 * They serve the same shape - stream an R2 object, render a listing, share
 * one stylesheet and favicon - and differ only in which bucket, how a key
 * is validated, how the index looks, and what may be cached. Those four
 * differences are the site definitions in ./packages.js and ./iso.js;
 * everything else lives once in ./serve.js.
 *
 * Routing is by hostname, because that is what already distinguishes them:
 * both custom domains point at this script, and each binding names its own
 * bucket, so neither site can read the other's.
 */

import { handler } from './serve.js';
import { site as isoSite } from './iso.js';
import { site as packagesSite } from './packages.js';

const SITES = {
  'packages.ashlaros.download': packagesSite,
  'iso.ashlaros.download': isoSite,
};

// The apex is the landing page, which is not a bucket at all: it is the
// docs/ directory, bound as static assets and served by the runtime.
const DOCS_HOST = 'ashlaros.download';

// `wrangler dev` and a workers.dev URL carry none of these hostnames;
// serving the repository there keeps the common case working without
// pretending an unknown host is one of ours.
const DEFAULT_SITE = packagesSite;

export function siteFor(hostname) {
  return SITES[hostname] ?? DEFAULT_SITE;
}

export function isDocsHost(hostname) {
  return hostname === DOCS_HOST || hostname === `www.${DOCS_HOST}`;
}

export default {
  fetch(request, env, ctx) {
    const { hostname } = new URL(request.url);
    if (isDocsHost(hostname)) return env.DOCS.fetch(request);
    return handler(siteFor(hostname))(request, env, ctx);
  },
};
