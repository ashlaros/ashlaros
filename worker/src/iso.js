/**
 * iso.ashlaros.download - the ISO downloads.
 *
 * The listing is the bucket, not a manifest the publish job has to keep in
 * step: a page rendered from R2 cannot show an image that is not there, or
 * miss one that is.
 */

import { escapeHtml, html, humanSize, json, page } from './serve.js';
import { collect, record } from './stats.js';
import {
  DEFAULT_GAME,
  allTime,
  board,
  gameOf,
  claimedDay,
  dayOf,
  initialsOf,
  recent,
  seedFor,
  validateSubmission,
} from './game/scores.js';

const TITLE = 'AshlarOS';

/**
 * The version prefix a key belongs to.
 *
 * upload_iso.py writes <version>/<name>.iso and latest/ashlaros.iso, so the
 * first segment is the version and `latest` is an alias rather than one.
 */
export function versionOf(key) {
  const cut = key.indexOf('/');
  return cut === -1 ? null : key.slice(0, cut);
}

/**
 * Whether a key is one of the `latest/` pointers upload_iso.py writes.
 *
 * Only the image aliases. `latest/screenshots/` and `latest/video/` live
 * under the same prefix and are real files the page renders, so matching
 * the whole prefix would turn every screenshot into a broken redirect.
 */
export function isAlias(key) {
  return key === 'latest/ashlaros.iso' || key === 'latest/ashlaros-rpi5.img.xz';
}

/**
 * The versioned filename an alias points at.
 *
 * The alias is named for the product; the real file carries the version in
 * its name - ashlaros.iso is ashlaros-2026.09.15-x86_64.iso under that
 * version's prefix. So the redirect has to build the name rather than
 * reuse the alias's, or it points at a key that does not exist.
 */
export function aliasTarget(version, aliasName) {
  if (aliasName === 'ashlaros.iso') return `ashlaros-${version}-x86_64.iso`;
  return `ashlaros-${version}-aarch64-rpi5.img.xz`;
}

/**
 * The strip of desktop shots above the downloads.
 *
 * A picture of what you are about to download belongs on the page offering
 * it. They are never listed as rows: the listing skips `latest/` entirely,
 * which is where the screenshot job publishes.
 */
/**
 * The desktop tour, above the stills.
 *
 * preload="metadata" rather than auto: the file is a few hundred KB and
 * every visitor to the download page would otherwise pay for it unasked.
 * muted and playsinline so it can autoplay at all, loop because it is a
 * few seconds long, and width/height set for the same no-reflow reason the
 * stills carry them.
 */
function renderTour(key) {
  if (!key) return '';
  return (
    `<video class="tour" src="/${escapeHtml(key)}" width="960" height="540"` +
    ' autoplay muted loop playsinline preload="metadata"></video>'
  );
}

function renderShots(shots) {
  if (!shots.length) return '';
  const images = shots
    .map(
      (key) =>
        `<a href="/${escapeHtml(key)}"><img class="shot" src="/${escapeHtml(key)}"` +
        ` alt="${escapeHtml(key.split('/').pop().replace(/\.png$/, ''))}"` +
        ' width="480" height="270" loading="lazy" /></a>',
    )
    .join('\n');
  return `<div class="shots">\n${images}\n</div>`;
}

/**
 * Which machine an object is for.
 *
 * The ISO and the Pi image are different hardware, not two files in one
 * list: an x86_64 ISO on a Pi is not a slower download, it is the wrong
 * thing entirely (#29). A checksum belongs with whatever it checksums,
 * and upload_iso.py names the image's one SHA256SUMS.<image> because a
 * bare name would collide with the ISO's.
 */
export function targetOf(name) {
  if (/rpi5|aarch64/.test(name)) return 'Raspberry Pi 5';
  if (/x86_64/.test(name)) return 'PC (x86_64)';
  // a bare SHA256SUMS is the ISO's, since the image's carries its name
  return 'PC (x86_64)';
}

