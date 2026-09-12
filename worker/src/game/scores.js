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

import { replay, MAX_EVENTS } from './logic.js';

/**
 * The day a seed belongs to, in UTC.
 *
 * UTC rather than the player's zone: a board that rolls over at a
 * different moment per player is not one board, and R1.4 forbids letting
 * the device's timezone reach anything scored.
 */
export function dayOf(now) {
  return new Date(now).toISOString().slice(0, 10);
}

/**
 * The seed for a given day and game.
 *
 * Derived rather than stored: every player gets the same board on the same
 * day without a write, and the verifier can recompute it from the run's
 * own day rather than trusting the submission.
 */
export function seedFor(game, day) {
  let h = 2166136261 >>> 0;
  for (const ch of `${game}:${day}`) {
    h = Math.imul(h ^ ch.charCodeAt(0), 16777619) >>> 0;
  }
  return h >>> 0;
}

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

const NAME = /^[a-z0-9][a-z0-9 _-]{0,23}$/i;

/**
 * The cheap checks, run in the fetch handler before the DO is woken.
 *
 * Shape and bounds only: anything that needs the simulation belongs in the
 * DO. This exists so a garbage submission costs a few microseconds rather
 * than a Durable Object invocation.
 */
export function validateSubmission(body) {
  if (!body || typeof body !== 'object') return 'body must be an object';
  if (typeof body.player !== 'string' || !NAME.test(body.player)) {
    return 'player must be 1-24 characters of letters, digits, space, - or _';
  }
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
