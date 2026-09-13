/**
 * Quarry's balance harness.
 *
 * Not a test - a measurement. It plays the simulation with scripted
 * players at several skill levels across several seeds and reports the
 * score spread and how runs end, which is the only way to know whether a
 * constant is doing what it looks like it does.
 *
 * slop-out's PUNCHLIST.md is the model, and its findings are what this
 * exists to catch: a 9.8x cliff between skill bands, and a configuration
 * where nobody ever cleared a wall. Both are invisible from reading the
 * code.
 *
 *   node test/quarry-balance.mjs [runs-per-band]
 */

import {
  ACTIONS,
  BALL_SPEED,
  FIELD_W,
  MAX_TICKS,
  PADDLE_W,
  TICKS_PER_SECOND,
  createState,
  applyAction,
  stepTick,
} from '../src/game/quarry.js';
import { seedFor } from '../src/game/logic.js';

/**
 * A scripted player.
 *
 * `error` is how far its aim is off, in sub-pixels, and `reaction` is how
 * many ticks it waits before re-aiming. Together they span from a player
 * who barely tracks the ball to one who cannot miss.
 */
const BANDS = [
  { name: 'novice', error: 64, reaction: 14 },
  { name: 'casual', error: 32, reaction: 8 },
  { name: 'decent', error: 12, reaction: 4 },
  { name: 'perfect', error: 0, reaction: 1 },
];

function play(seed, band) {
  const state = createState(seed);
  const events = [];
  let lastAim = -1;
  let lastTarget = state.target;

  const emit = (action, value) => {
    events.push([action, state.tick, value]);
    applyAction(state, action, value);
  };

  // a cheap deterministic wobble, so a band's error is reproducible
  let noise = seed >>> 0;
  const wobble = (range) => {
    if (range === 0) return 0;
    noise = (Math.imul(noise ^ (noise >>> 15), 0x2c1b3c6d) + 1) >>> 0;
    return (noise % (range * 2 + 1)) - range;
  };

  while (!state.over && state.tick < MAX_TICKS) {
    if (state.held) {
      emit(ACTIONS.LAUNCH);
    } else if (state.tick - lastAim >= band.reaction && state.balls.length) {
      // aim at the ball that will reach the paddle first - unless a
      // capsule is closer to the bottom than every ball, which is the
      // choice the genre is actually about. A scripted player that only
      // ever tracks the ball never catches a capsule, and then multi-ball
      // never happens and no wall is ever clearable; that is a harness
      // that measures the wrong game.
      let lowest = state.balls[0];
      for (const ball of state.balls) if (ball.y > lowest.y) lowest = ball;
      for (const capsule of state.capsules) {
        if (capsule.y > lowest.y) lowest = capsule;
      }
      const aim = Math.max(
        0,
        Math.min(FIELD_W - PADDLE_W, lowest.x - (PADDLE_W >> 1) + wobble(band.error)),
      );
      // Sampled, and only on a real change: this is what slop-out measured
      // at 9.7 events/sec against 60 for logging every tick. Aiming within
      // a paddle-width of where you already aimed changes nothing the
      // paddle can act on, so it is not worth an event.
      if (Math.abs(aim - lastTarget) >= SAMPLE) {
        emit(ACTIONS.TARGET, aim);
        lastTarget = aim;
      }
      lastAim = state.tick;
    }
    stepTick(state);
  }

  return {
    score: state.score,
    level: state.level,
    bricks: state.bricksBroken,
    ticks: state.tick,
    events: events.length,
    ending: state.lives <= 0 ? 'lost' : 'time',
  };
}

// How far the aim must move before it is worth an event. A quarter of the
// paddle: below that the paddle covers the difference anyway.
const SAMPLE = PADDLE_W >> 2;

const runs = Number(process.argv[2] ?? 8);
const rows = [];

for (const band of BANDS) {
  const results = [];
  for (let i = 0; i < runs; i++) {
    results.push(play(seedFor('quarry', `2026-09-${String(13 + i).padStart(2, '0')}`), band));
  }
  const scores = results.map((r) => r.score).sort((a, b) => a - b);
  const mean = Math.round(scores.reduce((a, b) => a + b, 0) / scores.length);
  rows.push({
    band: band.name,
    low: scores[0],
    median: scores[scores.length >> 1],
    high: scores[scores.length - 1],
    mean,
    levels: (results.reduce((a, r) => a + r.level, 0) / runs).toFixed(1),
    bricks: Math.round(results.reduce((a, r) => a + r.bricks, 0) / runs),
    events: Math.round(results.reduce((a, r) => a + r.events, 0) / runs),
    lost: results.filter((r) => r.ending === 'lost').length,
    secs: (results.reduce((a, r) => a + r.ticks, 0) / runs / TICKS_PER_SECOND).toFixed(1),
  });
}

console.log(`Quarry balance, ${runs} seeds per band\n`);
console.log(
  ['band', 'low', 'median', 'high', 'mean', 'levels', 'bricks', 'events', 'lost', 'secs']
    .map((h) => h.padStart(8))
    .join(''),
);
for (const r of rows) {
  console.log(
    [r.band, r.low, r.median, r.high, r.mean, r.levels, r.bricks, r.events, `${r.lost}/${runs}`, r.secs]
      .map((c) => String(c).padStart(8))
      .join(''),
  );
}

// The two numbers worth stating outright, because they are the ones
// slop-out's harness existed to find.
const novice = rows[0].mean || 1;
const perfect = rows[rows.length - 1].mean;
console.log(`\nskill cliff (perfect / novice): ${(perfect / novice).toFixed(1)}x`);
console.log(
  `events per second at the top band: ` +
    `${(rows[rows.length - 1].events / Number(rows[rows.length - 1].secs)).toFixed(1)}`,
);
console.log(`ball speed ${BALL_SPEED} sub-pixels/step, paddle ${PADDLE_W}`);
