/**
 * What serving a bucket over HTTP has in common, whichever bucket it is.
 *
 * R2 has no directories: a listing is a delimited list() over the key
 * prefix. Object reads stream straight through, so a client gets plain
 * bytes with working range requests.
 */

import { FAVICON } from './favicon.js';
import { BACKGROUND } from './background.js';
import { STYLESHEET } from './style.js';

export const escapeHtml = (s) => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

export function humanSize(bytes) {
  const units = ['B', 'KiB', 'MiB', 'GiB'];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${unit === 0 ? value : value.toFixed(1)} ${units[unit]}`;
}

/**
 * The design language from sway-repo/_layouts/default.html, with the
 * Manjaro green replaced by our stone accent. Both sites render with it,
 * which is the point of having one worker.
 */


/**
 * The topbar title, with the project name linking home.
 *
 * Absolute, to the apex: on packages. and iso. a bare "/" is that site's
 * own index, so a relative link would send three hosts to three different
 * pages when the point is one way back to the project.
 *
 * Only the name links. A packages listing is titled
 * "AshlarOS — Packages / x86_64/", and everything after the name is where
 * you already are - linking it home would be a lie about where it goes.
 */
const HOME = 'https://ashlaros.download/';

const NAME = 'AshlarOS';

function titleLink(title) {
  const safe = escapeHtml(title);
  // a title that does not start with the project name is not one of ours
  // to link; render it as text rather than guessing where it should go
  if (!safe.startsWith(NAME)) return safe;
  return `<a href="${HOME}">${NAME}</a>${safe.slice(NAME.length)}`;
}

export function page(title, body) {
  return `<!DOCTYPE html>
<html lang="en">
  <head>
    <title>${escapeHtml(title)}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <link rel="icon" href="/favicon.svg" type="image/svg+xml" />
    <link rel="stylesheet" href="/site.css" />
  </head>
  <body>
    <h1>${titleLink(title)}</h1>
    <main>
${body}
    </main>
  </body>
</html>
`;
}

export const html = (body) =>
  new Response(body, { headers: { 'content-type': 'text/html; charset=utf-8' } });

export const json = (body, status = 200) =>
  new Response(`${JSON.stringify(body)}\n`, {
    status,
    headers: { 'content-type': 'application/json' },
  });

export const notFound = () => new Response('not found', { status: 404 });

/**
 * Stream one object, with the caching and headers the site asks for.
 *
 * Range and conditional requests are handed to R2 rather than reimplemented:
 * a resumed 1.7 GB ISO download depends on both.
 */
export async function serveObject(request, bucket, key, extraHeaders = {}) {
  // If-Range decides whether a resumed download may continue, and R2 does
  // not apply it: a stale validator still came back 206. That is the
  // dangerous answer for `latest/`, which is a real object repointed at
  // every release - a client resuming across one would splice bytes from
  // two different ISOs into a file that fails its checksum and looks like
  // a corrupt download rather than a moved target.
  //
  // So it is evaluated here: a validator that no longer matches drops the
  // range and serves the whole current object, which is what RFC 9110
  // asks for and what makes the client start over instead of stitching.
  const ifRange = request.headers.get('if-range');
  let wanted = request.headers;
  if (ifRange && request.headers.get('range')) {
    const current = await bucket.head(key);
    if (!current) return notFound();
    // an entity-tag comparison; a weak tag never matches for a range
    if (ifRange.trim() !== current.httpEtag) {
      wanted = new Headers(request.headers);
      wanted.delete('range');
    }
  }

  const object = await bucket.get(key, {
    range: wanted,
    onlyIf: request.headers,
  });
  if (!object) return notFound();

  const headers = new Headers();
  object.writeHttpMetadata(headers);
  headers.set('etag', object.httpEtag);
  // writeHttpMetadata carries the stored content type and nothing about
  // size or ranges. curl and a browser downloading an ISO do not care; a
  // <video> element does - it probes with HEAD, finds no length and no
  // advertised range support, concludes it cannot seek, and fails the
  // load with a format error even though the bytes are perfect and a
  // range request would have been answered.
  headers.set('accept-ranges', 'bytes');
  // What the client asked for, not what R2 reports. R2 fills in `range`
  // for a full read too - offset 0, the whole length - so testing the
  // object alone answered 206 to every plain GET. That is wrong twice
  // over: 206 without a request range violates RFC 9110, and stats.js
  // excludes 206 so it does not count a resume as many downloads, which
  // meant no download was counted at all.
  const asked = wanted.get('range');
  const ranged = Boolean(asked) && object.range && 'offset' in object.range;
  if (ranged) {
    const { offset, length } = object.range;
    headers.set('content-range', `bytes ${offset}-${offset + length - 1}/${object.size}`);
    headers.set('content-length', String(length));
  } else {
    headers.set('content-length', String(object.size));
  }
  for (const [name, value] of Object.entries(extraHeaders)) headers.set(name, value);

  // `wanted`, not the original request: a range dropped by the If-Range
  // check above must be answered 200 with the whole object, and saying
  // 206 there would tell the client its stale offsets were honoured.
  const status = object.body ? (ranged ? 206 : 200) : 304;
  return new Response(request.method === 'HEAD' ? null : object.body, { status, headers });
}

/**
 * Turn a site definition into a fetch handler.
 *
 * A site supplies: `bucket` (the binding name), `title`, `resolveKey`,
 * `listing`, `headers`, and optionally `routes` for anything it serves
 * that is not a bucket object. A route is called with
 * (request, bucket, env, url).
 */
/**
 * Everything is served from one hostname now, so a site owns a path prefix
 * rather than a subdomain: /packages/ and /iso/. The prefix is stripped
 * here and put back by site.href, so the bucket keys and every resolveKey
 * stay exactly what they were - the move is in the URL, not in R2.
 */
/**
 * The files every page links: the stylesheet, its background and the
 * favicon.
 *
 * At the entrypoint rather than inside a site handler, because the pages
 * link them absolutely from the apex - /site.css, not /packages/site.css -
 * and a listing under a prefix has to resolve the same URL the landing
 * page does. They used to sit in the handler, which was right when each
 * site owned a hostname and wrong the moment they owned a path.
 */
export function sharedAsset(pathname) {
  const assets = {
    '/site.css': ['text/css; charset=utf-8', STYLESHEET],
    '/background.svg': ['image/svg+xml', BACKGROUND],
    // .ico callers accept an svg body, so one file serves both
    '/favicon.svg': ['image/svg+xml', FAVICON],
    '/favicon.ico': ['image/svg+xml', FAVICON],
  };
  const asset = assets[pathname];
  if (!asset) return null;
  const [type, body] = asset;
  return new Response(body, {
    headers: { 'content-type': type, 'cache-control': 'public, max-age=86400' },
  });
}

export function handler(site) {
  return async (request, env) => {
    const url = new URL(request.url);
    // A lone `%` is not a decodable escape and decodeURIComponent throws
    // on one, which on Workers is a 1101 rather than a status - served to
    // pacman, which expects an HTTP answer. A path that does not decode
    // names no key, so it is a miss like any other.
    let path;
    try {
      path = decodeURIComponent(url.pathname);
    } catch {
      return notFound();
    }
    const base = `/${site.prefix}`;
    if (path !== base && !path.startsWith(`${base}/`)) return notFound();
    const requested = path.slice(base.length).replace(/^\//, '');
    const bucket = env[site.bucket];

    // Routes are checked before the method gate: a bucket only ever
    // answers GET and HEAD, but a route may be a POST endpoint, and
    // rejecting it here would make the route unreachable rather than
    // wrong - which is how the score endpoint first answered 405.
    //
    // (request, bucket, env, url) rather than just the bucket: /geo needs
    // request.cf, and the game routes need env and the query. One
    // signature covering all of them beats each adding its own parameter.
    const route = site.routes?.[requested];
    if (route) return route(request, bucket, env, url);

    if (request.method !== 'GET' && request.method !== 'HEAD') {
      return new Response('method not allowed', { status: 405 });
    }

    const key = site.resolveKey(requested);
    if (key === null) return notFound();

    // An alias is a pointer holding a version string, not the image. It
    // is read and redirected rather than served, so a download targets an
    // immutable versioned URL: `latest/` is repointed every release, and a
    // resume across one used to ask for a byte range of an object that had
    // been replaced underneath it.
    if (site.isAlias?.(key)) {
      const pointer = await bucket.get(key);
      if (!pointer) return notFound();
      // A pointer is a version string - twelve bytes or so. Reading the
      // body without checking its size killed the isolate when the key
      // still held the 1.98 GB image it used to be a copy of: text() on
      // two gigabytes is Cloudflare's error 1101, and both aliases
      // answered 500 until the objects were replaced. Anything larger
      // than a version cannot be one, so it is not read at all.
      if (pointer.size > 64) return notFound();
      const version = (await pointer.text()).trim();
      // a pointer that is not a version is a broken publish; 404 beats
      // redirecting somewhere arbitrary
      if (!/^\d{4}\.\d{2}\.\d{2}$/.test(version)) return notFound();
      const name = key.slice(key.indexOf('/') + 1);
      return new Response(null, {
        status: 302,
        headers: {
          location: `/${site.prefix}/${version}/${site.aliasTarget(version, name)}`,
          // the pointer moves every release, so nothing may cache the hop
          'cache-control': 'no-cache',
        },
      });
    }

    if (site.isListing(key)) return site.listing(bucket, key);

    // An object the site marks fetchable direct from its bucket is
    // redirected there instead of streamed through here. run_worker_first
    // means this worker is invoked for every request on every route, so
    // serving the bytes spends an invocation per request on an object that
    // cannot change; the bucket hostname has no worker in front of it, so
    // the hop costs one invocation and the transfer and every repeat fetch
    // cost none.
    //
    // Ranges are redirected too. The bucket hostnames answer them natively
    // - 206 with content-range and an etag - and a resume is the case that
    // matters most, since excluding it would send a partial multi-gigabyte
    // transfer back through the worker. The etag differs across the hop
    // (a multipart upload's is a digest of digests), so a client resuming
    // with a stale If-Range is served the whole object and starts over,
    // which is what RFC 9110 asks for - and these objects are immutable,
    // so it restarts on the same bytes.
    const direct = site.direct?.(key);
    if (direct && request.method === 'GET') {
      // head first: without it an absent object answers 302 to a URL that
      // is also absent, so a typo or a pruned version becomes a redirect
      // into a 404 on another host rather than an honest 404 here. One
      // metadata read, against a transfer this hands off entirely.
      if (!(await bucket.head(key))) return notFound();
      const hop = new Response(null, {
        status: 302,
        headers: {
          location: direct,
          // the object is immutable, so the hop to it is too - but keep it
          // short enough that moving the bucket is not a year-long wait
          'cache-control': 'public, max-age=3600',
        },
      });
      // The last point at which this download is visible to us: the bytes
      // move on a host that reports nothing back. Not a ranged hop: a
      // resume issues one per chunk, and counting each would report one
      // download as dozens - which is why 206 was never counted when the
      // range was answered here.
      if (!request.headers.get('range')) site.record?.(env, key, hop.status, request.method);
      return hop;
    }

    const response = await serveObject(request, bucket, key, site.headers(key));
    // after the response, because only its status says whether anything was
    // transferred. Optional and site-specific: the packages site defines no
    // record, so pacman traffic is never counted.
    site.record?.(env, key, response.status, request.method);
    return response;
  };
}
