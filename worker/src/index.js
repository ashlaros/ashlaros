/**
 * One worker for both of AshlarOS's public buckets.
 *
 * They serve the same shape - stream an R2 object, render a listing, share
 * one stylesheet and favicon - and differ only in which bucket, how a key
 * is validated, how the index looks, and what may be cached. Those four
 * differences are the site definitions in ./packages.js and ./iso.js;
 * everything else lives once in ./serve.js.
 *
 * Routing is by path prefix under one hostname: /packages and /iso. It was
 * by hostname, which cost two custom domains, two origins for a stylesheet
 * to be fetched from, and a cross-origin link every time one page pointed
 * at another. Each binding still names its own bucket, so neither site can
 * read the other's.
 */

import { handler, sharedAsset } from './serve.js';
import { geo } from './geo.js';
import { archiveMonth, closedMonth } from './stats.js';
// the Durable Object class has to be exported from the entrypoint for
// wrangler to bind it
export { Verifier } from './game/scores.js';
import { site as isoSite } from './iso.js';
import { site as packagesSite } from './packages.js';

const SITES = {
  packages: packagesSite,
  iso: isoSite,
};

/**
 * Which site a path belongs to, or null for the docs.
 *
 * The first segment and nothing else: /packages/x86_64/... is the
 * repository, /iso/latest/... is the downloads, and everything else -
 * including /, /privacy and /game/ - is the static site.
 */
export function siteFor(pathname) {
  const [, first] = pathname.split('/');
  return SITES[first] ?? null;
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
    const { pathname } = new URL(request.url);

    // The stylesheet, its background and the favicon, which every page
    // links absolutely from the apex - so they answer the same URL whether
    // the page rendering them is the landing page or a listing under a
    // prefix.
    const asset = sharedAsset(pathname);
    if (asset) return asset;

    // Ahead of the docs binding, which otherwise answers for everything
    // outside the two prefixes. The desktop reads this instead of telling
    // a third party its IP address; nothing about it is logged or stored.
    if (pathname === '/geo') return geo(request);

    // The game's own endpoints. They live on the ISO site because that is
    // where the download page is, but the page fetching them is a docs
    // asset at /game/, so they are reachable at their own path rather than
    // under /iso/.
    if (pathname.startsWith('/game/')) {
      const route = isoSite.routes?.[pathname.slice(1)];
      if (route) return route(request, env[isoSite.bucket], env, new URL(request.url));
    }

    const site = siteFor(pathname);
    if (site) return handler(site)(request, env, ctx);
    // The static site. Absent under `wrangler dev` without assets and in
    // tests that only bind buckets, and a missing binding should be a 404
    // rather than a thrown exception on every path outside the prefixes.
    if (!env.DOCS) return new Response('not found', { status: 404 });
    return env.DOCS.fetch(request);
  },
};
