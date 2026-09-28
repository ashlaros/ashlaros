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
  BALL_R,
  BALL_SPEED,
  BALL_SPEED_MAX,
  BRICK_COLS,
  BRICK_W,
  FIELD_W,
  MAX_TICKS,
  PADDLE_W,
  PADDLE_Y,
  TICKS_PER_SECOND,
  createState,
  applyAction,
  stepTick,
} from '../src/game/quarry.js';
import { seedFor } from '../src/game/logic.js';

/**
 * A scripted player.
 *
 * Every band reads the bounce - people do - and they differ in how badly
 * and how late. `error` is how far a read can be off, in sub-pixels, at
 * the start speed on a steep ball; it grows with the ball's speed and
 * with how shallow its path is, because that is what makes a real read
 * harder. `reaction` is how many ticks pass before re-aiming. The top
 * band also aims off-centre to send the return at the toughest column,
 * which is the skill the paddle deflection exists for.
 *
 * An earlier version of this harness tracked the ball's current x with a
 * perfect aim. That player lost to any fast diagonal and the harness
 * reported the game unwinnable at every band, which measured the script
 * rather than the game.
 */
const BANDS = [
  { name: 'novice', error: 260, reaction: 18 },
  { name: 'casual', error: 170, reaction: 10 },
  { name: 'decent', error: 90, reaction: 6 },
  { name: 'expert', error: 30, reaction: 3, steer: true },
];

/** Fold an x position back into the field, as the side walls would. */
function fold(x) {
  const span = FIELD_W - 2 * BALL_R;
  const t = (((x - BALL_R) % (2 * span)) + 2 * span) % (2 * span);
  return BALL_R + (t > span ? 2 * span - t : t);
}

/** Where a ball will next cross the paddle line, ignoring bricks. */
function landing(ball) {
  const rise = ball.vy < 0 ? ball.y - BALL_R + (PADDLE_Y - BALL_R) : PADDLE_Y - BALL_R - ball.y;
  return fold(ball.x + (ball.vx * rise) / Math.abs(ball.vy));
}

function play(seed, band) {
  const state = createState(seed);
  const events = [];
  let lastAim = -1;
  let lastTarget = state.target;
  let peak = state.speed;

  const emit = (action, value) => {
    events.push([action, state.tick, value]);
    applyAction(state, action, value);
  };

  // a cheap deterministic wobble, so a band's error is reproducible
  let noise = (seed ^ 0x9e37) >>> 0;
  const wobble = (range) => {
    const r = Math.round(range);
    if (r === 0) return 0;
    noise = (Math.imul(noise ^ (noise >>> 15), 0x2c1b3c6d) + 1) >>> 0;
    return (noise % (r * 2 + 1)) - r;
  };

  while (!state.over && state.tick < MAX_TICKS) {
    if (state.held) {
      emit(ACTIONS.LAUNCH);
    } else if (state.tick - lastAim >= band.reaction && state.balls.length) {
      // the falling ball nearest the paddle, else the one coming soonest
      let ball = state.balls[0];
      for (const b of state.balls) {
        const falling = (b.vy > 0) - (ball.vy > 0);
        if (falling > 0 || (falling === 0 && b.y > ball.y)) ball = b;
      }
      let x = landing(ball);
      const hard =
        (Math.abs(ball.vy) / BALL_SPEED) * (1 + Math.abs(ball.vx) / Math.max(1, Math.abs(ball.vy)));
      let offset = 0;
      if (band.steer && ball.vy > 0) {
        const weight = new Array(BRICK_COLS).fill(0);
        state.bricks.forEach((tier, i) => {
          if (tier > 0) weight[i % BRICK_COLS] += tier;
        });
        const heaviest = weight.indexOf(Math.max(...weight));
        offset = (heaviest * BRICK_W + (BRICK_W >> 1) < x ? -1 : 1) * (state.paddleW >> 2);
      }
      // a capsule lower than a rising ball is the choice the genre is
      // about; a player who never takes it never sees multi-ball
      for (const capsule of state.capsules) {
        if (ball.vy < 0 && capsule.y > ball.y) {
          x = capsule.x;
          offset = 0;
        }
      }
      const aim = Math.max(
        0,
        Math.min(FIELD_W - state.paddleW, x - offset - (state.paddleW >> 1) + wobble(band.error * hard)),
      );
      // Sampled, and only on a real change: this is what slop-out measured
      // at 9.7 events/sec against 60 for logging every tick.
      if (Math.abs(aim - lastTarget) >= SAMPLE) {
        emit(ACTIONS.TARGET, aim);
        lastTarget = aim;
      }
      lastAim = state.tick;
    }
    stepTick(state);
    peak = Math.max(peak, state.speed);
  }

  return {
    score: state.score,
    level: state.level,
    bricks: state.bricksBroken,
    ticks: state.tick,
    events: events.length,
    lives: Math.max(0, state.lives),
    peak,
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
    lives: (results.reduce((a, r) => a + r.lives, 0) / runs).toFixed(1),
    peak: Math.round(results.reduce((a, r) => a + r.peak, 0) / runs),
    lost: results.filter((r) => r.ending === 'lost').length,
    secs: (results.reduce((a, r) => a + r.ticks, 0) / runs / TICKS_PER_SECOND).toFixed(1),
  });
}

console.log(`Quarry balance, ${runs} seeds per band\n`);
console.log(
  ['band', 'low', 'median', 'high', 'mean', 'levels', 'bricks', 'events', 'lives', 'peak', 'lost', 'secs']
    .map((h) => h.padStart(8))
    .join(''),
);
for (const r of rows) {
  console.log(
    [r.band, r.low, r.median, r.high, r.mean, r.levels, r.bricks, r.events, r.lives, r.peak, `${r.lost}/${runs}`, r.secs]
      .map((c) => String(c).padStart(8))
      .join(''),
  );
}

// The two numbers worth stating outright, because they are the ones
// slop-out's harness existed to find.
const novice = rows[0].mean || 1;
const expert = rows[rows.length - 1].mean;
console.log(`\nskill cliff (expert / novice): ${(expert / novice).toFixed(1)}x`);
console.log(
  `events per second at the top band: ` +
    `${(rows[rows.length - 1].events / Number(rows[rows.length - 1].secs)).toFixed(1)}`,
);
console.log(`ball speed ${BALL_SPEED}..${BALL_SPEED_MAX} sub-pixels/step, paddle ${PADDLE_W}`);
