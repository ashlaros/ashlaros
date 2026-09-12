/**
 * The front end: a renderer, a keyboard reader, and a tick loop.
 *
 * Everything that decides a score lives in logic.js, which the verifier
 * imports unchanged. Nothing in this file may affect the simulation - it
 * reads state and draws it, and it turns keystrokes into [action, tick]
 * pairs. If a rule ever needs to live here, it belongs in logic.js
 * instead.
 *
 * The event log this builds IS the submission: the server replays it and
 * discards whatever score was shown on screen.
 */
import {
  ACTIONS,
  HEIGHT,
  PIECES,
  SPAWN_ROWS,
  TICKS_PER_SECOND,
  WIDTH,
  createState,
  applyAction,
  pieceAt,
  spawn,
  stepTick,
} from './logic.js';

const COLOURS = {
  // The mark's stone, not seven arcade colours: the favicon is three
  // courses of dressed ashlar, and a rainbow would look like a different
  // project. Two tones plus the accent is what the palette has.
  I: '#eeeeee',
  J: '#c9ccd1',
  L: '#eeeeee',
  O: '#c9ccd1',
  S: '#eeeeee',
  T: '#8a8f98',
  Z: '#c9ccd1',
};

const CELL = 30;
const board = document.getElementById('board');
const ctx = board.getContext('2d');
const nextCanvas = document.getElementById('next');
const nextCtx = nextCanvas.getContext('2d');
const scoreEl = document.getElementById('score');
const statusEl = document.getElementById('status');
const tableEl = document.getElementById('board-table');
const playerEl = document.getElementById('player');
const submitEl = document.getElementById('submit');
const noteEl = document.getElementById('submit-note');

let state = null;
let events = [];
let seed = null;
let day = null;
let running = false;
let accumulator = 0;
let lastFrame = 0;

function drawCell(context, x, y, colour) {
  context.fillStyle = colour;
  // a one-pixel gap, so the courses read as laid stone rather than a
  // solid mass - the joints are the mark
  context.fillRect(x * CELL + 1, y * CELL + 1, CELL - 2, CELL - 2);
}

function draw() {
  ctx.fillStyle = '#141a1b';
  ctx.fillRect(0, 0, board.width, board.height);
  if (!state) return;

  for (let row = SPAWN_ROWS; row < SPAWN_ROWS + HEIGHT; row++) {
    for (let col = 0; col < WIDTH; col++) {
      const cell = state.board[row * WIDTH + col];
      if (cell !== 0) drawCell(ctx, col, row - SPAWN_ROWS, COLOURS[cell] ?? '#eee');
    }
  }

  if (state.piece && !state.over) {
    const shape = state.rotation & 3;
    for (const [cx, cy] of piecesCells(state.piece, shape)) {
      const x = state.x + cx;
      const y = state.y + cy - SPAWN_ROWS;
      if (y >= 0) drawCell(ctx, x, y, COLOURS[state.piece] ?? '#eee');
    }
  }

  scoreEl.textContent = state.score.toLocaleString('en-US');
  drawNext();
}

// the shapes come from logic.js, so this file holds no piece data of its
// own - a second table here is a second implementation waiting to happen
function piecesCells(piece, rotation) {
  return PIECES[piece][rotation];
}

function drawNext() {
  nextCtx.fillStyle = '#141a1b';
  nextCtx.fillRect(0, 0, nextCanvas.width, nextCanvas.height);
  if (!state || state.over) return;
  const piece = pieceAt(state.seed, state.index);
  nextCtx.save();
  nextCtx.scale(0.66, 0.66);
  for (const [cx, cy] of PIECES[piece][0]) {
    nextCtx.fillStyle = COLOURS[piece] ?? '#eee';
    nextCtx.fillRect(cx * CELL + 1, cy * CELL + 1, CELL - 2, CELL - 2);
  }
  nextCtx.restore();
}

/**
 * One action, logged and applied.
 *
 * R3.5: only accepted input is logged. The log is evidence, not a debug
 * trace - an entry the server refuses costs the player the whole run, so
 * nothing goes in that the simulation did not take.
 */
function press(action) {
  if (!state || state.over) return;
  events.push([action, state.tick]);
  applyAction(state, action);
  draw();
}

