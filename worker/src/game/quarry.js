/**
 * Quarry: the block breaker.
 *
 * Named from the ashlar vocabulary, like Courses. "Arkanoid" is Taito's
 * and "Breakout" is Atari's - mechanics are not copyrightable, names are.
 *
 * Same design as Courses and for the same reasons (worker/src/game/logic.js):
 * the seed is the only source of world state, time is a tick index and
 * never a wall clock, the replay IS the submission, and every quantity the
 * simulation touches is an integer.
 *
 * Integers matter more here than they do in a falling-block game. This has
 * ball physics - a position and a velocity advanced every tick and
 * reflected off surfaces - which is exactly where two engines drift apart
 * if either uses floats. So positions are in sub-pixels at a power-of-two
 * resolution: SUB = 16 means one pixel is 16 units and a shift replaces a
 * divide, with no rounding to disagree about.
 *
 * The replay logs the paddle's TARGET, never its position. The paddle
 * closes on the target at a fixed speed, so the server derives where it
 * actually went rather than being told. slop-out measured the difference:
 * 60 events/sec logging position every tick, 9.7 logging a sampled target.
 */

import { hash32 } from './logic.js';

export const TICKS_PER_SECOND = 60;

// One pixel is SUB units. A power of two, so every divide in the physics
// is a shift and nothing rounds.
export const SUB = 16;
const px = (n) => n * SUB;

export const FIELD_W = px(240);
export const FIELD_H = px(320);

export const PADDLE_W = px(40);
export const PADDLE_H = px(4);
export const PADDLE_Y = FIELD_H - px(16);
// The cap is a verification requirement, not a difficulty choice: with an
// uncapped paddle every position at every tick is legal and the verifier
// has nothing to reject. slop-out broke from the original here too.
// Faster than the ball, and that is a measurement rather than a taste.
// The balance harness found every band losing inside 9 seconds with the
// paddle at px(4): the ball advances 96 sub-pixels a tick against the
// paddle's 64, so it crosses the field in 40 ticks where the paddle needs
// 60. No amount of skill closes a gap the paddle cannot physically close,
// which is slop-out's "the ceiling is the ball's round-trip time" from
// the other direction.
export const PADDLE_SPEED = px(7);

export const BALL_R = px(3);
export const BALL_SPEED = px(3);

export const BRICK_W = px(24);
export const BRICK_H = px(10);
export const BRICK_COLS = 8;
// Five rows, not eight, and the harness is why. At eight rows a wall took
// 137 hits to clear and a perfect player landed 32 in a two-minute run -
// so no band ever finished a level and the 1000-point bonus was
// unreachable code. This is slop-out's "nobody ever cleared a wall"
// verbatim, and the same lesson: the bottleneck is the ball's round trip,
// so the wall has to fit inside it.
export const BRICK_ROWS = 4;
export const BRICK_TOP = px(40);

// A run is bounded, like Courses: without a ceiling the board ranks
// whoever had a free afternoon rather than whoever played best.
export const MAX_TICKS = 120 * TICKS_PER_SECOND;
export const MAX_EVENTS = 4000;
export const MAX_EVENTS_PER_TICK = 4;
export const MAX_BALLS = 5;
export const START_LIVES = 3;

/**
 * Brick tiers. The value is how many hits it takes; 0 is empty and -1 is
 * indestructible, which is Arkanoid's silver brick and the reason a level
 * needs designing rather than filling.
 */
export const EMPTY = 0;
export const SOLID = -1;

export const BRICK_SCORES = [0, 50, 100, 200];

export const ACTIONS = {
  /** aim the paddle at a column of the field, in sub-pixels */
  TARGET: 0,
  /** release a held ball, or launch the first one */
  LAUNCH: 1,
};

/**
 * Capsules, all positive.
 *
 * Shatter's choice, and the better one: the difficulty comes from
 * multi-ball making the board harder to survive, not from a pickup that
 * punishes you for catching it. A falling capsule is already a second
 * thing to chase while keeping the ball alive, which is the whole point.
 */
