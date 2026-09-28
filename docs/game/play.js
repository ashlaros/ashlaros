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
  LOCK_DELAY,
  PIECES,
  SPAWN_ROWS,
  TICKS_PER_SECOND,
  TOTAL_HEIGHT,
  WIDTH,
  createState,
  applyAction,
  collides,
  dayOf,
  seedFor,
  pieceAt,
  spawn,
  stepTick,
} from './logic.js';
import { createAudio } from './audio.js';
import { createBoards } from './boards.js';
import { createEffects } from './effects.js';

const GAME_NAME = 'courses';
const audio = createAudio();
const effects = createEffects();

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
// The hold and the next three. One upcoming piece is a surprise and five
// is a spreadsheet; three is what a player can actually plan a well
// around.
const QUEUE = 3;
// How high the stack may come before the run is in trouble. Four rows is
// where the board stops being playable rather than merely uncomfortable.
const DANGER_ROWS = 4;

const board = document.getElementById('board');
const ctx = board.getContext('2d');
const holdCanvas = document.getElementById('hold');
const holdCtx = holdCanvas.getContext('2d');
const nextCanvas = document.getElementById('next');
const nextCtx = nextCanvas.getContext('2d');
const scoreEl = document.getElementById('score');
const levelEl = document.getElementById('level');
const linesEl = document.getElementById('lines');
const statusEl = document.getElementById('status');
const tableEl = document.getElementById('board-table');
const tabsEl = document.getElementById('board-tabs');
const entryEl = document.getElementById('entry');
const initialEls = [...document.querySelectorAll('#initials button')];
const submitEl = document.getElementById('submit');
const noteEl = document.getElementById('submit-note');
const againEl = document.getElementById('again');

let state = null;
let events = [];
let seed = null;
let day = null;
let running = false;
let submittable = false;
let lastBoard = [];
// the board shows twenty, so placing means beating the twentieth
const BOARD_SIZE = 20;
let accumulator = 0;
let lastFrame = 0;
// When the last run ended. A key still held from the run - a soft drop,
// an arrow - arrives as a fresh keydown the instant it ends, and without
// this pause it started the next round before the final score was read.
let finishedAt = 0;
const AGAIN_DELAY_MS = 600;
// The danger cue fires on entering the top band and not on every tick
// spent in it; this is what makes it "entering" rather than "still there".
// It arms again only once a piece has left the band, so one piece cannot
// ask for attention twice.
let dangerArmed = true;

/**
 * A little pitch variation on the cues that fire constantly, so holding
 * down soft drop does not machine-gun one identical sample. Presentation
 * only: two players hear slightly different detune and log the same run.
 */
const detune = () => 0.97 + Math.random() * 0.06;

function drawCell(context, x, y, colour) {
  context.fillStyle = colour;
  // a one-pixel gap, so the courses read as laid stone rather than a
  // solid mass - the joints are the mark
  context.fillRect(x * CELL + 1, y * CELL + 1, CELL - 2, CELL - 2);
}

/**
 * How far the falling piece can go before it lands.
 *
 * collides() is the simulation's own answer to "is this cell taken",
 * called read-only: nothing here writes the board, so the preview cannot
 * change what the run does.
 */
function dropTarget() {
  if (!state || !state.piece) return null;
  let y = state.y;
  while (!collides(state, state.piece, state.rotation, state.x, y + 1)) y += 1;
  return y;
}

function draw() {
  ctx.fillStyle = '#141a1b';
  ctx.fillRect(0, 0, board.width, board.height);
  drawQueue();
  if (!state) return;

  const offset = effects.shakeOffset();
  ctx.save();
  ctx.translate(offset.x, offset.y);

  for (let row = SPAWN_ROWS; row < SPAWN_ROWS + HEIGHT; row++) {
    for (let col = 0; col < WIDTH; col++) {
      const cell = state.board[row * WIDTH + col];
      if (cell !== 0) drawCell(ctx, col, row - SPAWN_ROWS, COLOURS[cell] ?? '#eee');
    }
  }

  if (state.piece && !state.over) {
    const shape = state.rotation & 3;
    const colour = COLOURS[state.piece] ?? '#eee';
    const land = dropTarget();
    // The landing preview, held faint so it reads as a marker and never
    // as a piece that has already come down. Drawn solid at low alpha
    // rather than as an outline: at one pixel an outline disappears
    // against the joints of the stone behind it.
    if (land !== null && land !== state.y) {
      ctx.save();
      ctx.globalAlpha = 0.22;
      for (const [cx, cy] of piecesCells(state.piece, shape)) {
        const y = land + cy - SPAWN_ROWS;
        if (y >= 0) drawCell(ctx, state.x + cx, y, colour);
      }
      ctx.restore();
    }
    // A piece sitting on the stack brightens as its lock approaches, so
    // the half second the rules give the player to nudge it reads as a
    // window closing rather than as the game pausing.
    const heat = LOCK_DELAY > 0 ? (state.lockCounter ?? 0) / LOCK_DELAY : 0;
    for (const [cx, cy] of piecesCells(state.piece, shape)) {
      const x = state.x + cx;
      const y = state.y + cy - SPAWN_ROWS;
      if (y < 0) continue;
      drawCell(ctx, x, y, colour);
      if (heat > 0) {
        ctx.save();
        ctx.globalAlpha = Math.min(0.5, heat * 0.5);
        drawCell(ctx, x, y, '#ffffff');
        ctx.restore();
      }
    }
  }

  ctx.restore();
  effects.draw(ctx);

  scoreEl.textContent = state.score.toLocaleString('en-US');
  levelEl.textContent = String(state.level);
  linesEl.textContent = String(state.lines);
}

