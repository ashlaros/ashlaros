/**
 * The falling-block simulation. Pure, integer-only, no I/O.
 *
 * This module is the single implementation: the page imports it to play and
 * the verifier imports it to replay. A second implementation is the thing
 * this design exists to avoid - if the two ever disagree, every honest
 * score is rejected and the leaderboard is worthless.
 *
 * Rules it follows, with slopduel's GAME-RULES.md identifiers:
 *
 * R1.1  the seed is the only source of world state. The piece sequence is a
 *       function of the seed and nothing else, which is what makes a
 *       leaderboard a comparison of play rather than of luck.
 * R1.2  Math.random() appears nowhere in this file. Not "only for visuals" -
 *       nowhere, so the question of whether a call can reach the score
 *       cannot arise.
 * R1.3  the bag is addressable: bagAt(seed, n) is a pure function of its
 *       arguments, so the verifier can jump to piece n rather than
 *       re-shuffling everything before it.
 * R1.4  nothing here reads a clock, a locale, a terminal size or an
 *       environment variable.
 * R2.1  time is a tick index, never milliseconds. The simulation is
 *       discrete, so a timestamp would be a lossier way of naming the same
 *       integer - and a suspended tab owes the simulation nothing, so
 *       there is no late timestamp to reject and no tolerance to tune.
 *
 * Integers only, everywhere. Two engines agreeing on integer arithmetic is
 * a property of the arithmetic; agreeing on floats is a hope.
 */

// One tick is one simulation step. The renderer may draw at any rate it
// likes; it may not invent ticks.
export const TICKS_PER_SECOND = 60;

export const WIDTH = 10;
export const HEIGHT = 20;
// Pieces spawn above the visible field, as the Guideline expects, so a
// spawn that overlaps is a top-out rather than a piece drawn off-screen.
export const SPAWN_ROWS = 2;
export const TOTAL_HEIGHT = HEIGHT + SPAWN_ROWS;

// A run is bounded, deliberately. Without a ceiling a strong player plays
// until they get bored and the board ranks whoever had a free afternoon -
// the failure slop-out found when its wall advanced on a clock. The
// gravity curve below also tops everyone out eventually; this is the
// backstop that makes the bound explicit rather than emergent.
export const MAX_PIECES = 300;

// Guideline scoring. The risk/reward curve is the thing that makes a score
// worth comparing: clearing four at once is worth eight singles, so the
// board ranks players willing to build a well and hold for an I.
export const LINE_SCORES = [0, 100, 300, 500, 800];
export const SOFT_DROP_POINTS = 1;
export const HARD_DROP_POINTS = 2;
// back-to-back tetris, as the Guideline has it
export const BACK_TO_BACK_MULTIPLIER = 3;
export const BACK_TO_BACK_DIVISOR = 2;

export const ACTIONS = {
  LEFT: 0,
  RIGHT: 1,
  ROTATE_CW: 2,
  ROTATE_CCW: 3,
  SOFT_DROP: 4,
  HARD_DROP: 5,
  HOLD: 6,
};

// Bounds on the replay itself, so a crafted log cannot make the verifier
// step a state machine for longer than the run could possibly have lasted.
export const MAX_EVENTS_PER_TICK = 8;
export const MAX_EVENTS = 20000;

/**
 * The seven pieces, as rotation states.
 *
 * Each entry is four [x, y] cells per rotation, written out rather than
 * derived: a rotation routine that computes kicks from a matrix is where
 * two implementations drift, and there are only 28 states.
 */
export const PIECES = {
  I: [
    [[0, 1], [1, 1], [2, 1], [3, 1]],
    [[2, 0], [2, 1], [2, 2], [2, 3]],
    [[0, 2], [1, 2], [2, 2], [3, 2]],
    [[1, 0], [1, 1], [1, 2], [1, 3]],
  ],
  J: [
    [[0, 0], [0, 1], [1, 1], [2, 1]],
    [[1, 0], [2, 0], [1, 1], [1, 2]],
    [[0, 1], [1, 1], [2, 1], [2, 2]],
    [[1, 0], [1, 1], [0, 2], [1, 2]],
  ],
  L: [
    [[2, 0], [0, 1], [1, 1], [2, 1]],
    [[1, 0], [1, 1], [1, 2], [2, 2]],
    [[0, 1], [1, 1], [2, 1], [0, 2]],
    [[0, 0], [1, 0], [1, 1], [1, 2]],
  ],
  O: [
    [[1, 0], [2, 0], [1, 1], [2, 1]],
    [[1, 0], [2, 0], [1, 1], [2, 1]],
    [[1, 0], [2, 0], [1, 1], [2, 1]],
    [[1, 0], [2, 0], [1, 1], [2, 1]],
  ],
  S: [
    [[1, 0], [2, 0], [0, 1], [1, 1]],
    [[1, 0], [1, 1], [2, 1], [2, 2]],
    [[1, 1], [2, 1], [0, 2], [1, 2]],
    [[0, 0], [0, 1], [1, 1], [1, 2]],
  ],
  T: [
    [[1, 0], [0, 1], [1, 1], [2, 1]],
    [[1, 0], [1, 1], [2, 1], [1, 2]],
    [[0, 1], [1, 1], [2, 1], [1, 2]],
    [[1, 0], [0, 1], [1, 1], [1, 2]],
  ],
  Z: [
    [[0, 0], [1, 0], [1, 1], [2, 1]],
    [[2, 0], [1, 1], [2, 1], [1, 2]],
    [[0, 1], [1, 1], [1, 2], [2, 2]],
    [[1, 0], [0, 1], [1, 1], [0, 2]],
  ],
};