export const CAPSULES = {
  WIDEN: 0,
  MULTI: 1,
  SLOW: 2,
  CATCH: 3,
};
const CAPSULE_KINDS = 4;
export const CAPSULE_SPEED = px(1);
export const CAPSULE_SCORE = 100;
// One brick in three drops something, and that rate is a measurement.
// slop-out's finding is the governing one here: "a single ball cannot
// clear a wall in a short round - no amount of tuning fixes that, because
// the ceiling is the ball's round-trip time. Multi-ball is what makes a
// wall clearable, not a difficulty knob." At one in eight the harness
// showed a perfect player landing 31 hits against a wall needing 89, and
// multi-ball arriving too rarely to close the gap. Seeded per brick, so
// the same wall gives every player the same capsules in the same places.
const CAPSULE_CHANCE = 3;

/**
 * The wall for a level.
 *
 * Designed rather than uniform: a solid brick sits where it forces the
 * ball around it, and the tiers rise toward the top so breaking upward is
 * worth more. Seeded, so every player on a day faces the same wall.
 */
export function wallAt(seed, level) {
  const bricks = new Int8Array(BRICK_COLS * BRICK_ROWS);
  for (let row = 0; row < BRICK_ROWS; row++) {
    for (let col = 0; col < BRICK_COLS; col++) {
      const roll = hash32(seed, (level * 256 + row) * 16 + col) % 100;
      let tier;
      if (roll < 8 + level * 2) {
        // indestructible, and never on the bottom row: a solid brick
        // there can wall off the only approach to what is above it
        tier = row < BRICK_ROWS - 2 ? SOLID : 1;
      } else if (roll < 34) {
        // a third of the wall is gaps, which is what lets a ball through
        // to work on the top rows rather than grinding the bottom one -
        // the cavities slop-out took from Super Breakout, and the reason
        // a designed wall beats a filled rectangle
        tier = EMPTY;
      } else {
        // the higher rows are tougher, so clearing upward is the ladder -
        // but only the top row is a three-hit brick. A wall where most
        // bricks take two or three hits is two or three walls, and the
        // measured clear rate cannot pay for it.
        tier = row === 0 ? 3 : row === 1 ? 2 : 1;
      }
      bricks[row * BRICK_COLS + col] = tier;
    }
  }
  return bricks;
}

export function createState(seed) {
  return {
    seed,
    tick: 0,
    level: 0,
    score: 0,
    lives: START_LIVES,
    bricks: wallAt(seed, 0),
    paddleX: (FIELD_W - PADDLE_W) >> 1,
    paddleW: PADDLE_W,
    target: (FIELD_W - PADDLE_W) >> 1,
    balls: [],
    capsules: [],
    // a ball waiting on the paddle, which is where every life starts
    held: true,
    catching: false,
    slow: 0,
    over: false,
    bricksBroken: 0,
  };
}

function spawnBall(state, vx) {
  if (state.balls.length >= MAX_BALLS) return;
  state.balls.push({
    x: state.paddleX + (state.paddleW >> 1),
    y: PADDLE_Y - BALL_R,
    vx,
    vy: -BALL_SPEED,
  });
}

/** The brick index a point is inside, or -1. */
export function brickAt(x, y) {
  if (y < BRICK_TOP) return -1;
  const row = Math.floor((y - BRICK_TOP) / BRICK_H);
  const col = Math.floor(x / BRICK_W);
  if (row < 0 || row >= BRICK_ROWS || col < 0 || col >= BRICK_COLS) return -1;
  return row * BRICK_COLS + col;
}

function hitBrick(state, index) {
  const tier = state.bricks[index];
  if (tier === EMPTY || tier === SOLID) return false;
  const left = tier - 1;
  state.bricks[index] = left;
  if (left === EMPTY) {
    state.score += BRICK_SCORES[Math.min(tier, BRICK_SCORES.length - 1)];
    state.bricksBroken += 1;
    maybeDropCapsule(state, index);
  } else {
    // a partial hit still scores, or a three-tier brick pays nothing for
    // the two hits that did the work
    state.score += 10;
  }
  return true;
}

