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
import { geo } from './geo.js';
import { archiveMonth, closedMonth } from './stats.js';
// the Durable Object class has to be exported from the entrypoint for
// wrangler to bind it
export { Verifier } from './game/scores.js';
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
  /**
   * Fold the month that just closed into kv, before analytics engine
   * forgets it - it retains three months, kv keeps this for good.
   *
   * The month comes from the trigger time rather than from "now", so a
   * late or re-run invocation archives the same month instead of drifting
   * onto the wrong one.
   */
  async scheduled(event, env, ctx) {
    if (!env.ANALYTICS_TOKEN || !env.STATS) return;
    ctx.waitUntil(archiveMonth(env, closedMonth(event.scheduledTime)));
  },

  fetch(request, env, ctx) {
    const { hostname, pathname } = new URL(request.url);
    // Ahead of the docs binding, which otherwise answers for the whole
    // apex. The desktop reads this instead of telling a third party its
    // IP address; nothing about the request is logged or stored.
    if (isDocsHost(hostname) && pathname === '/geo') return geo(request);
    // The game page is a docs asset, so its own fetches go to the apex -
    // and the docs binding would answer 404 for all of them, which the
    // page reads as being offline. Same reasoning as /geo above: the
    // route has to run before the binding claims the whole host.
    if (isDocsHost(hostname) && pathname.startsWith('/game/')) {
      const route = isoSite.routes?.[pathname.slice(1)];
      if (route) return route(request, env[isoSite.bucket], env, new URL(request.url));
    }
    if (isDocsHost(hostname)) return env.DOCS.fetch(request);
    return handler(siteFor(hostname))(request, env, ctx);
  },
};
