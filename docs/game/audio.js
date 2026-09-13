/**
 * Playing the cues, and never being a reason the game fails to start.
 *
 * Silence is a first-class path rather than an error case: the page runs
 * with audio blocked by autoplay policy, with the files missing entirely,
 * with no output device, and muted by choice. Each of those is a normal
 * outcome here, so nothing in this file throws and nothing in the game
 * waits on it.
 *
 * Nothing here may affect the simulation. Audio is told what happened; it
 * never decides anything.
 */

import { renderTrack, trackFor } from './music.js';

const MUTE_KEY = 'ashlaros:game:muted';
// A floor rather than a target: a run is capped at 120 seconds, and a
// loop that wrapped inside one would put a seam in the middle of it -
// slopduel chose 156s against a 120s duel for the same reason. The
// render runs whole bars, so the real length is the first bar boundary
// past this.
const LOOP_SECONDS = 130;

const CUES = [
  'move',
  'rotate',
  'drop',
  'lock',
  'hold',
  'clear-1',
  'clear-2',
  'clear-3',
  'clear-4',
  'levelup',
  'gameover',
  'brick-1',
  'brick-2',
  'brick-3',
  'paddle',
  'wall',
  'solid',
  'capsule',
  'catch',
  'lost',
  'levelclear',
];

export function createAudio() {
  let context = null;
  const buffers = new Map();
  let muted = false;
  let music = null;
  try {
    muted = localStorage.getItem(MUTE_KEY) === '1';
  } catch {
    // a browser with storage disabled still plays; the preference simply
    // does not persist
  }

  /**
   * The context cannot exist until a gesture, and asking earlier is what
   * produces the console warning every autoplay-policy page has. So this
   * is called from the first keypress and never before.
   */
  function ensure() {
    if (context) return context;
    try {
      const Ctor = window.AudioContext || window.webkitAudioContext;
      if (!Ctor) return null;
      context = new Ctor();
    } catch {
      context = null;
    }
    return context;
  }

  async function load(name) {
    const ctx = ensure();
    if (!ctx || buffers.has(name)) return;
    // marked before the fetch, so a second call cannot start a second one
    buffers.set(name, null);
    try {
      const response = await fetch(`./audio/${name}.wav`);
      if (!response.ok) return;
      buffers.set(name, await ctx.decodeAudioData(await response.arrayBuffer()));
    } catch {
      // a missing or undecodable file is silence for that cue and nothing
      // more - the rest of the set still plays
    }
  }

  function stopMusic() {
    if (!music) return;
    try {
      music.source.stop();
    } catch {
      // already stopped
    }
    music = null;
  }

  return {
    /** Called from the first real gesture, which is when a context is allowed. */
    start() {
      const ctx = ensure();
      if (!ctx) return;
      if (ctx.state === 'suspended') ctx.resume().catch(() => {});
      for (const name of CUES) load(name);
    },

    /**
     * Start the track this seed drew.
     *
     * Rendered here rather than fetched: three loops long enough to
     * outlast a run are 33 MiB of PCM, against 6 KiB for the module that
     * makes them. It also costs a few hundred milliseconds of main
     * thread, so it happens once at the start of a run rather than per
     * life.
     */
    music(seed) {
      const ctx = ensure();
      if (!ctx || muted || music) return;
      try {
        const name = trackFor(seed);
        const samples = renderTrack(name, { rate: ctx.sampleRate, seconds: LOOP_SECONDS });
        const buffer = ctx.createBuffer(1, samples.length, ctx.sampleRate);
        buffer.copyToChannel(samples, 0);
        const source = ctx.createBufferSource();
        source.buffer = buffer;
        source.loop = true;
        const volume = ctx.createGain();
        // under the cues by a wide margin: the cues carry information and
        // the track carries none, so it must never compete
        volume.gain.value = 0.5;
        source.connect(volume).connect(ctx.destination);
        source.start();
        music = { source, volume };
      } catch {
        // a track that cannot be built is silence, and the cues are
        // unaffected
      }
    },

    stopMusic,

    play(name, gain = 1) {
      if (muted || !context) return;
      const buffer = buffers.get(name);
      // still loading, missing, or never requested: silence, not an error
      if (!buffer) return;
      try {
        const source = context.createBufferSource();
        source.buffer = buffer;
        const volume = context.createGain();
        volume.gain.value = gain;
        source.connect(volume).connect(context.destination);
        source.start();
      } catch {
        // an exhausted or closed context must not take the game with it
      }
    },

    get muted() {
      return muted;
    },

    toggle() {
      muted = !muted;
      // the track is the one thing that keeps making noise on its own, so
      // muting has to stop it rather than wait for it to end
      if (muted) stopMusic();
      try {
        localStorage.setItem(MUTE_KEY, muted ? '1' : '0');
      } catch {
        // unchanged behaviour, just not remembered
      }
      return muted;
    },
  };
}
