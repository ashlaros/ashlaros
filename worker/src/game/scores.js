/**
 * Seeds, verification and the leaderboard.
 *
 * The shape, and why it is this shape:
 *
 *   POST /game/seed   the server issues a seed and records the claim
 *   POST /game/score  the client submits [action, tick] events
 *                     -> cheap validation here, inside the 10ms budget
 *                     -> replay in a Durable Object, which has 30s
 *                     -> the DO writes the accepted row to D1
 *   GET  /game/board  today's table
 *
 * The free plan gives a fetch handler 10ms of CPU, and re-stepping a
 * multi-minute run at 60Hz does not fit in that. waitUntil does not help -
 * background work draws on the same budget - and a scheduled handler gets
 * the same 10ms. A Durable Object gets 30s per invocation on free, in its
 * own isolate, and a fetch handler waiting on one spends no CPU of its
 * own. So the endpoint does almost nothing and the replay happens where
 * the budget is.
 *
 * R3.2: the replay is the submission. The server recomputes the score and
 * discards whatever number the client reported; the seed comes from the
 * server's own record, never from the request.
 *
 * R3.3: this module and logic.js are server-side. The page ships its own
 * copy of logic.js to play with, but nothing here reaches the client.
 */

// One derivation of the day and the seed, shared with the page: it
// derives both when offline, and a second hand-written copy is exactly
// the drift this design exists to prevent.
export { dayOf, seedFor } from './logic.js';
import { dayOf, replay, seedFor, MAX_EVENTS } from './logic.js';

/**
 * The day a seed belongs to, in UTC.
 *
 * UTC rather than the player's zone: a board that rolls over at a
 * different moment per player is not one board, and R1.4 forbids letting
 * the device's timezone reach anything scored.
 */

/**
 * The seed for a given day and game.
 *
 * Derived rather than stored: every player gets the same board on the same
 * day without a write, and the verifier can recompute it from the run's
 * own day rather than trusting the submission.
 */

export const SCHEMA = `
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  game TEXT NOT NULL,
  day TEXT NOT NULL,
  player TEXT NOT NULL,
  score INTEGER NOT NULL,
  lines INTEGER NOT NULL,
  created_at INTEGER NOT NULL
);
-- the daily board is the hot query, and a table scan is what turns a
-- leaderboard into a slow one as the table grows
CREATE INDEX IF NOT EXISTS runs_board ON runs (game, day, score DESC);
-- one accepted run per player per seed: the board is a pure function of
-- the seed, so a player who restarts gets the same board now known. Best
-- of five measured +34.7% on trinity-slop, beating the honest run in 35 of
-- 40 seeds - a seeded board where retries are free ranks whoever retried.
CREATE UNIQUE INDEX IF NOT EXISTS runs_once ON runs (game, day, player);
`;

/**
 * Arcade initials, three characters.
 *
 * Free text needs moderating forever; [A-Z0-9]x3 is 46,656 possibilities -
 * enough to feel personal, far too short to be a moderation queue, and the
 * offensive combinations are a finite list rather than an ongoing job. It
 * stores nothing about the person either: three characters they chose, a
 * score, a seed.
 *
 * Collisions are a feature. Two players as AAA is fine; the arcade never
 * cared either.
 */
const INITIALS = /^[A-Z0-9]{3}$/;

const DENIED = new Set([
  'ASS', 'FUK', 'FUC', 'CUM', 'TIT', 'FAG', 'JEW', 'NIG', 'NGR', 'KKK',
  'SEX', 'CUN', 'DIK', 'PIS', 'SHT', 'WOP', 'GOK', 'JAP', 'PAK', 'FCK',
]);

/**
 * The initials as stored, or null.
 *
 * Case folding happens here and only here: stored as typed, `abc` and
 * `ABC` would be two rows and the unique index enforcing one attempt per
 * seed would be bypassed by holding shift.
 */
export function initialsOf(body) {
  const player = typeof body?.player === 'string' ? body.player.toUpperCase() : '';
  return INITIALS.test(player) && !DENIED.has(player) ? player : null;
}

/**
 * How long after a day ends its seed still accepts runs.
 *
 * The board a run belongs to is the day its seed was issued, never the
 * moment it was submitted: a run started at 23:59 and submitted at 00:01
 * was played against yesterday's pieces, and scoring it against today's
 * seed rejects an honest player for starting late. That is slopduel's
 * phone-call bug wearing a different hat, and the fix is the same one -
 * stop letting a wall clock decide anything.
 *
 * A run is bounded by MAX_PIECES, so this only has to cover one full run
 * plus the time to type three initials.
 */
export const DAY_GRACE_MS = 60 * 60 * 1000;