// the shapes come from logic.js, so this file holds no piece data of its
// own - a second table here is a second implementation waiting to happen
function piecesCells(piece, rotation) {
  return PIECES[piece][rotation & 3];
}

/**
 * One piece, centred in a box of its own. The hold and every queue slot
 * are this at the same scale, so the four read as one set of previews
 * rather than as four drawings.
 */
function drawPieceBox(context, x, y, w, h, piece) {
  context.fillStyle = '#141a1b';
  context.fillRect(x, y, w, h);
  if (!piece) return;
  const cells = PIECES[piece][0];
  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;
  for (const [cx, cy] of cells) {
    if (cx < minX) minX = cx;
    if (cx > maxX) maxX = cx;
    if (cy < minY) minY = cy;
    if (cy > maxY) maxY = cy;
  }
  const size = CELL * 0.66;
  const ox = x + (w - (maxX - minX + 1) * size) / 2 - minX * size;
  const oy = y + (h - (maxY - minY + 1) * size) / 2 - minY * size;
  context.fillStyle = COLOURS[piece] ?? '#eee';
  for (const [cx, cy] of cells) {
    context.fillRect(ox + cx * size + 1, oy + cy * size + 1, size - 2, size - 2);
  }
}

function drawQueue() {
  // both boxes are cleared whatever the run is doing, so the sidebar is
  // dark before a game starts rather than showing the browser's canvas
  drawPieceBox(
    holdCtx,
    0,
    0,
    holdCanvas.width,
    holdCanvas.height,
    state && !state.over ? state.hold : null,
  );
  const band = nextCanvas.height / QUEUE;
  for (let k = 0; k < QUEUE; k++) {
    drawPieceBox(
      nextCtx,
      0,
      k * band,
      nextCanvas.width,
      band,
      state && !state.over ? pieceAt(state.seed, state.index + k) : null,
    );
  }
}

/**
 * Everything the effects need to know about the piece that is about to
 * act, taken before it does.
 *
 * The lock rewrites the board in place and shifts whatever survives it,
 * so afterwards there is no way to know which rows went or where the
 * piece was - and the debris has to land where the player saw the lines.
 */
function lockSnapshot() {
  return {
    board: state.board.slice(),
    piece: state.piece,
    rotation: state.rotation,
    x: state.x,
    y: state.y,
    landY: dropTarget(),
    lines: state.lines,
    level: state.level,
    score: state.score,
    backToBack: state.backToBack,
  };
}

/** The rows of a board that are completely filled. */
function fullRows(grid) {
  const rows = [];
  for (let row = 0; row < TOTAL_HEIGHT; row++) {
    let full = true;
    for (let col = 0; col < WIDTH; col++) {
      if (grid[row * WIDTH + col] === 0) {
        full = false;
        break;
      }
    }
    if (full) rows.push(row);
  }
  return rows;
}

/**
 * Where the lines were, before they went.
 *
 * The rows are read from the board with the falling piece already laid
 * onto it, which is what the board was the instant before the clear. Once
 * the state reports the lines gone they have been shifted down and there
 * is nothing left to point at.
 */