export const PIECE_NAMES = ['I', 'J', 'L', 'O', 'S', 'T', 'Z'];

/**
 * A 32-bit integer hash, used as the seeded generator.
 *
 * Integer ops only, and every one masked back to 32 bits with >>> 0:
 * JavaScript numbers are doubles, so an unmasked multiply silently leaves
 * the exact-integer range and two engines can disagree about the low bits.
 * This is the concrete form of the integers-only rule.
 */
export function hash32(a, b) {
  let x = (a ^ Math.imul(b + 0x9e3779b9, 0x85ebca6b)) >>> 0;
  x = Math.imul(x ^ (x >>> 16), 0x7feb352d) >>> 0;
  x = Math.imul(x ^ (x >>> 15), 0x846ca68b) >>> 0;
  return (x ^ (x >>> 16)) >>> 0;
}

/**
 * The nth bag of seven, shuffled by the seed.
 *
 * Addressable (R1.3): bag n depends on the seed and n, not on bag n-1, so
 * the verifier can evaluate any piece directly. A stream would force it to
 * re-shuffle from the beginning to answer "what was piece 200".
 *
 * Fisher-Yates driven by hash32, which is deterministic given (seed, n).
 */
export function bagAt(seed, n) {
  const bag = PIECE_NAMES.slice();
  for (let i = bag.length - 1; i > 0; i--) {
    // one draw per swap, distinct per (seed, bag, position)
    const j = hash32(seed, n * 16 + i) % (i + 1);
    const t = bag[i];
    bag[i] = bag[j];
    bag[j] = t;
  }
  return bag;
}

/** The piece at index i of the run, straight from its bag. */
export function pieceAt(seed, i) {
  return bagAt(seed, Math.floor(i / 7))[i % 7];
}

/**
 * Ticks between gravity steps at a given level.
 *
 * A curve steep enough that everyone tops out: TGM's lesson is that a
 * speed that eventually exceeds reaction is what bounds a run and keeps
 * the board a contest of skill rather than of stamina. At level 15 and
 * above gravity is one row per tick, which no one sustains.
 */
export function gravityInterval(level) {
  if (level >= 15) return 1;
  const table = [48, 43, 38, 33, 28, 23, 18, 13, 8, 6, 5, 5, 4, 4, 3];
  return table[level];
}

export function levelFor(lines) {
  return Math.floor(lines / 10);
}

function emptyBoard() {
  // a flat array of TOTAL_HEIGHT*WIDTH cells: 0 empty, or the piece letter
  return new Array(TOTAL_HEIGHT * WIDTH).fill(0);
}

export function createState(seed) {
  return {
    seed: seed >>> 0,
    board: emptyBoard(),
    tick: 0,
    index: 0,
    piece: null,
    rotation: 0,
    x: 0,
    y: 0,
    hold: null,
    holdUsed: false,
    score: 0,
    lines: 0,
    level: 0,
    gravityCounter: 0,
    backToBack: false,
    over: false,
  };
}

function cellsOf(piece, rotation, x, y) {
  const out = [];
  for (const [cx, cy] of PIECES[piece][rotation & 3]) {
    out.push([x + cx, y + cy]);
  }
  return out;
}

export function collides(state, piece, rotation, x, y) {
  for (const [cx, cy] of cellsOf(piece, rotation, x, y)) {
    if (cx < 0 || cx >= WIDTH) return true;
    if (cy >= TOTAL_HEIGHT) return true;
    if (cy < 0) continue;
    if (state.board[cy * WIDTH + cx] !== 0) return true;
  }
  return false;
}

