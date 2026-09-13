/**
 * The Rust core, as the worker sees it.
 *
 * `core/` is compiled to wasm and imported statically - Workers allow
 * `import mod from './x.wasm'` yielding a `WebAssembly.Module`, but refuse
 * runtime compilation, so the module is uploaded with the script rather
 * than fetched.
 *
 * This is the same binary the native client links as an rlib, and
 * `ci/cross-target.mjs` is what makes that claim checkable rather than
 * asserted.
 */

import wasmModule from './ashlaros_games.wasm';

// One instance per isolate. Workers handle one request at a time per
// isolate, so the shared event buffer below needs no locking - but it
// does mean nothing may hold a slice of memory across an await.
const instance = new WebAssembly.Instance(wasmModule, {});
const exports = instance.exports;
const memory = new Int32Array(exports.memory.buffer);

const GAME_IDS = { courses: 0, quarry: 1 };

/**
 * Replay an event log through the Rust simulation.
 *
 * Events are [action, tick] or [action, tick, value] as each game emits
 * them; the value lane is zero for games that do not use it.
 */
export function replay(game, seed, events) {
  const id = GAME_IDS[game] ?? 0;
  const max = exports.max_events();
  if (events.length > max) throw new Error('too many events');

  const base = exports.events_ptr() >> 2;
  for (let i = 0; i < events.length; i++) {
    const event = events[i];
    memory[base + i * 3] = event[0] | 0;
    memory[base + i * 3 + 1] = event[1] | 0;
    // Courses events are two-element; `undefined | 0` would be 0 anyway,
    // but saying so is cheaper to read than relying on it.
    memory[base + i * 3 + 2] = event.length > 2 ? event[2] | 0 : 0;
  }

  const score = exports.replay(id, seed >>> 0, events.length) >>> 0;
  return { score, detail: exports.last_detail() >>> 0, ticks: exports.last_ticks() >>> 0 };
}