/**
 * The day a submission may claim, or null.
 *
 * The client says which seed it played; the server decides whether that
 * seed is still open. Only today and, briefly, yesterday are - so a
 * claimed day is never a way to reach back for a kinder seed.
 */
export function claimedDay(body, now) {
  const day = typeof body?.day === 'string' ? body.day : null;
  if (day === dayOf(now)) return day;
  const at = new Date(now);
  const midnight = Date.UTC(at.getUTCFullYear(), at.getUTCMonth(), at.getUTCDate());
  if (day === dayOf(midnight - 1) && now - midnight < DAY_GRACE_MS) return day;
  return null;
}

/**
 * The cheap checks, run in the fetch handler before the DO is woken.
 *
 * Shape and bounds only: anything that needs the simulation belongs in the
 * DO. This exists so a garbage submission costs a few microseconds rather
 * than a Durable Object invocation.
 */
export function validateSubmission(body) {
  if (!body || typeof body !== 'object') return 'body must be an object';
  if (!initialsOf(body)) return 'initials must be three of A-Z or 0-9';
  if (!Array.isArray(body.events)) return 'events must be an array';
  if (body.events.length > MAX_EVENTS) return 'too many events';
  return null;
}

/**
 * Replay and score. Called inside the Durable Object.
 *
 * The reported score is not an input. It is not even read.
 */
export function verify(seed, events) {
  const state = replay(seed, events);
  return { score: state.score, lines: state.lines };
}

export async function board(db, game, day, limit = 20) {
  const { results } = await db
    .prepare(
      'SELECT player, score, lines FROM runs WHERE game = ? AND day = ?' +
        ' ORDER BY score DESC LIMIT ?',
    )
    .bind(game, day, limit)
    .all();
  return results ?? [];
}

/**
 * All-time, one row per player.
 *
 * Not "the best daily scores": scores from different seeds are not
 * comparable, so a table of best runs ranks the kindest seed rather than
 * the best play. One row each keeps it about people instead, which is
 * still seed-luck-flattered but does not pretend otherwise.
 *
 * A rating would remove seed luck properly - everyone that day faced the
 * same seed - but a rating table with six players is noise. This is the
 * shape to start with; the runs table keeps every run, so a rating can be
 * derived later without a backfill.
 */
export async function allTime(db, game, limit = 20) {
  const { results } = await db
    .prepare(
      'SELECT player, MAX(score) AS score, MAX(lines) AS lines, COUNT(*) AS runs' +
        ' FROM runs WHERE game = ? GROUP BY player ORDER BY score DESC LIMIT ?',
    )
    .bind(game, limit)
    .run();
  return results ?? [];
}

/**
 * The last 30 days, one row per player.
 *
 * Recent form, and the answer to the way an all-time table ossifies: after
 * a year the top ten are fixed and nobody new can enter. A window
 * refreshes itself.
 */
export async function recent(db, game, now, days = 30, limit = 20) {
  const from = dayOf(now - days * 24 * 60 * 60 * 1000);
  const { results } = await db
    .prepare(
      'SELECT player, MAX(score) AS score, MAX(lines) AS lines, COUNT(*) AS runs' +
        ' FROM runs WHERE game = ? AND day >= ? GROUP BY player' +
        ' ORDER BY score DESC LIMIT ?',
    )
    .bind(game, from, limit)
    .run();
  return results ?? [];
}

export async function record(db, { game, day, player, score, lines, now }) {
  try {
    await db
      .prepare(
        'INSERT INTO runs (game, day, player, score, lines, created_at)' +
          ' VALUES (?, ?, ?, ?, ?, ?)',
      )
      .bind(game, day, player, score, lines, now)
      .run();
    return { recorded: true };
  } catch (error) {
    // the unique index is the one-attempt rule, so a second submission is
    // an expected outcome rather than a failure to report as an error
    if (String(error).includes('UNIQUE')) {
      return { recorded: false, reason: 'already submitted a run for this seed' };
    }
    throw error;
  }
}

/**
 * The Durable Object that does the replaying.
 *
 * It exists for its CPU budget, not for its storage: 30s per invocation on
 * the free plan against the fetch handler's 10ms.
 */
export class Verifier {
  constructor(state, env) {
    this.env = env;
  }

  async fetch(request) {
    const { game, day, seed, player, events, now } = await request.json();

    let result;
    try {
      result = verify(seed, events);
    } catch (error) {
      // a malformed log is a rejection, not a server error
      return Response.json({ error: String(error.message ?? error) }, { status: 400 });
    }

    const written = await record(this.env.SCORES, {
      game,
      day,
      player,
      score: result.score,
      lines: result.lines,
      now,
    });

    return Response.json({ ...result, ...written });
  }
}