const KEYS = {
  ArrowLeft: ACTIONS.LEFT,
  ArrowRight: ACTIONS.RIGHT,
  ArrowUp: ACTIONS.ROTATE_CW,
  ArrowDown: ACTIONS.SOFT_DROP,
  ' ': ACTIONS.HARD_DROP,
  Shift: ACTIONS.HOLD,
  z: ACTIONS.ROTATE_CCW,
  x: ACTIONS.ROTATE_CW,
};

window.addEventListener('keydown', (event) => {
  if (!running) {
    start();
    return;
  }
  const action = KEYS[event.key];
  if (action === undefined) return;
  event.preventDefault();
  press(action);
});

/**
 * The tick loop.
 *
 * requestAnimationFrame drives wall time; the simulation advances in whole
 * ticks from an accumulator, so a dropped frame or a backgrounded tab
 * changes how smoothly it draws and not what happens. The tick index is
 * the clock the server shares.
 */
function frame(now) {
  if (!running) return;
  const elapsed = Math.min(now - lastFrame, 250);
  lastFrame = now;
  accumulator += elapsed;

  const step = 1000 / TICKS_PER_SECOND;
  while (accumulator >= step) {
    accumulator -= step;
    stepTick(state);
    if (state.over) {
      finish();
      return;
    }
  }
  draw();
  requestAnimationFrame(frame);
}

function start() {
  if (seed === null) return;
  state = createState(seed);
  spawn(state);
  events = [];
  running = true;
  accumulator = 0;
  lastFrame = performance.now();
  statusEl.textContent = 'Playing.';
  submitEl.disabled = true;
  requestAnimationFrame(frame);
}

function finish() {
  running = false;
  draw();
  statusEl.textContent = `Topped out at ${state.score.toLocaleString('en-US')}.`;
  submitEl.disabled = false;
}

submitEl.addEventListener('click', async () => {
  submitEl.disabled = true;
  noteEl.textContent = 'Verifying…';
  try {
    const response = await fetch('/game/score', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      // no score field: the server replays the events and would ignore it
      body: JSON.stringify({ game: 'courses', player: playerEl.value, events }),
    });
    const result = await response.json();
    if (!response.ok) {
      noteEl.textContent = result.error ?? 'The run was not accepted.';
      return;
    }
    noteEl.textContent = result.recorded
      ? `Recorded ${result.score.toLocaleString('en-US')}.`
      : (result.reason ?? 'Already submitted a run for this seed.');
    await loadBoard();
  } catch (error) {
    noteEl.textContent = `Could not submit: ${error.message}`;
  }
});

async function loadBoard() {
  try {
    const response = await fetch('/game/board?game=courses');
    const data = await response.json();
    tableEl.innerHTML = (data.scores ?? [])
      .map(
        (row, i) =>
          `<tr><td>${i + 1}</td><td>${escape(row.player)}</td>` +
          `<td>${Number(row.score).toLocaleString('en-US')}</td></tr>`,
      )
      .join('');
    if (!data.scores?.length) tableEl.innerHTML = '<tr><td>No runs yet today.</td></tr>';
  } catch {
    tableEl.innerHTML = '<tr><td>The board is unreachable.</td></tr>';
  }
}

const escape = (s) => String(s).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

/**
 * Offline is the default: without a seed from the server the game still
 * plays, on a seed derived from today's date the same way the server
 * derives it. Only the leaderboard needs the network.
 */
async function init() {
  try {
    const response = await fetch('/game/seed?game=courses');
    const data = await response.json();
    seed = data.seed;
    day = data.day;
    statusEl.textContent = `Today's seed. Press any key to start.`;
    await loadBoard();
  } catch {
    // the same derivation the server uses, so an offline run is on the
    // same board as everyone else's that day - it simply cannot be
    // submitted until the network is back
    const today = new Date().toISOString().slice(0, 10);
    seed = localSeed(`courses:${today}`);
    day = today;
    statusEl.textContent = 'Offline. Press any key to start.';
    tableEl.innerHTML = '<tr><td>The board is unreachable.</td></tr>';
    submitEl.disabled = true;
  }
  draw();
}

function localSeed(text) {
  let h = 2166136261 >>> 0;
  for (const ch of text) h = Math.imul(h ^ ch.charCodeAt(0), 16777619) >>> 0;
  return h >>> 0;
}

init();