function maybeDropCapsule(state, index) {
  // seeded on the brick, not on a counter: which bricks drop is a property
  // of the wall, so two players who break the same brick get the same
  // capsule whatever order they got there in
  if (hash32(state.seed, 0x5eed0000 + index) % CAPSULE_CHANCE !== 0) return;
  const row = Math.floor(index / BRICK_COLS);
  const col = index % BRICK_COLS;
  state.capsules.push({
    x: col * BRICK_W + (BRICK_W >> 1),
    y: BRICK_TOP + row * BRICK_H + (BRICK_H >> 1),
    kind: hash32(state.seed, 0xca950000 + index) % CAPSULE_KINDS,
  });
}

function applyCapsule(state, kind) {
  state.score += CAPSULE_SCORE;
  switch (kind) {
    case CAPSULES.WIDEN:
      state.paddleW = Math.min(state.paddleW + px(8), px(64));
      break;
    case CAPSULES.MULTI: {
      // every ball splits, not just the first: one ball plus one is a
      // slightly better single ball, where two plus two is the pressure
      // the genre is built on. Each new ball mirrors its parent, so the
      // split is deterministic rather than seeded - the verifier gets the
      // same pair the player saw.
      const born = [];
      for (const source of state.balls) {
        if (state.balls.length + born.length >= MAX_BALLS) break;
        born.push({ x: source.x, y: source.y, vx: -source.vx, vy: source.vy });
      }
      state.balls.push(...born);
      break;
    }
    case CAPSULES.SLOW:
      state.slow = 10 * TICKS_PER_SECOND;
      break;
    case CAPSULES.CATCH:
      state.catching = true;
      break;
  }
}

export function applyAction(state, action, value) {
  if (state.over) return state;
  switch (action) {
    case ACTIONS.TARGET:
      // clamped here rather than trusted: a submission naming a target
      // off the field would otherwise drag the paddle somewhere the game
      // cannot put it
      state.target = Math.max(0, Math.min(FIELD_W - state.paddleW, value | 0));
      break;
    case ACTIONS.LAUNCH:
      if (state.held) {
        state.held = false;
        spawnBall(state, BALL_SPEED >> 1);
      }
      break;
  }
  return state;
}

/**
 * Reflect a ball off the paddle.
 *
 * The centre of the paddle must never return the ball straight up: a
 * vertical return is a soft-lock and a stalling strategy, and slop-out
 * measured a perfect tracker scoring 33 points in 120s while never losing
 * the ball. So the deflection is by offset from centre with a floor on
 * the horizontal component.
 */
function bounceOffPaddle(state, ball) {
  const centre = state.paddleX + (state.paddleW >> 1);
  const offset = ball.x - centre;
  // scale the offset into a horizontal velocity, integer-only
  let vx = Math.trunc((offset * BALL_SPEED * 2) / (state.paddleW >> 1));
  const floor = BALL_SPEED >> 2;
  if (vx > -floor && vx < floor) vx = offset < 0 ? -floor : floor;
  ball.vx = Math.max(-BALL_SPEED * 2, Math.min(BALL_SPEED * 2, vx));
  ball.vy = -BALL_SPEED;
  ball.y = PADDLE_Y - BALL_R;
}

function stepBall(state, ball) {
  const steps = state.slow > 0 ? 1 : 2;
  for (let s = 0; s < steps; s++) {
    ball.x += ball.vx;
    ball.y += ball.vy;

    if (ball.x - BALL_R < 0) {
      ball.x = BALL_R;
      ball.vx = -ball.vx;
    } else if (ball.x + BALL_R > FIELD_W) {
      ball.x = FIELD_W - BALL_R;
      ball.vx = -ball.vx;
    }
    if (ball.y - BALL_R < 0) {
      ball.y = BALL_R;
      ball.vy = -ball.vy;
    }

    const index = brickAt(ball.x, ball.y);
    if (index >= 0) {
      const tier = state.bricks[index];
      if (tier !== EMPTY) {
        hitBrick(state, index);
        ball.vy = -ball.vy;
        ball.y += ball.vy;
      }
    }

    if (
      ball.vy > 0 &&
      ball.y + BALL_R >= PADDLE_Y &&
      ball.y - BALL_R <= PADDLE_Y + PADDLE_H &&
      ball.x >= state.paddleX &&
      ball.x <= state.paddleX + state.paddleW
    ) {
      if (state.catching) {
        state.held = true;
        state.catching = false;
        return true;
      }
      bounceOffPaddle(state, ball);
    }
  }
  return ball.y - BALL_R <= FIELD_H;
}

