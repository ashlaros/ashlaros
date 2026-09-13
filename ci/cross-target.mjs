// Do the native build and the wasm build agree?
//
// `cargo test` writes what the native target scored for a fixed corpus;
// this replays the identical corpus through the wasm module and diffs.
// The corpus is generated the same way on both sides - same generator,
// same constants - so a difference is the compilers disagreeing, which is
// exactly what "one implementation, two targets" has to rule out.

import { readFileSync } from 'node:fs';

const root = new URL('..', import.meta.url).pathname;
const bytes = readFileSync(`${root}core/target/wasm32-unknown-unknown/release/ashlaros_games.wasm`);
const wasm = new WebAssembly.Instance(new WebAssembly.Module(bytes), {}).exports;
const memory = new Int32Array(wasm.memory.buffer);

// The same LCG the Rust side uses, in the same order, so the corpus is
// identical without shipping it as data.
let state = 12345;
const rand = (n) => {
  state = ((Math.imul(state, 1103515245) + 12345) & 0x7fffffff) >>> 0;
  return state % n;
};

const FIELD_W = 240 * 16;
const cases = [];

for (let run = 0; run < 40; run++) {
  const seed = (2948530700 + Math.imul(run, 7919)) >>> 0;
  const events = [];
  let tick = 0;
  for (let i = 0; i < 300; i++) {
    tick += 1 + rand(8);
    events.push([rand(7), tick, 0]);
  }
  cases.push([0, seed, events]);
}

for (let run = 0; run < 40; run++) {
  const seed = (3201124988 + Math.imul(run, 7919)) >>> 0;
  const events = [[1, 0, 0]];
  let tick = 0;
  for (let i = 0; i < 300; i++) {
    tick += 1 + rand(20);
    events.push([0, tick, rand(FIELD_W)]);
  }
  cases.push([1, seed, events]);
}

const base = wasm.events_ptr() >> 2;
const actual = cases.map(([game, seed, events]) => {
  events.forEach(([action, tick, value], i) => {
    memory[base + i * 3] = action;
    memory[base + i * 3 + 1] = tick;
    memory[base + i * 3 + 2] = value;
  });
  const score = wasm.replay(game, seed, events.length) >>> 0;
  return `${game} ${seed} ${score} ${wasm.last_detail() >>> 0} ${wasm.last_ticks() >>> 0}`;
});

const expected = readFileSync(`${root}core/target/native-results.txt`, 'utf8').trim().split('\n');

if (expected.length !== actual.length) {
  console.error(`corpus length differs: native ${expected.length}, wasm ${actual.length}`);
  process.exit(1);
}

let differing = 0;
for (let i = 0; i < expected.length; i++) {
  if (expected[i] !== actual[i]) {
    differing++;
    if (differing <= 5) console.error(`case ${i}:\n  native ${expected[i]}\n  wasm   ${actual[i]}`);
  }
}

if (differing) {
  console.error(`${differing}/${expected.length} cases disagree across targets`);
  process.exit(1);
}

console.log(`${actual.length} cases, native and wasm agree`);
