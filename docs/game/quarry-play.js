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
  BALL_SPEED,
  BALL_SPEED_MAX,
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
import { createAudio } from './audio.js';
import { createBoards } from './boards.js';
import { createEffects } from './effects.js';

const GAME_NAME = 'quarry';
const audio = createAudio();
const effects = createEffects();

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

const CAPSULE_LABELS = {
  [CAPSULES.WIDEN]: 'WIDE',
  [CAPSULES.MULTI]: 'MULTI',
  [CAPSULES.SLOW]: 'SLOW',
  [CAPSULES.CATCH]: 'CATCH',
};

// A bounce inside this band that changed no score met an indestructible
// brick and came straight back, which is the only way to tell the two
// apart now that a break's worth depends on how fast the ball was going.
const BRICK_BAND_TOP = BRICK_TOP - BALL_R;
const BRICK_BAND_BOTTOM = BRICK_TOP + BRICK_ROWS * BRICK_H + BALL_R;

const canvas = document.getElementById('field');
const ctx = canvas.getContext('2d');
const scoreEl = document.getElementById('score');
const livesEl = document.getElementById('lives');
const levelEl = document.getElementById('level');
const speedEl = document.getElementById('speed');
const meterEl = document.getElementById('meter-fill');
const statusEl = document.getElementById('status');
const tableEl = document.getElementById('board-table');
const tabsEl = document.getElementById('board-tabs');
const entryEl = document.getElementById('entry');
const initialEls = [...document.querySelectorAll('#initials button')];
const submitEl = document.getElementById('submit');
const noteEl = document.getElementById('submit-note');
const againEl = document.getElementById('again');

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
// When the last run ended: a held arrow arrives as a fresh keydown the
// instant the run ends, and without this pause it started the next round
// before the final score was read.
let finishedAt = 0;
const AGAIN_DELAY_MS = 600;
let heldKeys = { left: false, right: false };
let lastTarget = 0;
let lastDirection = 0;
// Bricks broken without the paddle touching the ball in between. The cue
// climbs a semitone per brick on the trot, so a clean run through the wall
// is heard as a scale and the first miss is heard as the drop back.
let combo = 0;
// How hard the paddle was last hit, for the squash and flash on contact.
let paddleSquash = 0;
// Ball velocities before the tick, in a buffer that is reused rather than
// rebuilt sixty times a second. stepBall rewrites every ball in place, so
// the only way to know what a bounce did is to have looked first.
const velocities = [];
// The wall before the tick, for the same reason and the same fix: a break
// takes the tier off, and the debris has to be the colour the brick WAS.
const wallBefore = new Int8Array(BRICK_COLS * BRICK_ROWS);

function snapshotVelocities() {
  velocities.length = 0;
  for (const ball of state.balls) velocities.push(ball.vx, ball.vy);
  return velocities;
}

function snapshotWall() {
  for (let i = 0; i < wallBefore.length; i++) wallBefore[i] = state.bricks[i];
}

/**
 * How far the ball is from its starting pace to its ceiling, 0..1.
 *
 * Everything that says "faster" - the tint, the smear, the meter - reads
 * this one number, so the three cannot drift apart and describe three
 * different speeds.
 */
function heat() {
  const speed = state ? (state.speed ?? BALL_SPEED) : BALL_SPEED;
  const span = BALL_SPEED_MAX - BALL_SPEED;
  return span > 0 ? Math.max(0, Math.min(1, (speed - BALL_SPEED) / span)) : 0;
}

/**
 * The ball warms as it speeds up: white at the run's starting pace and hot
 * by the time it is out of control. The only hue on the page and barely
 * that - the palette is stone, so this has to read as heat rather than as
 * a second colour scheme.
 */
function ballTint(t) {
  return `rgb(${Math.round(238 + 17 * t)},${Math.round(238 - 10 * t)},${Math.round(238 - 49 * t)})`;
}