function stepCapsules(state) {
  const kept = [];
  for (const capsule of state.capsules) {
    capsule.y += CAPSULE_SPEED;
    const caught =
      capsule.y >= PADDLE_Y &&
      capsule.y <= PADDLE_Y + PADDLE_H + CAPSULE_SPEED &&
      capsule.x >= state.paddleX &&
      capsule.x <= state.paddleX + state.paddleW;
    if (caught) {
      applyCapsule(state, capsule.kind);
    } else if (capsule.y < FIELD_H) {
      kept.push(capsule);
    }
  }
  state.capsules = kept;
}

/** Whether anything breakable is left. */
export function cleared(bricks) {
  for (let i = 0; i < bricks.length; i++) {
    const tier = bricks[i];
    if (tier !== EMPTY && tier !== SOLID) return false;
  }
  return true;
}

export function stepTick(state) {
  if (state.over) return state;
  state.tick += 1;
  if (state.slow > 0) state.slow -= 1;

  // The paddle closes on the target at a fixed speed. This is what makes
  // the replay verifiable: the client says where it aimed, and the server
  // works out where the paddle actually reached.
  const delta = state.target - state.paddleX;
  if (delta > PADDLE_SPEED) state.paddleX += PADDLE_SPEED;
  else if (delta < -PADDLE_SPEED) state.paddleX -= PADDLE_SPEED;
  else state.paddleX = state.target;
  state.paddleX = Math.max(0, Math.min(FIELD_W - state.paddleW, state.paddleX));

  if (state.held) {
    stepCapsules(state);
    if (state.tick >= MAX_TICKS) state.over = true;
    return state;
  }

  const alive = [];
  for (const ball of state.balls) {
    if (stepBall(state, ball) && !state.held) alive.push(ball);
  }
  state.balls = alive;

  stepCapsules(state);

  if (!state.balls.length && !state.held) {
    state.lives -= 1;
    // the paddle loses its widening with the life, or a single good run
    // makes every later one easier
    state.paddleW = PADDLE_W;
    state.catching = false;
    state.slow = 0;
    if (state.lives <= 0) state.over = true;
    else state.held = true;
  }

  if (cleared(state.bricks)) {
    state.level += 1;
    state.score += 1000;
    state.bricks = wallAt(state.seed, state.level);
    state.balls = [];
    state.capsules = [];
    state.held = true;
    state.paddleW = PADDLE_W;
  }

  if (state.tick >= MAX_TICKS) state.over = true;
  return state;
}

/**
 * Replay an event log and return the final state.
 *
 * The same function the page plays with, which is the property the whole
 * design rests on: one implementation, two engines, the same answer.
 */
export function replay(seed, events) {
  const state = createState(seed);
  let index = 0;
  let guard = 0;
  while (!state.over && guard < MAX_TICKS + 1) {
    guard += 1;
    while (index < events.length && events[index][1] === state.tick) {
      const [action, , value] = events[index];
      applyAction(state, action, value);
      index += 1;
    }
    stepTick(state);
  }
  return state;
}

/**
 * Whether an event log is shaped like something a player could produce.
 *
 * Cheap checks only - this runs in the fetch handler, inside its 10ms,
 * before a Durable Object is woken to do the replay.
 */
export function validateEvents(events) {
  if (!Array.isArray(events)) return 'events must be an array';
  if (events.length > MAX_EVENTS) return 'too many events';
  let previous = -1;
  let perTick = 0;
  for (const event of events) {
    if (!Array.isArray(event) || event.length < 2) return 'each event is [action, tick, value]';
    const [action, tick, value] = event;
    if (!Number.isInteger(action) || !Number.isInteger(tick)) {
      return 'action and tick must be integers';
    }
    if (value !== undefined && !Number.isInteger(value)) return 'value must be an integer';
    if (tick < previous) return 'ticks must not go backwards';
    if (tick > MAX_TICKS) return 'tick beyond the end of a run';
    perTick = tick === previous ? perTick + 1 : 1;
    if (perTick > MAX_EVENTS_PER_TICK) return 'too many events in one tick';
    previous = tick;
  }
  return null;
}