export function renderIndex(byVersion, shots = [], tour = null) {
  // version prefixes sort chronologically, so the newest is last
  const versions = [...byVersion.keys()].sort().reverse();
  const sections = versions
    .map((version) => {
      const groups = new Map();
      for (const object of byVersion.get(version)) {
        const name = object.key.slice(version.length + 1);
        const target = targetOf(name);
        if (!groups.has(target)) groups.set(target, []);
        groups.get(target).push({ name, key: object.key, size: object.size });
      }

      // the PC image first, because it is what most visitors came for,
      // and stable regardless of which files a version happens to carry
      const order = ['PC (x86_64)', 'Raspberry Pi 5'];
      const blocks = [...groups.keys()]
        .sort((a, b) => order.indexOf(a) - order.indexOf(b))
        .map((target) => {
          const rows = groups
            .get(target)
            .map(
              (o) =>
                `<a class="row" href="/${escapeHtml(o.key)}"><span>${escapeHtml(
                  o.name,
                )}</span><span>${humanSize(o.size)}</span></a>`,
            )
            .join('\n');
          return `<h3>${escapeHtml(target)}</h3>\n${rows}`;
        })
        .join('\n');
      return `<h2>${escapeHtml(version)}</h2>\n${blocks}`;
    })
    .join('\n');

  return page(
    TITLE,
    `      <p>The newest x86_64 ISO is always at
        <a href="/latest/ashlaros.iso"><code>/latest/ashlaros.iso</code></a>,
        and the newest Raspberry Pi 5 image at
        <a href="/latest/ashlaros-rpi5.img.xz"
          ><code>/latest/ashlaros-rpi5.img.xz</code></a
        >. Verify a download against the <code>SHA256SUMS</code> beside it.
        <a class="link" href="/stats">Download stats</a>.</p>
      <!-- beside the download rather than in a footnote (#29): the ISO
           encrypts by default and someone who knows that will reasonably
           assume the Pi image does too -->
      <p>The ISO installs an encrypted disk by default. The Pi image is
        written to a card and is <strong>not encrypted</strong> — the
        installer that sets up LUKS runs on x86_64 only, and the Pi's
        firmware boots directly from a FAT partition.</p>
${renderTour(tour)}
${renderShots(shots)}
${sections || '<p>No images published yet.</p>'}`,
  );
}

const countRow = (label, href, downloads) =>
  `<tr><td>${href ? `<a href="${href}">${escapeHtml(label)}</a>` : escapeHtml(label)}` +
  `</td><td>${downloads.toLocaleString('en-US')}</td></tr>`;

export function renderStats({ configured, archive, versions, files, version }) {
  const parts = [];

  if (!configured) {
    // public page: say what is true rather than answer 500, which reads as
    // "the numbers are broken" when it means "no read token yet"
    parts.push(
      '<p>Live stats are not configured yet. Downloads are still being counted,' +
        ' and any archived months appear below.</p>',
    );
  } else {
    parts.push('<h2>Last three months</h2>');
    parts.push(
      versions.length
        ? `<table>${versions
            .map((row) =>
              countRow(
                row.version,
                `/stats?version=${encodeURIComponent(row.version)}`,
                row.downloads,
              ),
            )
            .join('')}</table>`
        : '<p>No downloads recorded yet.</p>',
    );
  }

  if (files) {
    parts.push(`<h2>${escapeHtml(version)}</h2>`);
    parts.push(
      files.length
        ? `<table>${files.map((row) => countRow(row.name, null, row.downloads)).join('')}</table>`
        : '<p>No downloads recorded for this version.</p>',
    );
  }

  for (const { month, totals } of archive) {
    const rows = Object.entries(totals).sort((a, b) => b[1] - a[1]);
    parts.push(`<h2>${escapeHtml(month)}</h2>`);
    parts.push(
      rows.length
        ? `<table>${rows.map(([name, n]) => countRow(name, null, n)).join('')}</table>`
        : '<p>No downloads that month.</p>',
    );
  }

  parts.push(
      'A download is one whole-image GET that transferred.' +
      ' Resumed downloads and revalidations are not counted, and neither is' +
      ' <code>SHA256SUMS</code>.' +
      ' <a class="link" href="/stats.json">stats.json</a></p>',
  );

  return page(TITLE, parts.join('\n'));
}