export function spawn(state) {
  if (state.index >= MAX_PIECES) {
    state.over = true;
    return state;
  }
  state.piece = pieceAt(state.seed, state.index);
  state.index += 1;
  state.rotation = 0;
  state.x = 3;
  state.y = 0;
  state.holdUsed = false;
  state.gravityCounter = 0;
  // a spawn that cannot be placed is the top-out
  if (collides(state, state.piece, 0, state.x, state.y)) state.over = true;
  return state;
}

/**
 * Wall kicks.
 *
 * The Guideline's SRS offsets, written out rather than computed. A player
 * whose muscle memory expects a kick to work will not tolerate it silently
 * failing, and a rotation routine is exactly the kind of thing two
 * implementations get subtly different.
 */
const KICKS = [
  [0, 0],
  [-1, 0],
  [1, 0],
  [0, -1],
  [-1, -1],
  [1, -1],
  [0, -2],
];

export function rotate(state, direction) {
  if (!state.piece) return state;
  const next = (state.rotation + (direction > 0 ? 1 : 3)) & 3;
  for (const [dx, dy] of KICKS) {
    if (!collides(state, state.piece, next, state.x + dx, state.y + dy)) {
      state.rotation = next;
      state.x += dx;
      state.y += dy;
      return state;
    }
  }
  return state;
}

export function move(state, dx) {
  if (!state.piece) return state;
  if (!collides(state, state.piece, state.rotation, state.x + dx, state.y)) {
    state.x += dx;
  }
  return state;
}

function clearLines(state) {
  let cleared = 0;
  for (let row = TOTAL_HEIGHT - 1; row >= 0; row--) {
    let full = true;
    for (let col = 0; col < WIDTH; col++) {
      if (state.board[row * WIDTH + col] === 0) {
        full = false;
        break;
      }
    }
    if (!full) continue;
    cleared += 1;
    // shift everything above down one, and clear the top row
    for (let r = row; r > 0; r--) {
      for (let c = 0; c < WIDTH; c++) {
        state.board[r * WIDTH + c] = state.board[(r - 1) * WIDTH + c];
      }
    }
    for (let c = 0; c < WIDTH; c++) state.board[c] = 0;
    row += 1; // the shifted row has to be examined too
  }
  return cleared;
}

export function lockPiece(state) {
  for (const [cx, cy] of cellsOf(state.piece, state.rotation, state.x, state.y)) {
    if (cy >= 0 && cy < TOTAL_HEIGHT && cx >= 0 && cx < WIDTH) {
      state.board[cy * WIDTH + cx] = state.piece;
    }
  }

  const cleared = clearLines(state);
  if (cleared > 0) {
    let points = LINE_SCORES[cleared] * (state.level + 1);
    // back-to-back, integer arithmetic: x3/2 rather than x1.5, because a
    // float multiply is where two engines are free to disagree
    if (cleared === 4 && state.backToBack) {
      points = Math.floor((points * BACK_TO_BACK_MULTIPLIER) / BACK_TO_BACK_DIVISOR);
    }
    state.score += points;
    state.lines += cleared;
    state.level = levelFor(state.lines);
    state.backToBack = cleared === 4;
  }

  spawn(state);
  return state;
}

export function applyAction(state, action) {
  if (state.over || !state.piece) return state;
  switch (action) {
    case ACTIONS.LEFT:
      return move(state, -1);
    case ACTIONS.RIGHT:
      return move(state, 1);
    case ACTIONS.ROTATE_CW:
      return rotate(state, 1);
    case ACTIONS.ROTATE_CCW:
      return rotate(state, -1);
    case ACTIONS.SOFT_DROP:
      if (!collides(state, state.piece, state.rotation, state.x, state.y + 1)) {
        state.y += 1;
        state.score += SOFT_DROP_POINTS;
        state.gravityCounter = 0;
      }
      return state;
    case ACTIONS.HARD_DROP: {
      let dropped = 0;
      while (!collides(state, state.piece, state.rotation, state.x, state.y + 1)) {
        state.y += 1;
        dropped += 1;
      }
      state.score += dropped * HARD_DROP_POINTS;
      return lockPiece(state);
    }
    case ACTIONS.HOLD: {
      // one swap per piece, as the Guideline has it: unlimited swapping
      // would let a player stall indefinitely
      if (state.holdUsed) return state;
      const held = state.hold;
      state.hold = state.piece;
      state.holdUsed = true;
      if (held === null) {
        spawn(state);
      } else {
        state.piece = held;
        state.rotation = 0;
        state.x = 3;
        state.y = 0;
        if (collides(state, state.piece, 0, state.x, state.y)) state.over = true;
      }
      return state;
    }
    default:
      return state;
  }
}

