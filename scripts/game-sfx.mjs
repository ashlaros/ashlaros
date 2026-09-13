/**
 * Generate the games' sound cues.
 *
 * Written from code rather than sourced: no third-party rights to check,
 * nothing sampled or transcribed from any other work, kilobytes instead
 * of megabytes, and - the part a sourced file cannot give us - a cue can
 * be rendered at any tempo or pitch from the same source.
 *
 * WAV, because the format is a header plus PCM and needs no encoder.
 *
 * Deterministic, and that is load-bearing: the noise comes from a seeded
 * PRNG so a rerun on an unchanged script leaves the working tree clean,
 * and a dirty diff means the script really changed. Math.random() would
 * make every run emit different bytes and the diff could never be
 * trusted.
 *
 *   node scripts/game-sfx.mjs docs/game/audio
 */

import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const RATE = 44100;

/** Decibels, because that is the perceptual unit a mix is reasoned in. */
const db = (value) => 10 ** (value / 20);

/**
 * A seeded generator, shared with the games (worker/src/game/logic.js
 * carries the same mix constants) so noise is reproducible.
 */
function rng(seed) {
  let state = seed >>> 0;
  return () => {
    state = (Math.imul(state ^ (state >>> 15), 0x2c1b3c6d) + 0x9e3779b9) >>> 0;
    return state / 0x100000000;
  };
}

/** An envelope that never clicks: everything gets an attack and a decay. */
function envelope(i, length, attack = 0.002, release = 0.05) {
  const t = i / RATE;
  const total = length / RATE;
  const up = Math.min(1, t / attack);
  const down = Math.min(1, (total - t) / release);
  return Math.max(0, up * down);
}

const sine = (phase) => Math.sin(phase * Math.PI * 2);
const square = (phase) => (phase % 1 < 0.5 ? 1 : -1);
const triangle = (phase) => 4 * Math.abs((phase % 1) - 0.5) - 1;

/**
 * Render one cue.
 *
 * `tone` is called per sample with (t, i) and returns -1..1. Everything
 * else - length, gain, the envelope - is handled here so a cue is a
 * description of a sound rather than a loop over samples.
 */
function render({ seconds, gain = db(-6), tone, attack, release }) {
  const length = Math.round(seconds * RATE);
  const samples = new Float32Array(length);
  for (let i = 0; i < length; i++) {
    samples[i] = tone(i / RATE, i) * envelope(i, length, attack, release) * gain;
  }
  return samples;
}

/** A frequency sweep, linear in log space so it sounds even. */
const sweep = (from, to, t, seconds) => from * (to / from) ** Math.min(1, t / seconds);

function wav(samples) {
  const header = Buffer.alloc(44);
  const data = Buffer.alloc(samples.length * 2);
  for (let i = 0; i < samples.length; i++) {
    // clamped, not wrapped: a clipped sample that wraps is a click
    const value = Math.max(-1, Math.min(1, samples[i]));
    data.writeInt16LE(Math.round(value * 32767), i * 2);
  }
  header.write('RIFF', 0);
  header.writeUInt32LE(36 + data.length, 4);
  header.write('WAVE', 8);
  header.write('fmt ', 12);
  header.writeUInt32LE(16, 16);
  header.writeUInt16LE(1, 20); // PCM
  header.writeUInt16LE(1, 22); // mono
  header.writeUInt32LE(RATE, 24);
  header.writeUInt32LE(RATE * 2, 28);
  header.writeUInt16LE(2, 32);
  header.writeUInt16LE(16, 34);
  header.write('data', 36);
  header.writeUInt32LE(data.length, 40);
  return Buffer.concat([header, data]);
}

// A major triad plus the octave, in Hz. The ladder cues walk up this, so
// clearing more lines literally walks up a chord - the player hears how
// well they did without reading the score.
const TRIAD = [440, 554, 659, 880];

/**
 * The cues.
 *
 * Frequency is the information channel and loudness is the priority
 * channel: what happens every second is quiet and dull, what happens
 * rarely is loud and bright. Backwards, and the game is exhausting inside
 * a minute.
 */