function clearEffects(before, cleared, delta) {
  // before.board is this file's own copy, so the piece goes onto it
  // rather than onto a second copy of the same thing
  const joined = before.board;
  for (const [cx, cy] of piecesCells(before.piece, before.rotation)) {
    const x = before.x + cx;
    const y = before.y + cy;
    if (x >= 0 && x < WIDTH && y >= 0 && y < TOTAL_HEIGHT) joined[y * WIDTH + x] = before.piece;
  }

  effects.flash(0.2 + cleared * 0.07);
  effects.shake(2 + cleared * 1.5);
  for (const row of fullRows(joined)) {
    const visible = row - SPAWN_ROWS;
    // the two rows of spawn space above the board are never drawn, so
    // debris thrown there would be thrown away
    if (visible < 0 || visible >= HEIGHT) continue;
    for (let col = 0; col < WIDTH; col++) {
      const cell = joined[row * WIDTH + col];
      if (cell === 0) continue;
      effects.burst((col + 0.5) * CELL, (visible + 0.5) * CELL, COLOURS[cell] ?? '#eee', 2);
    }
  }
  effects.popup(`+${delta.toLocaleString('en-US')}`, board.width / 2, board.height * 0.58);
  if (cleared >= 4) {
    effects.popup(
      before.backToBack ? 'BACK-TO-BACK' : 'TETRIS',
      board.width / 2,
      board.height * 0.48,
      '#c9ccd1',
    );
  }
}

/**
 * What the piece left on the way down. The ghost already told the player
 * where it would land; this is how far it fell, which is the part that
 * reads as force.
 */
function hardDropTrail(before) {
  if (!before.piece || before.landY === null || before.landY <= before.y) return;
  for (const [cx, cy] of piecesCells(before.piece, before.rotation)) {
    const x = (before.x + cx) * CELL + 1;
    const y0 = (before.y + cy - SPAWN_ROWS) * CELL;
    const y1 = (before.landY + cy - SPAWN_ROWS) * CELL;
    effects.streak(x, y0, CELL - 2, y1 + CELL - 2 - y0, COLOURS[before.piece] ?? '#eee');
  }
}

/** How high the settled stack reaches, in visible rows from the top. */
function stackTop() {
  for (let row = 0; row < HEIGHT; row++) {
    for (let col = 0; col < WIDTH; col++) {
      if (state.board[(row + SPAWN_ROWS) * WIDTH + col] !== 0) return row;
    }
  }
  return HEIGHT;
}

function checkDanger() {
  const dangerous = stackTop() < DANGER_ROWS;
  if (dangerous && dangerArmed) {
    dangerArmed = false;
    audio.play('warning');
  } else if (!dangerous) {
    dangerArmed = true;
  }
}

/**
 * A piece locked: the clear ladder and where the lines were, or the dull
 * tick of a plain placement.
 */