export const site = {
  bucket: 'ISO',
  isListing: (key) => key === '',

  // no arch trees here: every key is <version>/<file>, and an unknown one
  // simply misses in the bucket
  resolveKey: (path) => path,

  // latest/ holds a version string, not an image; the handler redirects
  isAlias,
  aliasTarget,

  // only this site counts: every `pacman -Sy` is a database fetch, and
  // that event volume would dwarf the signal on the packages side
  record,

  routes: {
    // The game endpoints. On the ISO site because that is where the
    // download page lives and the game is a thing to do while an image
    // downloads - and because both already share this worker.
    'game/seed': async (request, bucket, env, url) => {
      // Checked against the registry, not taken as given: an unknown name
      // would otherwise be handed a seed and a board of its own, which
      // reads as a working game and is a typo.
      const game = gameOf(url.searchParams.get('game') ?? DEFAULT_GAME);
      if (!game) return json({ error: 'unknown game' }, 404);
      // the day is part of the answer: the client sends it back with the
      // run so the score lands on the board it was played for
      const day = dayOf(Date.now());
      return json({ game, day, seed: seedFor(game, day) });
    },

    'game/board': async (request, bucket, env, url) => {
      const game = gameOf(url.searchParams.get('game') ?? DEFAULT_GAME);
      if (!game) return json({ error: 'unknown game' }, 404);
      const day = url.searchParams.get('day') ?? dayOf(Date.now());
      if (!env.SCORES) return json({ game, day, scores: [], configured: false });
      return json({ game, day, scores: await board(env.SCORES, game, day) });
    },

    // Two boards, because they answer different questions: the daily one
    // is the competition and resets, so a newcomer is never looking at a
    // wall of scores set months ago; these are the hall of fame.
    'game/all-time': async (request, bucket, env, url) => {
      const game = gameOf(url.searchParams.get('game') ?? DEFAULT_GAME);
      if (!game) return json({ error: 'unknown game' }, 404);
      if (!env.SCORES) return json({ game, scores: [], configured: false });
      const window = url.searchParams.get('window');
      const scores =
        window === 'all'
          ? await allTime(env.SCORES, game)
          : await recent(env.SCORES, game, Date.now());
      return json({ game, window: window === 'all' ? 'all' : '30d', scores });
    },

    'game/score': async (request, bucket, env) => {
      if (request.method !== 'POST') {
        return json({ error: 'post the run' }, 405);
      }
      if (!env.SCORES || !env.VERIFIER) {
        return json({ error: 'scores are not configured' }, 503);
      }

      let body;
      try {
        body = await request.json();
      } catch {
        return json({ error: 'body must be json' }, 400);
      }

      // cheap checks here, inside the 10ms the fetch handler gets; the
      // replay happens in the Durable Object, which gets 30s
      const problem = validateSubmission(body);
      if (problem) return json({ error: problem }, 400);

      const game = gameOf(typeof body.game === 'string' ? body.game : DEFAULT_GAME);
      if (!game) return json({ error: 'unknown game' }, 400);
      // the board is the day the seed was issued, not the moment this
      // arrived - a run started before midnight was played on yesterday's
      // pieces and must be scored against them
      const now = Date.now();
      const day = claimedDay(body, now);
      if (!day) return json({ error: 'that seed is no longer open' }, 400);
      // R3.2: the seed is still the server's, derived from the day rather
      // than taken from the submission
      const seed = seedFor(game, day);

      const id = env.VERIFIER.idFromName(`${game}:${day}`);
      const response = await env.VERIFIER.get(id).fetch(
        new Request('https://verifier/', {
          method: 'POST',
          body: JSON.stringify({
            game,
            day,
            seed,
            player: initialsOf(body),
            events: body.events,
            now,
          }),
        }),
      );
      return new Response(response.body, {
        status: response.status,
        headers: { 'content-type': 'application/json' },
      });
    },

    stats: async (request, bucket, env, url) =>
      html(renderStats(await collect(env, url.searchParams.get('version')))),
    'stats.json': async (request, bucket, env, url) =>
      json(await collect(env, url.searchParams.get('version'))),
  },

  listing: async (bucket) => {
    // Paginated, because a single list() caps at 1000 keys and answers
    // truncated without saying so. Every release adds an image, a
    // checksum and a signature, so the cap is reached by accumulation
    // rather than by anything going wrong - and R2 lists lexically, so
    // `latest/` sorts last and would be the first thing to vanish from
    // the page, taking the screenshots and the tour with it.
    const objects = [];
    let cursor;
    do {
      const page = await bucket.list({ limit: 1000, cursor });
      objects.push(...page.objects);
      cursor = page.truncated ? page.cursor : undefined;
    } while (cursor);

    const byVersion = new Map();
    const shots = [];
    let tour = null;
    for (const object of objects) {
      const version = versionOf(object.key);
      if (!version) continue;
      // latest/ holds a pointer to a version already listed below, not an
      // image, so nothing under it becomes a download row - the
      // screenshots there are shown as pictures instead
      if (version === 'latest') {
        if (object.key.startsWith('latest/screenshots/')) shots.push(object.key);
        if (object.key.endsWith('.webm')) tour = object.key;
        continue;
      }
      if (!byVersion.has(version)) byVersion.set(version, []);
      byVersion.get(version).push(object);
    }
    return html(renderIndex(byVersion, shots.sort(), tour));
  },

  headers: (key) => {
    const headers = {
      // A versioned image never changes. Under latest/ this now only
      // reaches the screenshots and the tour - the image aliases are
      // pointers the handler redirects before it gets here - and those are
      // republished in place, so no-cache is still right for them.
      'cache-control':
        versionOf(key) === 'latest'
          ? 'no-cache'
          : 'public, max-age=31536000, immutable',
    };
    if (key.endsWith('.iso')) {
      // browsers otherwise try to render several gigabytes of ISO
      headers['content-disposition'] = `attachment; filename="${key.split('/').pop()}"`;
    }
    return headers;
  },
};
