/**
 * The background tracks, synthesised in the browser.
 *
 * Written from code rather than sourced, for the same reason the cues are:
 * nothing sampled, transcribed or transposed, so there is no licence to
 * check and no arrangement whose rights differ from its composition. That
 * trap is real - "Korobeiniki" is genuinely public domain and Hirokazu
 * Tanaka's 1989 arrangement of it is Nintendo's, and transposing clears
 * neither, because what copyright protects is the sequence of intervals
 * and the rhythm rather than the absolute pitch. So these are original.
 *
 * Synthesised here rather than shipped as WAV, and the numbers decide it.
 * A loop has to outlast the round or the player hears the seam - slopduel
 * chose 156s against a 120s duel for exactly that. Three tracks long
 * enough to cover a 120s run are 33 MiB of PCM. This module is 6 KiB, and
 * the browser renders it into a buffer at load.
 *
 * That is also what makes the tempo a parameter rather than a resample:
 * speeding a file up shortens it, so a sourced loop's "outlasts the
 * round" guarantee has to be computed at the fastest rate. Here it is
 * rendered at whatever rate is asked for.
 */

/** Equal temperament from A4, so a track is written in semitones. */
const note = (semitones) => 440 * 2 ** (semitones / 12);
const db = (value) => 10 ** (value / 20);

export const TRACKS = {
  // minor and patient: this one plays under most runs, so it has to be
  // the one that survives being heard most
  ashlar: {
    bpm: 96,
    progression: [0, -3, -5, -3],
    degrees: [0, 3, 7, 10],
    bassOctave: -24,
    lead: db(-20),
  },
  // brighter and a little faster, major thirds
  quarry: {
    bpm: 112,
    progression: [0, 5, 3, -2],
    degrees: [0, 4, 7, 12],
    bassOctave: -24,
    lead: db(-21),
  },
  // sparse and low, for when the other two have been heard enough
  dusk: {
    bpm: 84,
    progression: [-5, -7, -10, -7],
    degrees: [0, 3, 7, 14],
    bassOctave: -12,
    lead: db(-22),
  },
};

export const TRACK_NAMES = Object.keys(TRACKS);

/**
 * Which track a seed gets.
 *
 * Keyed separately from the game's own stream, which is the load-bearing
 * part: derived from `${seed}:music` rather than from the seed directly,
 * so adding a fourth track later cannot shift a single piece. Seeded at
 * all because two players on the same daily seed should hear the same
 * thing - it makes the music part of the shared board rather than noise.
 */
export function trackFor(seed) {
  let hash = 2166136261 >>> 0;
  for (const character of `${seed >>> 0}:music`) {
    hash = Math.imul(hash ^ character.charCodeAt(0), 16777619) >>> 0;
  }
  return TRACK_NAMES[hash % TRACK_NAMES.length];
}

function rng(seed) {
  let state = seed >>> 0;
  return () => {
    state = (Math.imul(state ^ (state >>> 15), 0x2c1b3c6d) + 0x9e3779b9) >>> 0;
    return state / 0x100000000;
  };
}

/** A soft attack and a long tail: nothing in a background track clicks. */
function pluck(t, length) {
  return Math.min(1, t / 0.01) * Math.exp((-t / length) * 3.2);
}

/**
 * Render a track into a Float32Array.
 *
 * `seconds` is a floor rather than a target: the render runs whole bars,
 * so the result is the first bar boundary at or past it. A loop that ends
 * mid-bar would click on the wrap, which is worse than being a second
 * longer than asked.
 */
export function renderTrack(name, { rate = 44100, seconds = 130, tempo = 1 } = {}) {
  const track = TRACKS[name] ?? TRACKS[TRACK_NAMES[0]];
  const beat = 60 / (track.bpm * tempo);
  const barLength = beat * 4;
  const bars = Math.ceil(seconds / barLength);
  const length = Math.round(bars * barLength * rate);
  const samples = new Float32Array(length);
  const random = rng(0x5eed0000 ^ name.length);

  const add = (start, hz, len, shape, gain) => {
    const from = Math.round(start * rate);
    const count = Math.min(Math.round(len * rate), length - from);
    for (let i = 0; i < count; i++) {
      const t = i / rate;
      samples[from + i] += shape(hz, t) * pluck(t, len) * gain;
    }
  };

  const sine = (hz, t) => Math.sin(hz * t * Math.PI * 2);
  // a triangle rather than a sine for the bass: a little edge, so it is
  // audible under the arpeggio without being loud
  const tri = (hz, t) => 4 * Math.abs(((hz * t) % 1) - 0.5) - 1;

  for (let bar = 0; bar < bars; bar++) {
    const root = track.progression[bar % track.progression.length];
    const barStart = bar * barLength;

    for (let b = 0; b < 4; b++) {
      add(barStart + b * beat, note(root + track.bassOctave), beat * 0.9, tri, db(-14));
    }

    for (let step = 0; step < 16; step++) {
      const degree = track.degrees[step % track.degrees.length];
      // the octave rises through the bar, so a loop has a shape rather
      // than being a texture
      const octave = step < 8 ? 0 : 12;
      add(
        barStart + step * (beat / 4),
        note(root + degree + octave),
        (beat / 4) * 0.85,
        sine,
        track.lead,
      );
    }

    for (let b = 0; b < 4; b++) {
      const start = Math.round((barStart + (b + 0.5) * beat) * rate);
      const count = Math.min(Math.round(0.03 * rate), length - start);
      for (let i = 0; i < count; i++) {
        samples[start + i] += (random() * 2 - 1) * pluck(i / rate, 0.03) * db(-34);
      }
    }
  }

  return samples;
}