/** One simulation step: gravity, and a lock when the piece has landed. */
export function stepTick(state) {
  if (state.over) return state;
  if (!state.piece) spawn(state);
  if (state.over) return state;

  state.gravityCounter += 1;
  if (state.gravityCounter >= gravityInterval(state.level)) {
    state.gravityCounter = 0;
    if (!collides(state, state.piece, state.rotation, state.x, state.y + 1)) {
      state.y += 1;
    } else {
      lockPiece(state);
    }
  }
  state.tick += 1;
  return state;
}

/**
 * Replay a run from its events and return the state it ends in.
 *
 * Events are [action, tick] edges, not per-tick state: a two-minute run of
 * continuous movement costs a handful of numbers rather than fourteen
 * thousand. The caller reads .score off the result - the number the client
 * reported is never trusted (R3.2).
 *
 * Throws on a malformed log rather than scoring it, because a log the
 * server half-accepts is worse than one it refuses outright.
 */
export function replay(seed, events) {
  if (!Array.isArray(events)) throw new Error('events must be an array');
  if (events.length > MAX_EVENTS) throw new Error('too many events');

  const state = createState(seed);
  spawn(state);

  let previousTick = 0;
  let sameTick = 0;

  for (const event of events) {
    if (!Array.isArray(event) || event.length !== 2) {
      throw new Error('each event is [action, tick]');
    }
    const [action, tick] = event;
    if (!Number.isInteger(action) || !Number.isInteger(tick)) {
      throw new Error('action and tick must be integers');
    }
    if (tick < previousTick) throw new Error('ticks must not go backwards');
    if (action < 0 || action > ACTIONS.HOLD) throw new Error('unknown action');

    if (tick === previousTick) {
      sameTick += 1;
      // a human cannot press eight keys in one 60th of a second, and
      // without this a crafted log could pack every event into tick 0
      if (sameTick > MAX_EVENTS_PER_TICK) throw new Error('too many events in one tick');
    } else {
      sameTick = 1;
    }

    while (state.tick < tick && !state.over) stepTick(state);
    if (state.over) break;

    applyAction(state, action);
    previousTick = tick;
  }

  // the run continues to its end after the last input: a player who stops
  // pressing keys still tops out, and the score includes what gravity did
  let guard = 0;
  while (!state.over && guard < MAX_PIECES * 60 * 60) {
    stepTick(state);
    guard += 1;
  }

  return state;
}

/**
 * The UTC day a board belongs to.
 *
 * Here rather than beside the leaderboard because the page derives it too
 * when it is offline, and a second hand-written copy of a derivation is
 * the drift this whole design exists to prevent - the same reason the
 * simulation is not reimplemented per side.
 *
 * UTC rather than the player's zone: a board that rolls over at a
 * different moment per player is not one board.
 */
export function dayOf(now) {
  return new Date(now).toISOString().slice(0, 10);
}

/**
 * The seed for a game on a day.
 *
 * Derived rather than stored: every player gets the same board on the same
 * day without a write, and the verifier recomputes it from the run's own
 * day rather than trusting the submission.
 */
export function seedFor(game, day) {
  let h = 2166136261 >>> 0;
  for (const ch of `${game}:${day}`) {
    h = Math.imul(h ^ ch.charCodeAt(0), 16777619) >>> 0;
  }
  return h >>> 0;
}

/**
 * Whether an event log is shaped like something a player could produce.
 *
 * Cheap checks only: this runs in the fetch handler inside its 10ms, to
 * refuse a crafted log before a Durable Object is woken to replay it.
 * Here rather than in scores.js because the bounds are the simulation's -
 * MAX_EVENTS_PER_TICK is a fact about how fast a piece can be moved.
 */
export function validateEvents(events) {
  if (!Array.isArray(events)) return 'events must be an array';
  if (events.length > MAX_EVENTS) return 'too many events';
  let previous = -1;
  let perTick = 0;
  for (const event of events) {
    if (!Array.isArray(event) || event.length < 2) return 'each event is [action, tick]';
    const [action, tick] = event;
    if (!Number.isInteger(action) || !Number.isInteger(tick)) {
      return 'action and tick must be integers';
    }
    if (tick < previous) return 'ticks must not go backwards';
    perTick = tick === previous ? perTick + 1 : 1;
    if (perTick > MAX_EVENTS_PER_TICK) return 'too many events in one tick';
    previous = tick;
  }
  return null;
}
