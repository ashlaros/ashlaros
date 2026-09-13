/**
 * The rules Quarry's leaderboard rests on.
 *
 * Not tests of plumbing: each one is a property that, if it broke, would
 * silently turn the board into a ranking of something other than play -
 * the same bar the Courses tests are held to.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';

import worker from '../src/index.js';
import { bucketOf } from './helpers.mjs';
import { verify } from '../src/game/scores.js';
import {
  ACTIONS,
  BALL_SPEED,
  BRICK_COLS,
  BRICK_ROWS,
  EMPTY,
  FIELD_W,
  MAX_EVENTS,
  MAX_TICKS,
  PADDLE_SPEED,
  PADDLE_W,
  SOLID,
  applyAction,
  cleared,
  createState,
  replay,
  stepTick,
  validateEvents,
  wallAt,
} from '../src/game/quarry.js';

const aim = (x) => [ACTIONS.TARGET, 0, x];

test('the same seed and inputs give the same score, every time', () => {
  // the property the whole design rests on: the page plays this and the
  // verifier replays it, on two different engines
  const events = [[ACTIONS.LAUNCH, 0], aim(200), [ACTIONS.TARGET, 300, 900]];
  const a = replay(12345, events);
  const b = replay(12345, events);
  assert.equal(a.score, b.score);
  assert.equal(a.tick, b.tick);
  assert.equal(a.bricksBroken, b.bricksBroken);
});

test('a different seed is a different game', () => {
  const events = [[ACTIONS.LAUNCH, 0], aim(400)];
  const one = wallAt(1, 0);
  const two = wallAt(2, 0);
  assert.notDeepEqual(Array.from(one), Array.from(two));
  // and it is stable for a given seed, or the verifier rebuilds a
  // different wall than the player broke
  assert.deepEqual(Array.from(wallAt(1, 0)), Array.from(one));
  assert.ok(replay(1, events).tick > 0);
});

test('the paddle cannot move faster than its speed', () => {
  // the cap is a verification requirement: uncapped, every paddle
  // position at every tick is legal and the verifier has nothing to
  // reject
  const state = createState(7);
  applyAction(state, ACTIONS.TARGET, FIELD_W);
  const before = state.paddleX;
  stepTick(state);
  assert.ok(state.paddleX - before <= PADDLE_SPEED);
});

test('the paddle never leaves the field, however it is aimed', () => {
  const state = createState(7);
  for (const target of [-99999, 99999, FIELD_W * 4]) {
    applyAction(state, ACTIONS.TARGET, target);
    for (let i = 0; i < 200; i++) stepTick(state);
    assert.ok(state.paddleX >= 0, `paddle at ${state.paddleX}`);
    assert.ok(state.paddleX + state.paddleW <= FIELD_W);
  }
});

test('every quantity the simulation touches stays an integer', () => {
  // floats are where two engines drift apart, and this has ball physics -
  // a position advanced and reflected every tick is exactly the place it
  // would happen
  const state = createState(99);
  applyAction(state, ACTIONS.LAUNCH);
  for (let i = 0; i < 600; i++) {
    stepTick(state);
    for (const ball of state.balls) {
      assert.ok(Number.isInteger(ball.x) && Number.isInteger(ball.y), 'ball position');
      assert.ok(Number.isInteger(ball.vx) && Number.isInteger(ball.vy), 'ball velocity');
    }
    for (const capsule of state.capsules) {
      assert.ok(Number.isInteger(capsule.x) && Number.isInteger(capsule.y), 'capsule');
    }
    assert.ok(Number.isInteger(state.paddleX) && Number.isInteger(state.score));
  }
});

test('the paddle centre never returns the ball straight up', () => {
  // a vertical return is a soft-lock and a stalling strategy: slop-out
  // measured a perfect tracker scoring 33 points in 120s and never losing
  // the ball
  const state = createState(3);
  applyAction(state, ACTIONS.LAUNCH);
  // put a ball dead centre, falling
  const centre = state.paddleX + (state.paddleW >> 1);
  state.balls = [{ x: centre, y: 4000, vx: 0, vy: BALL_SPEED }];
  for (let i = 0; i < 40 && state.balls.length; i++) stepTick(state);
  for (const ball of state.balls) {
    assert.notEqual(ball.vx, 0, 'a centred bounce returned straight up');
  }
});

test('a run ends, whatever the player does or does not do', () => {
  // no input at all: the ball is never launched and the clock still runs
  const idle = replay(5, []);
  assert.ok(idle.over);
  assert.ok(idle.tick <= MAX_TICKS);
});

test('an indestructible brick never breaks and never blocks a clear', () => {
  const bricks = wallAt(42, 3);
  let solids = 0;
  for (let i = 0; i < bricks.length; i++) if (bricks[i] === SOLID) solids += 1;
  // a wall made only of solids could never be cleared and the run would
  // stall at full score
  assert.ok(solids < bricks.length);
  // cleared() must ignore them, or a level with one solid brick never ends
  const onlySolid = new Int8Array(BRICK_COLS * BRICK_ROWS).fill(EMPTY);
  onlySolid[0] = SOLID;
  assert.equal(cleared(onlySolid), true);
});

test('the wall is reachable: no solid brick sits on the bottom row', () => {
  // a solid brick on the bottom row can wall off the only approach to
  // what is above it, which is a level that cannot be finished
  for (let level = 0; level < 6; level++) {
    const bricks = wallAt(7, level);
    for (let col = 0; col < BRICK_COLS; col++) {
      const index = (BRICK_ROWS - 1) * BRICK_COLS + col;
      assert.notEqual(bricks[index], SOLID, `solid on the bottom row of level ${level}`);
    }
  }
});

test('a crafted event log is refused before anything replays it', () => {
  assert.ok(validateEvents('nope'));
  assert.ok(validateEvents([[0, 5], [0, 4]]), 'ticks going backwards');
  assert.ok(validateEvents([[0, 1.5]]), 'a fractional tick');
  assert.ok(validateEvents([[0, 0], [0, 0], [0, 0], [0, 0], [0, 0]]), 'packed into one tick');
  assert.ok(validateEvents(Array.from({ length: MAX_EVENTS + 1 }, () => [0, 0])), 'too many');
  assert.ok(validateEvents([[0, MAX_TICKS + 1]]), 'past the end of a run');
  assert.equal(validateEvents([[ACTIONS.TARGET, 0, 100]]), null);
});

test('a wall is clearable inside a run, at the measured clear rate', () => {
  // The harness found the opposite twice: at 8 rows a wall took 137 hits
  // against a perfect player's 34, so no band ever finished a level and
  // the level bonus was unreachable code. This pins the sizing rather
  // than the outcome - the rate is a property of the ball's round trip.
  let hits = 0;
  for (let seed = 0; seed < 8; seed++) {
    const bricks = wallAt(seed, 0);
    for (const tier of bricks) if (tier !== EMPTY && tier !== SOLID) hits += tier;
  }
  const average = hits / 8;
  // 0.46 bricks/second is the measured ceiling for a perfect tracker
  assert.ok(average / 0.46 < MAX_TICKS / 60, `a wall needs ${average} hits, too many to clear`);
});

test('a quarry run is scored by quarry, not by the other game', () => {
  // one verify() serving two simulations is exactly where a wrong default
  // would silently score every run of one game with the other's rules
  const events = [[ACTIONS.LAUNCH, 0], aim(400)];
  const quarry = verify('quarry', 77, events);
  assert.ok(Number.isInteger(quarry.score));
  // the detail column is the games' own: bricks here, lines there, and
  // mixing them would put one game's number under the other's heading
  assert.equal(quarry.lines, replay(77, events).bricksBroken);
  // and Courses refuses this log outright rather than scoring it as its
  // own - a [action, tick, value] triple is not one of its events
  assert.throws(() => verify('courses', 77, events), /\[action, tick\]/);
});

test('an unknown game is refused rather than given a board of its own', async () => {
  // a typo that returns a seed and an empty board looks like a working
  // game, and every run played on it is unrecoverable
  const env = { ISO: bucketOf([]), DOCS: { fetch: async () => new Response('docs') } };
  for (const path of ['game/seed?game=nope', 'game/board?game=nope']) {
    const res = await worker.fetch(
      new Request(`https://iso.ashlaros.download/${path}`),
      env,
      {},
    );
    assert.equal(res.status, 404, path);
  }
});

test('both games answer on their own seeds', async () => {
  const env = { ISO: bucketOf([]), DOCS: { fetch: async () => new Response('docs') } };
  const seeds = {};
  for (const game of ['courses', 'quarry']) {
    const res = await worker.fetch(
      new Request(`https://iso.ashlaros.download/game/seed?game=${game}`),
      env,
      {},
    );
    assert.equal(res.status, 200);
    seeds[game] = (await res.json()).seed;
  }
  // the same day must not hand both games the same wall and bag
  assert.notEqual(seeds.courses, seeds.quarry);
});
