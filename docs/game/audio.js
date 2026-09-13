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

const MUTE_KEY = 'ashlaros:game:muted';

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

  return {
    /** Called from the first real gesture, which is when a context is allowed. */
    start() {
      const ctx = ensure();
      if (!ctx) return;
      if (ctx.state === 'suspended') ctx.resume().catch(() => {});
      for (const name of CUES) load(name);
    },

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
      try {
        localStorage.setItem(MUTE_KEY, muted ? '1' : '0');
      } catch {
        // unchanged behaviour, just not remembered
      }
      return muted;
    },
  };
}