function draw() {
  ctx.fillStyle = '#0d1112';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  if (!state) return;

  const offset = effects.shakeOffset();
  ctx.save();
  ctx.translate(offset.x, offset.y);

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

  // The paddle squashes on contact. It is the one surface the player owns
  // and the one place the game answers them physically, so it is also the
  // one that gets to move.
  const squash = paddleSquash;
  const padW = s(state.paddleW) * (1 + squash * 0.14);
  const padH = s(PADDLE_H) * (1 - squash * 0.35);
  const padX = s(state.paddleX) - (padW - s(state.paddleW)) / 2;
  const padY = s(PADDLE_Y) + s(PADDLE_H) - padH;
  ctx.fillStyle = COLOURS.paddle;
  ctx.fillRect(padX, padY, padW, padH);
  if (squash > 0) {
    ctx.save();
    ctx.globalAlpha = squash * 0.45;
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(padX, padY, padW, padH);
    ctx.restore();
  }

  ctx.fillStyle = ballTint(heat());
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

  ctx.restore();
  effects.draw(ctx);

  scoreEl.textContent = state.score.toLocaleString('en-US');
  livesEl.textContent = String(Math.max(0, state.lives));
  levelEl.textContent = String(state.level);
  speedEl.textContent = `×${((state.speed ?? BALL_SPEED) / BALL_SPEED).toFixed(2)}`;
  meterEl.style.width = `${Math.round(heat() * 100)}%`;
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

/**
 * A smear behind every ball, longer the faster it is going. This is the
 * visible half of the speed ramp: the streak stretches before the player
 * has read the number beside the board.
 */
function ballTrails() {
  const warm = heat();
  const size = s(BALL_R) * (0.9 + warm * 0.6);
  const life = 0.1 + warm * 0.16;
  for (const ball of state.balls) {
    effects.trail(s(ball.x), s(ball.y), ballTint(warm), size, life);
  }
}

function emit(action, value) {
  const heldBefore = state.held;
  events.push(value === undefined ? [action, state.tick] : [action, state.tick, value]);
  applyAction(state, action, value);
  // A ball left the paddle: the first of a life, and every caught one the
  // player chooses to let go. Heard from what the action did, so a launch
  // with nothing to launch stays silent.
  if (action === ACTIONS.LAUNCH && heldBefore && !state.held) audio.play('launch');
}

/**
 * Keys aim at an edge, not a step ahead of the paddle.
 *
 * The paddle already closes on its target at PADDLE_SPEED, so a held key
 * needs one event, not one per tick: aim at the wall in that direction,
 * and on release aim where the paddle is so it stops there. The old way
 * nudged the target every tick while a key was down, which is sixty
 * events a second - steady steering reached the server's MAX_EVENTS
 * before the two minutes were up and the honest run was refused. It also
 * let the target run ahead of the paddle, so it drifted on after release.
 */
function steer() {
  if (!state || state.over) return;
  const direction = (heldKeys.right ? 1 : 0) - (heldKeys.left ? 1 : 0);
  if (direction === lastDirection) return;
  lastDirection = direction;
  const target =
    direction < 0 ? 0 : direction > 0 ? FIELD_W - state.paddleW : state.paddleX;
  if (target !== lastTarget) {
    emit(ACTIONS.TARGET, target);
    lastTarget = target;
  }
}

function frame(now) {
  if (!running) return;
  const elapsed = Math.min(now - lastFrame, 250);
  lastFrame = now;
  accumulator += elapsed;
  // The effects ride the frame clock and are never fed a tick, so the
  // replay owes them nothing.
  effects.update(elapsed);
  paddleSquash *= Math.exp(-elapsed / 110);
  if (paddleSquash < 0.01) paddleSquash = 0;

  const step = 1000 / TICKS_PER_SECOND;
  while (accumulator >= step) {
    accumulator -= step;
    steer();
    // Cues are read from what the tick changed, rather than the
    // simulation being asked to announce things. That keeps audio out of
    // the shared module entirely - the verifier must not carry a sound
    // system to replay a run.
    const before = {
      score: state.score,
      bricks: state.bricksBroken,
      lives: state.lives,
      level: state.level,
      balls: state.balls.length,
      // copied rather than referenced: a capsule dropped this tick is
      // pushed onto the same array the tick is about to replace
      capsules: state.capsules.slice(),
      speed: state.speed ?? BALL_SPEED,
      velocities: snapshotVelocities(),
    };
    snapshotWall();
    stepTick(state);
    announce(before);
    if (state.over) {
      finish();
      return;
    }
  }
  ballTrails();
  draw();
  requestAnimationFrame(frame);
}

/**
 * What the tick did, as sound and as effect.
 *
 * A brick that took a hit is the ladder; everything that happens
 * constantly sits below it, or a cue that competes with the bricks buries
 * the one piece of information the ladder carries.
 */
function announce(before) {
  // The rally stepped the pace up on a paddle return, so this lands with
  // the bounce that earned it and says the point just got more valuable
  // and more dangerous at the same time.
  if ((state.speed ?? BALL_SPEED) > before.speed) audio.play('speedup');

  if (state.level > before.level) {
    audio.play('levelclear');
    effects.banner(`LEVEL ${state.level}`);
    audio.tempo(1 + Math.min(state.level, 12) * 0.015);
    return;
  }
  if (state.lives < before.lives) {
    audio.play('lost');
    effects.shake(9);
    return;
  }

  // A capsule is caught rather than lost when it stopped before the floor:
  // the ones that simply fall out of the field leave without a sound, and
  // the object is the same one that was falling, so its kind is readable.
  const caught = before.capsules.find(
    (capsule) => capsule.y < FIELD_H && state.capsules.indexOf(capsule) < 0,
  );
  if (caught) {
    const label = CAPSULE_LABELS[caught.kind] ?? 'CATCH';
    // MULTI changes the shape of the whole point rather than helping one
    // ball, so it is not the pickup's chime.
    audio.play(caught.kind === CAPSULES.MULTI ? 'multi' : 'catch');
    effects.popup(label, s(caught.x), s(caught.y), '#c9ccd1');
    if (caught.kind === CAPSULES.MULTI) effects.shake(3);
  }

  brickEffects();

  if (state.bricksBroken > before.bricks) {
    const rung = brokenTier();
    combo += 1;
    // A semitone per brick on the trot, capped at an octave. The ladder
    // cues carry how strong the brick was; this carries how long the
    // player has gone without missing.
    audio.play(`brick-${rung}`, 1, 2 ** (Math.min(combo, 12) / 12));
  } else if (state.score > before.score && !caught) {
    // scored without breaking anything: a partial hit on a multi-hit
    // brick
    audio.play('brick-1');
  }
  if (newCapsules(before) > 0) audio.play('capsule');

  // a ball that reversed direction against the paddle
  const bounced = state.balls.some((ball, i) => velocities[i * 2 + 1] > 0 && ball.vy < 0);
  if (bounced) {
    // the paddle is where the streak ends, so this is the sound of the
    // climb stopping as well as of the return
    combo = 0;
    audio.play('paddle');
    paddleSquash = 1;
  }
  wallSounds(before);
}

/**
 * Which rung of the ladder the strongest brick broken this tick was on.
 *
 * Read from the wall as it was before the tick: a break takes the tier
 * off, and the score no longer names the rung either, because what a
 * brick pays now depends on how fast the ball was going when it landed.
 */
function brokenTier() {
  let rung = 1;
  for (let i = 0; i < wallBefore.length; i++) {
    const was = wallBefore[i];
    if (was > rung && state.bricks[i] !== was) rung = was;
  }
  return rung;
}

/**
 * Debris where a brick just was, in the colour it was.
 *
 * hitBrick takes the tier off before anyone can ask, so the wall as it
 * stood before the tick is the only place the old colour still exists. A
 * partial hit throws debris too - the brick visibly changed, and the
 * player should see that rather than only hear it.
 */
function brickEffects() {
  for (let i = 0; i < wallBefore.length; i++) {
    const was = wallBefore[i];
    if (was === state.bricks[i] || was <= 0) continue;
    const row = (i / BRICK_COLS) | 0;
    const col = i % BRICK_COLS;
    effects.burst(
      s(col * BRICK_W + BRICK_W / 2),
      s(BRICK_TOP + row * BRICK_H + BRICK_H / 2),
      COLOURS[was] ?? COLOURS[1],
      6,
    );
  }
}

/** How many capsules appeared this tick. */
function newCapsules(before) {
  let count = 0;
  for (const capsule of state.capsules) {
    if (before.capsules.indexOf(capsule) < 0) count += 1;
  }
  return count;
}

/**
 * The two sounds that are not about scoring.
 *
 * A wall or ceiling return is the rhythm of the point and happens
 * constantly, so it is the quietest cue in the set. An indestructible
 * brick is the one place the game tells the player that nothing happened,
 * and it must not sound like a hit. One of each per tick at most: with
 * several balls loose several surfaces go in the same tick, and a cue per
 * ball is a machine gun rather than feedback.
 */
function wallSounds(before) {
  // The snapshot is matched by index and a lost ball shifts them, so a
  // tick that changed the count is left unscored. One tick without a wall
  // cue is inaudible; one attributed to the wrong ball is a lie.
  if (state.balls.length !== before.balls) return;
  const scored = state.score !== before.score;
  let wall = false;
  let solid = false;
  for (let i = 0; i < state.balls.length; i++) {
    const ball = state.balls[i];
    const vx = velocities[i * 2];
    const vy = velocities[i * 2 + 1];
    if (Math.sign(ball.vy) !== Math.sign(vy)) {
      // the ceiling is the only vertical turn above the wall
      if (ball.y < BRICK_TOP) {
        wall = true;
      } else if (!scored && ball.y > BRICK_BAND_TOP && ball.y < BRICK_BAND_BOTTOM) {
        // turned inside the wall's band and nothing was scored: it met an
        // indestructible brick and came straight back
        solid = true;
      }
    } else if (Math.sign(ball.vx) !== Math.sign(vx)) {
      wall = true;
    }
  }
  if (solid) audio.play('solid');
  else if (wall) audio.play('wall');
}

function start() {
  if (seed === null) return;
  audio.start();
  audio.music(seed);
  audio.tempo(1);
  effects.clear();
  combo = 0;
  paddleSquash = 0;
  state = createState(seed);
  events = [];
  lastTarget = state.target;
  lastDirection = 0;
  running = true;
  accumulator = 0;
  lastFrame = performance.now();
  statusEl.textContent = 'Playing.';
  entryEl.hidden = true;
  againEl.hidden = true;
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
  finishedAt = performance.now();
  againEl.hidden = false;
  // the run is over, so what was mid-flight is debris frozen in the air
  // rather than anything still happening
  effects.clear();
  draw();
  statusEl.textContent = `Out of lives at ${state.score.toLocaleString('en-US')}. R to play again.`;
  audio.stopMusic();
  audio.play('gameover');
  if (submittable && placed(state.score)) {
    slot = 0;
    entryEl.hidden = false;
    drawInitials();
  } else {
    noteEl.textContent = submittable
      ? 'That did not place. The board keeps one run per player per seed.'
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
    // the first run starts on any key, as the page says; the next one only
    // on a deliberate Enter or R, so the end of a run is never skipped
    const deliberate = !event.repeat && (event.key === 'Enter' || event.key === 'r' || event.key === 'R');
    if (!state || (deliberate && performance.now() - finishedAt > AGAIN_DELAY_MS)) {
      event.preventDefault();
      start();
    }
    return;
  }
  if (event.key === 'm' || event.key === 'M') {
    statusEl.textContent = audio.toggle() ? 'Muted.' : 'Playing.';
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
      body: JSON.stringify({ game: GAME_NAME, day, player: initials.join(''), events }),
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
 * plays, on a seed derived by the same function the server uses. Only the
 * leaderboard needs the network.
 */
async function init() {
  try {
    const response = await fetch(`/game/seed?game=${GAME_NAME}`);
    const data = await response.json();
    seed = data.seed;
    day = data.day;
    submittable = true;
    statusEl.textContent = `Today's wall. Press any key to start.`;
    await boards.load();
  } catch {
    // the same derivation the server uses, imported rather than rewritten,
    // so an offline run really is on the same wall as everyone else's
    // that day - it simply cannot be submitted until the network is back
    day = dayOf(Date.now());
    seed = seedFor(GAME_NAME, day);
    statusEl.textContent = 'Offline. Press any key to start.';
    tableEl.innerHTML = '<tr><td>The board is unreachable.</td></tr>';
  }
  draw();
}

init();