const CUES = {
  // --- Courses: the things that fire constantly ---
  move: {
    seconds: 0.02,
    gain: db(-30),
    attack: 0.001,
    release: 0.012,
    tone: (t) => square(t * 900) * 0.5,
  },
  rotate: {
    seconds: 0.03,
    gain: db(-26),
    attack: 0.001,
    release: 0.02,
    tone: (t) => triangle(t * 1200),
  },
  // The commitment, and the most satisfying input in the game: a
  // percussive thud, short, with body rather than pitch.
  drop: {
    seconds: 0.09,
    gain: db(-9),
    attack: 0.001,
    release: 0.07,
    tone: (t, i) => sine(sweep(220, 70, t, 0.09) * t) * 0.8 + noise(i) * 0.2,
  },
  // Confirms placement, distinct from the drop that precedes it: duller,
  // lower, and clearly a different event rather than an echo.
  lock: {
    seconds: 0.05,
    gain: db(-20),
    attack: 0.001,
    release: 0.04,
    tone: (t) => sine(t * 120) * 0.7 + sine(t * 180) * 0.3,
  },
  // Free once per piece and costly to waste: pleasant, but not a reward.
  // A neutral swap rather than a chime.
  hold: {
    seconds: 0.06,
    gain: db(-22),
    attack: 0.004,
    release: 0.05,
    tone: (t) => triangle(sweep(500, 400, t, 0.06) * t),
  },

  // --- Courses: the ladder ---
  // Four files, never one repitched. Resampling shortens a sound, so a
  // four-line clear would answer SHORTER than a single - the opposite of
  // what it means.
  ...Object.fromEntries(
    TRIAD.map((root, index) => [
      `clear-${index + 1}`,
      {
        // each rung is longer as well as higher, so the jackpot lands
        seconds: 0.16 + index * 0.06,
        gain: db(-10 + index),
        attack: 0.003,
        release: 0.12,
        tone: (t) =>
          sine(root * t) * 0.6 +
          sine(root * 2 * t) * 0.25 +
          sine(root * 3 * t) * 0.15,
      },
    ]),
  ),

  // The gravity changed and the player must anticipate it, so this sits
  // above the clears rather than competing with them.
  levelup: {
    seconds: 0.3,
    gain: db(-8),
    attack: 0.004,
    release: 0.2,
    tone: (t) => sine(sweep(660, 1320, t, 0.3) * t) * 0.7,
  },
  // The run ended: the longest, lowest, falling thing in the set.
  gameover: {
    seconds: 0.9,
    gain: db(-7),
    attack: 0.01,
    release: 0.6,
    tone: (t) => sine(sweep(330, 60, t, 0.9) * t) * 0.8 + triangle(sweep(165, 30, t, 0.9) * t) * 0.2,
  },

  // --- Quarry ---
  // The brick ladder, same reasoning as the line clears: breaking upward
  // through the wall walks up a chord, so a player hears how deep they
  // are without looking.
  ...Object.fromEntries(
    [0, 1, 2].map((tier) => [
      `brick-${tier + 1}`,
      {
        seconds: 0.05 + tier * 0.02,
        gain: db(-16 + tier * 3),
        attack: 0.001,
        release: 0.05,
        tone: (t) => triangle(TRIAD[tier] * t) * 0.8,
      },
    ]),
  ),
  // Happens constantly, so it sits below the bricks: a cue that competed
  // with them would bury the one piece of information the ladder carries.
  paddle: {
    seconds: 0.03,
    gain: db(-24),
    attack: 0.001,
    release: 0.025,
    tone: (t) => sine(t * 300) * 0.8,
  },
  wall: {
    seconds: 0.025,
    gain: db(-28),
    attack: 0.001,
    release: 0.02,
    tone: (t) => sine(t * 220) * 0.7,
  },
  // An indestructible brick: the ball comes back and nothing happened,
  // and the cue should say so - dead, not bright.
  solid: {
    seconds: 0.04,
    gain: db(-22),
    attack: 0.001,
    release: 0.035,
    tone: (t, i) => noise(i) * 0.6 + sine(t * 90) * 0.4,
  },
  // A capsule appearing is an invitation, not an achievement, so it is
  // quiet. Catching one is the achievement.
  capsule: {
    seconds: 0.05,
    gain: db(-26),
    attack: 0.003,
    release: 0.04,
    tone: (t) => sine(sweep(880, 1100, t, 0.05) * t) * 0.6,
  },
  catch: {
    seconds: 0.18,
    gain: db(-10),
    attack: 0.002,
    release: 0.14,
    tone: (t) => sine(sweep(523, 1046, t, 0.18) * t) * 0.7 + sine(784 * t) * 0.3,
  },
  // A ball lost: falling, and it should feel like losing something.
  lost: {
    seconds: 0.45,
    gain: db(-9),
    attack: 0.004,
    release: 0.35,
    tone: (t) => sine(sweep(440, 80, t, 0.45) * t) * 0.8,
  },
  // The one unambiguously good event in the game.
  levelclear: {
    seconds: 0.5,
    gain: db(-7),
    attack: 0.004,
    release: 0.3,
    tone: (t) =>
      TRIAD.reduce(
        // an arpeggio rather than a chord: each note starts a beat later,
        // so it reads as an ascent rather than a wash
        (sum, note, index) => sum + (t > index * 0.08 ? sine(note * t) * 0.25 : 0),
        0,
      ),
  },
};

// One noise source for every cue that wants it, seeded once so the whole
// set is reproducible together.
const random = rng(0x9e3779b9);
const NOISE = new Float32Array(RATE);
for (let i = 0; i < NOISE.length; i++) NOISE[i] = random() * 2 - 1;
function noise(i) {
  return NOISE[i % NOISE.length];
}

const out = process.argv[2] ?? 'docs/game/audio';
mkdirSync(out, { recursive: true });

let total = 0;
for (const [name, cue] of Object.entries(CUES)) {
  const bytes = wav(render(cue));
  writeFileSync(join(out, `${name}.wav`), bytes);
  total += bytes.length;
  console.log(`${name.padEnd(12)} ${String(bytes.length).padStart(7)} bytes`);
}
console.log(`\n${Object.keys(CUES).length} cues, ${(total / 1024).toFixed(1)} KiB total`);
