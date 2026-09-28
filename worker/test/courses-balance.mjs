/**
 * Courses' balance harness.
 *
 * A measurement, like quarry-balance.mjs: scripted players at several
 * skill levels on several seeds, reporting the score spread, how far the
 * speed curve got, and how runs end. Reading gravityInterval() says what
 * the curve is; only playing it says whether anyone reaches the steep
 * end, and whether the piece cap or the stack is what finishes a run.
 *
 * A band is a placement search made worse in the two ways people are
 * worse: `noise` blurs its judgement of a placement, and `think` / `gap`
 * are how long it takes to start moving and between inputs. The second is
 * what makes gravity matter - a player who hard-drops instantly never
 * feels the speed, and nobody plays like that at level 12.
 *
 *   node test/courses-balance.mjs [runs-per-band]
 */

import {
  ACTIONS,
  MAX_PIECES,
  TICKS_PER_SECOND,
  TOTAL_HEIGHT,
  WIDTH,
  applyAction,
  createState,
  gravityInterval,
  seedFor,
  spawn,
  stepTick,
} from '../src/game/logic.js';

const BANDS = [
  { name: 'novice', noise: 5, think: 40, gap: 8 },
  { name: 'casual', noise: 2.5, think: 24, gap: 5 },
  { name: 'decent', noise: 1, think: 12, gap: 3 },
  { name: 'expert', noise: 0, think: 6, gap: 2 },
];

/** Aggregate height, buried holes and column-to-column roughness. */
function shapeOf(board) {
  const columns = [];
  let holes = 0;
  for (let col = 0; col < WIDTH; col++) {
    let top = -1;
    for (let row = 0; row < TOTAL_HEIGHT; row++) {
      if (board[row * WIDTH + col]) {
        if (top < 0) top = row;
      } else if (top >= 0) {
        holes += 1;
      }
    }
    columns.push(top < 0 ? 0 : TOTAL_HEIGHT - top);
  }
  let bumpiness = 0;
  for (let col = 1; col < WIDTH; col++) bumpiness += Math.abs(columns[col] - columns[col - 1]);
  return { height: columns.reduce((a, b) => a + b, 0), holes, bumpiness };
}

function plan(state, band, wobble) {
  let best = null;
  for (let rotation = 0; rotation < 4; rotation++) {
    for (let dx = -6; dx <= 6; dx++) {
      const trial = { ...state, board: state.board.slice() };
      for (let i = 0; i < rotation; i++) applyAction(trial, ACTIONS.ROTATE_CW);
      for (let i = 0; i < Math.abs(dx); i++) {
        applyAction(trial, dx < 0 ? ACTIONS.LEFT : ACTIONS.RIGHT);
      }
      const before = trial.lines;
      applyAction(trial, ACTIONS.HARD_DROP);
      if (trial.over) continue;
      const { height, holes, bumpiness } = shapeOf(trial.board);
      const value =
        (trial.lines - before) * 3.5 -
        height * 0.51 -
        holes * 3.6 -
        bumpiness * 0.18 +
        wobble(band.noise);
      if (!best || value > best.value) best = { rotation, dx, value };
    }
  }
  if (!best) return [ACTIONS.HARD_DROP];
  const actions = [];
  for (let i = 0; i < best.rotation; i++) actions.push(ACTIONS.ROTATE_CW);
  for (let i = 0; i < Math.abs(best.dx); i++) actions.push(best.dx < 0 ? ACTIONS.LEFT : ACTIONS.RIGHT);
  actions.push(ACTIONS.HARD_DROP);
  return actions;
}

function play(seed, band) {
  const state = createState(seed);
  spawn(state);
  let noise = seed >>> 0 || 1;
  const wobble = (range) => {
    if (range === 0) return 0;
    noise = (Math.imul(noise ^ (noise >>> 15), 0x2c1b3c6d) + 1) >>> 0;
    return ((noise / 0x100000000) * 2 - 1) * range;
  };

  let piece = -1;
  let queue = [];
  let next = 0;
  let events = 0;
  // guard against a rule change that stalls a run forever; the replay has
  // the same bound
  while (!state.over && state.tick < MAX_PIECES * 60 * 60) {
    if (state.index !== piece) {
      piece = state.index;
      queue = plan(state, band, wobble);
      next = state.tick + band.think;
    }
    if (queue.length && state.tick >= next) {
      applyAction(state, queue.shift());
      events += 1;
      next = state.tick + band.gap;
      if (state.index !== piece || state.over) continue;
    }
    stepTick(state);
  }
  return {
    score: state.score,
    lines: state.lines,
    level: state.level,
    pieces: state.index,
    ticks: state.tick,
    events,
    ending: state.index >= MAX_PIECES ? 'cap' : 'top',
  };
}

const runs = Number(process.argv[2] ?? 8);
const rows = [];

for (const band of BANDS) {
  const results = [];
  for (let i = 0; i < runs; i++) {
    results.push(play(seedFor('courses', `2026-09-${String(13 + i).padStart(2, '0')}`), band));
  }
  const scores = results.map((r) => r.score).sort((a, b) => a - b);
  const mean = (key) => results.reduce((a, r) => a + r[key], 0) / runs;
  rows.push({
    band: band.name,
    low: scores[0],
    median: scores[scores.length >> 1],
    high: scores[scores.length - 1],
    mean: Math.round(mean('score')),
    lines: Math.round(mean('lines')),
    level: mean('level').toFixed(1),
    top: Math.max(...results.map((r) => r.level)),
    pieces: Math.round(mean('pieces')),
    capped: results.filter((r) => r.ending === 'cap').length,
    secs: (mean('ticks') / TICKS_PER_SECOND).toFixed(0),
  });
}

console.log(`Courses balance, ${runs} seeds per band\n`);
const heads = ['band', 'low', 'median', 'high', 'mean', 'lines', 'level', 'top', 'pieces', 'capped', 'secs'];
console.log(heads.map((h) => h.padStart(8)).join(''));
for (const r of rows) {
  console.log(
    [r.band, r.low, r.median, r.high, r.mean, r.lines, r.level, r.top, r.pieces, `${r.capped}/${runs}`, r.secs]
      .map((c) => String(c).padStart(8))
      .join(''),
  );
}
const novice = rows[0].mean || 1;
console.log(`\nskill cliff (expert / novice): ${(rows[rows.length - 1].mean / novice).toFixed(1)}x`);
console.log(
  `gravity, ticks per row by level: ${Array.from({ length: 16 }, (_, l) => gravityInterval(l)).join(' ')}`,
);
