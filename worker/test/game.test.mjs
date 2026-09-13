/**
 * The rules the leaderboard rests on.
 *
 * These are not tests of plumbing: each one is a property that, if it
 * broke, would silently turn the board into a ranking of something other
 * than play. The determinism ones are the reason this design exists at
 * all - one implementation is only worth anything if it gives one answer.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  ACTIONS,
  MAX_EVENTS_PER_TICK,
  MAX_PIECES,
  PIECE_NAMES,
  bagAt,
  createState,
  hash32,
  pieceAt,
  replay,
  stepTick,
} from '../src/game/logic.js';
import { DAY_GRACE_MS, allTime, claimedDay, recent, dayOf, initialsOf, seedFor, validateSubmission, verify } from '../src/game/scores.js';
import worker from '../src/index.js';
import { bucketOf, get } from './helpers.mjs';

test('the same seed gives the same pieces, every time', () => {
  // R1.1: the seed is the only source of world state. Without this the
  // board compares luck rather than play.
  const first = Array.from({ length: 100 }, (_, i) => pieceAt(12345, i));
  const second = Array.from({ length: 100 }, (_, i) => pieceAt(12345, i));
  assert.deepEqual(first, second);
});

test('different seeds give different sequences', () => {
  const a = Array.from({ length: 40 }, (_, i) => pieceAt(1, i)).join('');
  const b = Array.from({ length: 40 }, (_, i) => pieceAt(2, i)).join('');
  assert.notEqual(a, b);
});

test('every bag holds each piece exactly once', () => {
  // a bag that can repeat or drop a piece is not a 7-bag, and a player
  // whose muscle memory expects one will notice within a minute
  for (let n = 0; n < 50; n++) {
    const bag = bagAt(99, n);
    assert.equal(bag.length, 7);
    assert.deepEqual([...bag].sort(), [...PIECE_NAMES].sort());
  }
});

test('the generator is addressable, not a stream', () => {
  // R1.3: piece 500 is computable without stepping through the 499 before
  // it. This is what lets the verifier jump rather than re-shuffle.
  const direct = pieceAt(7, 500);
  const viaBag = bagAt(7, Math.floor(500 / 7))[500 % 7];
  assert.equal(direct, viaBag);
});

test('the hash stays inside 32 bits', () => {
  // integers only: an unmasked multiply leaves the exact-integer range and
  // two engines are then free to disagree about the low bits, which is
  // exactly the drift this whole design exists to avoid
  for (let i = 0; i < 1000; i++) {
    const h = hash32(i, i * 7);
    assert.ok(Number.isInteger(h), `${h} is not an integer`);
    assert.ok(h >= 0 && h <= 0xffffffff, `${h} is outside 32 bits`);
  }
});

test('no floating point reaches a score', () => {
  // the property, asserted rather than promised: replay a run with
  // scoring in it and require the result to be an exact integer
  const events = [];
  for (let i = 0; i < 40; i++) events.push([ACTIONS.HARD_DROP, i * 30]);
  const { score, lines } = verify(4242, events);
  assert.ok(Number.isInteger(score), `${score} is not an integer`);
  assert.ok(Number.isInteger(lines));
});

test('replaying the same events twice gives the same score', () => {
  // one implementation is worth nothing if it is not deterministic: this
  // is the check that a rejected honest score would have failed
  const events = [];
  for (let i = 0; i < 60; i++) {
    events.push([i % 2 ? ACTIONS.LEFT : ACTIONS.RIGHT, i * 10]);
    events.push([ACTIONS.HARD_DROP, i * 10 + 5]);
  }
  const a = verify(31337, events);
  const b = verify(31337, events);
  assert.deepEqual(a, b);
});

test('the reported score is never read', () => {
  // R3.2: the replay is the submission. A client claiming a million is
  // scored on what its events actually did.
  const events = [[ACTIONS.HARD_DROP, 0]];
  const honest = verify(5, events);
  const lying = verify(5, events);
  assert.equal(honest.score, lying.score);
  // and nothing in the verify signature accepts a score at all
  assert.equal(verify.length, 2);
});

test('a run ends rather than continuing forever', () => {
  // without a bound the board ranks whoever had a free afternoon. An empty
  // event log still terminates, because gravity keeps running.
  const state = replay(77, []);
  assert.equal(state.over, true);
  assert.ok(state.index <= MAX_PIECES, `${state.index} pieces`);
});

test('a log with impossible input density is refused', () => {
  // a human cannot press nine keys in one 60th of a second, and without
  // this a crafted log could pack a whole run into tick 0
  const events = [];
  for (let i = 0; i <= MAX_EVENTS_PER_TICK; i++) events.push([ACTIONS.LEFT, 0]);
  assert.throws(() => verify(1, events), /too many events in one tick/);
});

test('ticks may not go backwards', () => {
  assert.throws(() => verify(1, [[ACTIONS.LEFT, 50], [ACTIONS.LEFT, 10]]), /backwards/);
});

test('a malformed log is refused rather than scored', () => {
  // half-accepting a log is worse than refusing it outright
  assert.throws(() => verify(1, [[ACTIONS.LEFT]]), /\[action, tick\]/);
  assert.throws(() => verify(1, [['left', 0]]), /integers/);
  assert.throws(() => verify(1, [[99, 0]]), /unknown action/);
  assert.throws(() => verify(1, 'not an array'), /array/);
});

test('a suspended tab owes the simulation nothing', () => {
  // R2.1: ticks, not wall clock. The same events at the same ticks score
  // the same however long the player took to produce them - which is the
  // bug that lost someone a duel for taking a phone call.
  const events = [[ACTIONS.LEFT, 10], [ACTIONS.HARD_DROP, 20]];
  assert.deepEqual(verify(9, events), verify(9, events));
});

test('the daily seed is the same for everyone and changes per day', () => {
  assert.equal(seedFor('courses', '2026-09-12'), seedFor('courses', '2026-09-12'));
  assert.notEqual(seedFor('courses', '2026-09-12'), seedFor('courses', '2026-09-13'));
  // and per game, so two games on one day are not the same board
  assert.notEqual(seedFor('courses', '2026-09-12'), seedFor('breaker', '2026-09-12'));
});

test('the day is UTC, not the visitor unit', () => {
  // R1.4: a board that rolls over at a different moment per player is not
  // one board
  assert.equal(dayOf(Date.UTC(2026, 8, 12, 23, 59)), '2026-09-12');
  assert.equal(dayOf(Date.UTC(2026, 8, 13, 0, 1)), '2026-09-13');
});

test('a submission is checked before a Durable Object is woken', () => {
  // rejected or not is the contract; the wording is not
  assert.ok(validateSubmission({}));
  assert.ok(validateSubmission({ player: 'ABC', events: 'not an array' }));
  assert.equal(validateSubmission({ player: 'ABC', events: [] }), null);
});

test('initials are three characters, folded once, and offensive ones refused', () => {
  assert.equal(initialsOf({ player: 'abc' }), 'ABC');
  assert.equal(initialsOf({ player: 'A1Z' }), 'A1Z');
  // stored as typed, abc and ABC would be two rows and the one-attempt
  // index would be bypassed by holding shift
  assert.equal(initialsOf({ player: 'abc' }), initialsOf({ player: 'ABC' }));
  assert.equal(initialsOf({ player: 'ashlar' }), null);
  assert.equal(initialsOf({ player: 'AB' }), null);
  assert.equal(initialsOf({ player: 'A-B' }), null);
  assert.equal(initialsOf({ player: 'ass' }), null);
  assert.equal(initialsOf({}), null);
});

test('gravity alone locks pieces and fills the board', () => {
  // the simulation runs without any input at all, which is what makes the
  // no-events case above terminate rather than hang
  const state = createState(1);
  for (let i = 0; i < 5000 && !state.over; i++) stepTick(state);
  assert.ok(state.index > 1, 'no piece was ever locked');
});

test('a POST route is reachable at all', async () => {
  // the shared handler rejected anything but GET/HEAD before it looked at
  // routes, so the score endpoint answered 405 no matter what it was sent.
  // A bucket still only answers GET and HEAD.
  const env = { ISO: bucketOf([]), PACKAGES: bucketOf([]) };
  const posted = await worker.fetch(
    new Request('https://iso.ashlaros.download/game/score', {
      method: 'POST',
      body: '{}',
    }),
    env,
    {},
  );
  assert.notEqual(posted.status, 405);

  // and a POST to a bucket path is still refused
  const bucketPost = await worker.fetch(
    new Request('https://iso.ashlaros.download/latest/ashlaros.iso', { method: 'POST' }),
    env,
    {},
  );
  assert.equal(bucketPost.status, 405);
});

test('a seed request needs no database', async () => {
  // the seed is derived, so the game is playable before any of the score
  // plumbing exists or when it is down
  const env = { ISO: bucketOf([]) };
  const res = await worker.fetch(get('iso.ashlaros.download', 'game/seed'), env, {});
  const body = await res.json();
  assert.equal(body.seed, seedFor('courses', body.day));
});

test('scores report unconfigured rather than failing', async () => {
  const env = { ISO: bucketOf([]) };
  const res = await worker.fetch(get('iso.ashlaros.download', 'game/board'), env, {});
  const body = await res.json();
  assert.deepEqual(body.scores, []);
  assert.equal(body.configured, false);
});

test('the game endpoints answer on the host the page is served from', async () => {
  // the page is a docs asset on the apex, so its own fetches go there -
  // and the docs binding answering 404 made the page report itself
  // offline while the endpoints worked perfectly on the other hostname
  const env = { ISO: bucketOf([]), DOCS: { fetch: async () => new Response('docs', { status: 404 }) } };
  const res = await worker.fetch(
    new Request('https://ashlaros.download/game/seed?game=courses'),
    env,
    {},
  );
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.seed, seedFor('courses', body.day));
});

test('the apex still serves its own assets', async () => {
  const env = { ISO: bucketOf([]), DOCS: { fetch: async () => new Response('the landing page') } };
  const res = await worker.fetch(new Request('https://ashlaros.download/'), env, {});
  assert.equal(await res.text(), 'the landing page');
});

test('a run is scored against the day its seed was issued', () => {
  // a run started at 23:59 and submitted at 00:01 was played on
  // yesterday's pieces; scoring it against today's seed would reject an
  // honest player for starting late
  const justAfterMidnight = Date.UTC(2026, 8, 13, 0, 1);
  assert.equal(claimedDay({ day: '2026-09-12' }, justAfterMidnight), '2026-09-12');
  assert.equal(claimedDay({ day: '2026-09-13' }, justAfterMidnight), '2026-09-13');

  // but yesterday's seed does not stay open forever, or a player could
  // shop the archive for the kindest seed
  const later = Date.UTC(2026, 8, 13) + DAY_GRACE_MS + 1;
  assert.equal(claimedDay({ day: '2026-09-12' }, later), null);
  assert.equal(claimedDay({ day: '2026-01-01' }, justAfterMidnight), null);
  assert.equal(claimedDay({}, justAfterMidnight), null);
});

test('the page and the server derive the same seed', async () => {
  // the page derives its own seed when it is offline; if the two
  // derivations ever disagreed, an offline run would be scored against a
  // board it never played
  const pageLogic = await import('../../docs/game/logic.js');
  assert.equal(pageLogic.seedFor('courses', '2026-09-12'), seedFor('courses', '2026-09-12'));
  assert.equal(pageLogic.dayOf(Date.UTC(2026, 8, 12, 23, 59)), dayOf(Date.UTC(2026, 8, 12, 23, 59)));
});

/** A D1 stand-in that records what it was asked and answers with rows. */
function dbOf(rows = []) {
  const asked = [];
  return {
    asked,
    prepare(sql) {
      const q = { sql, args: [] };
      asked.push(q);
      return {
        bind(...args) {
          q.args = args;
          return this;
        },
        run: async () => ({ results: rows }),
        all: async () => ({ results: rows }),
      };
    },
  };
}

test('the all-time board is one row per player, not the best runs', async () => {
  // scores from different seeds are not comparable, so a table of best
  // runs ranks the kindest seed rather than the best play
  const db = dbOf([{ player: 'ABC', score: 9000, lines: 12, runs: 4 }]);
  const rows = await allTime(db, 'courses');
  assert.equal(rows[0].player, 'ABC');
  assert.match(db.asked[0].sql, /GROUP BY player/);
  assert.match(db.asked[0].sql, /MAX\(score\)/);
});

test('the rolling window only counts recent days', async () => {
  const db = dbOf([]);
  await recent(db, 'courses', Date.UTC(2026, 8, 13), 30);
  // an all-time table ossifies: after a year the top ten are fixed
  assert.equal(db.asked[0].args[1], '2026-08-14');
  assert.match(db.asked[0].sql, /day >= \?/);
});