function afterLock(before) {
  const cleared = state.lines - before.lines;
  const delta = state.score - before.score;
  if (cleared > 0) {
    // one file per rung, never one repitched: resampling shortens a
    // sound, so a four-line clear would answer shorter than a single
    audio.play(`clear-${Math.min(4, cleared)}`);
    clearEffects(before, cleared, delta);
  } else {
    audio.play('lock', 1, detune());
  }
  // A tetris that kept the chain going: the clearest signal in the game
  // that risk is being paid for. Laid over the clear rather than in place
  // of it, so the rung is still heard.
  if (cleared === 4 && before.backToBack) audio.play('backtoback');
  if (state.level > before.level) {
    audio.play('levelup');
    effects.banner(`LEVEL ${state.level}`);
    // The gravity changed under the player and the music says so before
    // the board does. Capped, because past level 12 the loop would be
    // unintelligible rather than tense.
    audio.tempo(1 + Math.min(state.level, 12) * 0.015);
  }
  checkDanger();
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
  const heldBefore = state.hold;
  const lockedBefore = state.index;
  const before = lockSnapshot();
  applyAction(state, action);
  // the input cues, from what the action actually did rather than from
  // the key that was pressed - a rotation the wall refused makes no sound
  if (action === ACTIONS.HARD_DROP) {
    audio.play('drop');
    effects.shake(5);
    hardDropTrail(before);
  } else if (action === ACTIONS.SOFT_DROP && state.y > before.y) {
    audio.play('softdrop', 1, detune());
  } else if (action === ACTIONS.HOLD && state.hold !== heldBefore) {
    audio.play('hold');
  } else if (action === ACTIONS.LEFT || action === ACTIONS.RIGHT) {
    audio.play('move', 1, detune());
  } else if (action === ACTIONS.ROTATE_CW || action === ACTIONS.ROTATE_CCW) {
    audio.play('rotate', 1, detune());
  }
  if (state.index !== lockedBefore) afterLock(before);
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
  // entry owns the keyboard while it is open: otherwise cycling a letter
  // would be read as "press any key to start" and throw the run away
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
  if (event.key === 'm' || event.key === 'M') {
    statusEl.textContent = audio.toggle() ? 'Muted.' : 'Playing.';
    return;
  }
  if (!running) {
    // the first run starts on any key, as the page says; the next one only
    // on a deliberate Enter or R, so the end of a run is never skipped
    const deliberate = !event.repeat && (event.key === 'Enter' || event.key === 'r' || event.key === 'R');
    if (!state || (deliberate && performance.now() - finishedAt > AGAIN_DELAY_MS)) {
      event.preventDefault();
      start();
    }
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
 * the clock the server shares. The effects ride the frame clock and are
 * never fed a tick, so the replay owes them nothing.
 */
function frame(now) {
  if (!running) return;
  const elapsed = Math.min(now - lastFrame, 250);
  lastFrame = now;
  accumulator += elapsed;
  effects.update(elapsed);

  const step = 1000 / TICKS_PER_SECOND;
  while (accumulator >= step) {
    accumulator -= step;
    const lockedBefore = state.index;
    const before = lockSnapshot();
    stepTick(state);
    // gravity locks pieces too, not just a hard drop
    if (state.index !== lockedBefore) afterLock(before);
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
  audio.start();
  audio.music(seed);
  audio.play('start');
  audio.tempo(1);
  dangerArmed = true;
  effects.clear();
  state = createState(seed);
  spawn(state);
  events = [];
  running = true;
  accumulator = 0;
  lastFrame = performance.now();
  statusEl.textContent = 'Playing.';
  entryEl.hidden = true;
  againEl.hidden = true;
  noteEl.textContent = '';
  requestAnimationFrame(frame);
}

/**
 * Initials entry, the arcade way.
 *
 * Shown after the run and only if the score placed, exactly as the
 * original does - it is a reward for the run, not a form to fill in
 * before earning one.
 */
const ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
let slot = 0;
let initials = ['A', 'A', 'A'];

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
  // an empty board places everyone, which is the point of a new day
  if (!lastBoard.length || lastBoard.length < BOARD_SIZE) return true;
  return score > lastBoard[lastBoard.length - 1].score;
}

function finish() {
  running = false;
  finishedAt = performance.now();
  againEl.hidden = false;
  // the run is over, so what was mid-flight is debris frozen in the air
  // rather than anything still happening
  effects.clear();
  draw();
  statusEl.textContent = `Topped out at ${state.score.toLocaleString('en-US')}. R to play again.`;
  audio.stopMusic();
  audio.play('gameover');
  if (submittable && placed(state.score)) {
    // from the left every time: the cursor is not a leftover from
    // whichever key the run happened to end on
    slot = 0;
    entryEl.hidden = false;
    drawInitials();
  } else {
    noteEl.textContent = submittable
      ? 'That did not place. The board keeps one run per player per seed.'
      : 'Offline: this run cannot be submitted.';
  }
}

submitEl.addEventListener('click', async () => {
  submitEl.disabled = true;
  entryEl.hidden = true;
  noteEl.textContent = 'Verifying…';
  try {
    const response = await fetch('/game/score', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      // no score field: the server replays the events and would ignore it
      // day travels with the run: the board it belongs to is the day its
      // seed was issued, not the moment this request arrives
      body: JSON.stringify({ game: 'courses', day, player: initials.join(''), events }),
    });
    const result = await response.json();
    if (!response.ok) {
      noteEl.textContent = result.error ?? 'The run was not accepted.';
      return;
    }
    submitEl.disabled = false;
    noteEl.textContent = result.recorded
      ? `Recorded ${result.score.toLocaleString('en-US')}.`
      : (result.reason ?? 'Already submitted a run for this seed.');
    await loadBoard();
  } catch (error) {
    noteEl.textContent = `Could not submit: ${error.message}`;
  }
});

againEl.addEventListener('click', () => {
  againEl.blur();
  start();
});

const boards = createBoards({
  game: GAME_NAME,
  tableEl,
  tabsEl,
  // "did this run place" is a question about today, so the daily rows are
  // what the entry panel is decided on whichever tab is showing
  onDaily: (rows) => {
    lastBoard = rows;
  },
});

const loadBoard = () => boards.refresh();


/**
 * Offline is the default: without a seed from the server the game still
 * plays, on a seed derived by today's date the same way the server
 * derives it. Only the leaderboard needs the network.
 */
async function init() {
  try {
    const response = await fetch('/game/seed?game=courses');
    const data = await response.json();
    seed = data.seed;
    day = data.day;
    submittable = true;
    statusEl.textContent = `Today's seed. Press any key to start.`;
    await boards.load();
  } catch {
    // the same derivation the server uses, imported rather than rewritten,
    // so an offline run really is on the same board as everyone else's
    // that day - it simply cannot be submitted until the network is back
    day = dayOf(Date.now());
    seed = seedFor('courses', day);
    statusEl.textContent = 'Offline. Press any key to start.';
    tableEl.innerHTML = '<tr><td>The board is unreachable.</td></tr>';
  }
  draw();
}

init();
