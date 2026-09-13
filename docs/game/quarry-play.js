/**
 * Quarry's front end: a renderer, a keyboard reader, and a tick loop.
 *
 * Everything that decides a score lives in quarry.js, which the verifier
 * imports unchanged. Nothing in this file may affect the simulation - it
 * reads state and draws it, and it turns keystrokes into [action, tick,
 * value] triples.
 *
 * The log records the paddle's TARGET rather than its position, and only
 * when the target has moved far enough to matter. That is what keeps a
 * two-minute run inside a few hundred events instead of seven thousand.
 */
import {
  ACTIONS,
  BALL_R,
  BRICK_COLS,
  BRICK_H,
  BRICK_ROWS,
  BRICK_TOP,
  BRICK_W,
  CAPSULES,
  EMPTY,
  FIELD_H,
  FIELD_W,
  PADDLE_H,
  PADDLE_Y,
  SOLID,
  SUB,
  TICKS_PER_SECOND,
  applyAction,
  createState,
  stepTick,
} from './quarry.js';
import { dayOf, seedFor } from './logic.js';

const GAME = 'quarry';

const COLOURS = {
  // the mark's stone, as in Courses: two tones plus the accent
  3: '#eeeeee',
  2: '#c9ccd1',
  1: '#8a8f98',
  solid: '#3a4043',
  ball: '#eeeeee',
  paddle: '#c9ccd1',
  capsule: '#8a8f98',
};

const canvas = document.getElementById('field');
const ctx = canvas.getContext('2d');
const scoreEl = document.getElementById('score');
const livesEl = document.getElementById('lives');
const statusEl = document.getElementById('status');
const tableEl = document.getElementById('board-table');
const entryEl = document.getElementById('entry');
const initialEls = [...document.querySelectorAll('#initials button')];
const submitEl = document.getElementById('submit');
const noteEl = document.getElementById('submit-note');

// the canvas is in pixels and the simulation is in sub-pixels; one place
// converts, so nothing else has to think about it
const SCALE = canvas.width / FIELD_W;
const s = (n) => n * SCALE;

let state = null;
let events = [];
let seed = null;
let day = null;
let running = false;
let submittable = false;
let lastBoard = [];
const BOARD_SIZE = 20;
let accumulator = 0;
let lastFrame = 0;
let heldKeys = { left: false, right: false };
let lastTarget = 0;
// how far the aim must move before it is worth an event
const SAMPLE = (FIELD_W / 40) | 0;

function draw() {
  ctx.fillStyle = '#0d1112';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  if (!state) return;

  for (let row = 0; row < BRICK_ROWS; row++) {
    for (let col = 0; col < BRICK_COLS; col++) {
      const tier = state.bricks[row * BRICK_COLS + col];
      if (tier === EMPTY) continue;
      ctx.fillStyle = tier === SOLID ? COLOURS.solid : COLOURS[tier] ?? COLOURS[1];
      // a one-pixel gap, so the wall reads as laid stone - the joints are
      // the mark, the same as the falling blocks in Courses
      ctx.fillRect(
        s(col * BRICK_W) + 1,
        s(BRICK_TOP + row * BRICK_H) + 1,
        s(BRICK_W) - 2,
        s(BRICK_H) - 2,
      );
    }
  }

  ctx.fillStyle = COLOURS.paddle;
  ctx.fillRect(s(state.paddleX), s(PADDLE_Y), s(state.paddleW), s(PADDLE_H));

  ctx.fillStyle = COLOURS.ball;
  for (const ball of state.balls) {
    ctx.beginPath();
    ctx.arc(s(ball.x), s(ball.y), s(BALL_R), 0, Math.PI * 2);
    ctx.fill();
  }
  if (state.held) {
    const x = state.paddleX + (state.paddleW >> 1);
    ctx.beginPath();
    ctx.arc(s(x), s(PADDLE_Y - BALL_R), s(BALL_R), 0, Math.PI * 2);
    ctx.fill();
  }

  ctx.fillStyle = COLOURS.capsule;
  for (const capsule of state.capsules) {
    ctx.fillRect(s(capsule.x) - 8, s(capsule.y) - 3, 16, 6);
    ctx.fillStyle = '#0d1112';
    ctx.fillText(capsuleLetter(capsule.kind), s(capsule.x) - 3, s(capsule.y) + 3);
    ctx.fillStyle = COLOURS.capsule;
  }

  scoreEl.textContent = state.score.toLocaleString('en-US');
  livesEl.textContent = String(Math.max(0, state.lives));
}

function capsuleLetter(kind) {
  switch (kind) {
    case CAPSULES.WIDEN:
      return 'W';
    case CAPSULES.MULTI:
      return 'M';
    case CAPSULES.SLOW:
      return 'S';
    default:
      return 'C';
  }
}

function emit(action, value) {
  events.push(value === undefined ? [action, state.tick] : [action, state.tick, value]);
  applyAction(state, action, value);
}

function steer() {
  if (!state || state.over) return;
  let target = state.target;
  const step = FIELD_W / 24;
  if (heldKeys.left) target -= step;
  if (heldKeys.right) target += step;
  target = Math.max(0, Math.min(FIELD_W - state.paddleW, Math.round(target)));
  // only when it has moved far enough to change what the paddle does:
  // logging every tick is 60 events/second and tells the verifier nothing
  // it could not derive
  if (Math.abs(target - lastTarget) >= SAMPLE) {
    emit(ACTIONS.TARGET, target);
    lastTarget = target;
  }
}

function frame(now) {
  if (!running) return;
  const elapsed = Math.min(now - lastFrame, 250);
  lastFrame = now;
  accumulator += elapsed;

  const step = 1000 / TICKS_PER_SECOND;
  while (accumulator >= step) {
    accumulator -= step;
    steer();
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
  events = [];
  lastTarget = state.target;
  running = true;
  accumulator = 0;
  lastFrame = performance.now();
  statusEl.textContent = 'Playing.';
  entryEl.hidden = true;
  noteEl.textContent = '';
  emit(ACTIONS.LAUNCH);
  requestAnimationFrame(frame);
}

const ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
let slot = 0;
const initials = ['A', 'A', 'A'];

function drawInitials() {
  initialEls.forEach((el, i) => {
    el.textContent = initials[i];
    el.setAttribute('aria-current', String(i === slot));
  });
}

function cycle(step) {
  const at = ALPHABET.indexOf(initials[slot]);
  initials[slot] = ALPHABET[(at + step + ALPHABET.length) % ALPHABET.length];
  drawInitials();
}

initialEls.forEach((el, i) => {
  el.addEventListener('click', () => {
    slot = i;
    cycle(1);
  });
});

function placed(score) {
  if (!lastBoard.length || lastBoard.length < BOARD_SIZE) return true;
  return score > lastBoard[lastBoard.length - 1].score;
}

function finish() {
  running = false;
  draw();
  statusEl.textContent = `Out of lives at ${state.score.toLocaleString('en-US')}.`;
  if (submittable && placed(state.score)) {
    slot = 0;
    entryEl.hidden = false;
    drawInitials();
  } else {
    noteEl.textContent = submittable
      ? 'That did not place. Try again tomorrow - one run per seed.'
      : 'Offline: this run cannot be submitted.';
  }
}

window.addEventListener('keydown', (event) => {
  if (!entryEl.hidden) {
    const handled = {
      ArrowLeft: () => { slot = (slot + 2) % 3; drawInitials(); },
      ArrowRight: () => { slot = (slot + 1) % 3; drawInitials(); },
      ArrowUp: () => cycle(1),
      ArrowDown: () => cycle(-1),
      Enter: () => submitEl.click(),
    }[event.key];
    if (handled) {
      event.preventDefault();
      handled();
    }
    return;
  }
  if (!running) {
    start();
    return;
  }
  if (event.key === 'ArrowLeft') heldKeys.left = true;
  else if (event.key === 'ArrowRight') heldKeys.right = true;
  else if (event.key === ' ') emit(ACTIONS.LAUNCH);
  else return;
  event.preventDefault();
});

window.addEventListener('keyup', (event) => {
  if (event.key === 'ArrowLeft') heldKeys.left = false;
  else if (event.key === 'ArrowRight') heldKeys.right = false;
});

submitEl.addEventListener('click', async () => {
  submitEl.disabled = true;
  entryEl.hidden = true;
  noteEl.textContent = 'Verifying…';
  try {
    const response = await fetch('/game/score', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      // no score field: the server replays the events and would ignore it
      body: JSON.stringify({ game: GAME, day, player: initials.join(''), events }),
    });
    const result = await response.json();
    submitEl.disabled = false;
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

const escape = (text) => String(text).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

async function loadBoard() {
  try {
    const response = await fetch(`/game/board?game=${GAME}`);
    const data = await response.json();
    lastBoard = data.scores ?? [];
    tableEl.innerHTML = lastBoard
      .map(
        (row, i) =>
          `<tr><td>${i + 1}</td><td>${escape(row.player)}</td>` +
          `<td>${Number(row.score).toLocaleString('en-US')}</td></tr>`,
      )
      .join('');
    if (!lastBoard.length) tableEl.innerHTML = '<tr><td>No runs yet today.</td></tr>';
  } catch {
    tableEl.innerHTML = '<tr><td>The board is unreachable.</td></tr>';
  }
}

/**
 * Offline is the default: without a seed from the server the game still
 * plays, on a seed derived by the same function the server uses. Only the
 * leaderboard needs the network.
 */
async function init() {
  try {
    const response = await fetch(`/game/seed?game=${GAME}`);
    const data = await response.json();
    seed = data.seed;
    day = data.day;
    submittable = true;
    statusEl.textContent = `Today's wall. Press any key to start.`;
    await loadBoard();
  } catch {
    day = dayOf(Date.now());
    seed = seedFor(GAME, day);
    statusEl.textContent = 'Offline. Press any key to start.';
    tableEl.innerHTML = '<tr><td>The board is unreachable.</td></tr>';
  }
  draw();
}

init();
