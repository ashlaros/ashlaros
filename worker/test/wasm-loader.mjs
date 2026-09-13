/**
 * Teach `node --test` the `.wasm` import Workers gives us natively.
 *
 * Wrangler compiles a `.wasm` import to a `WebAssembly.Module`; Node has
 * no such loader. Without this the tests would have to stub the core,
 * and a stubbed verifier tests nothing - the whole point is that the
 * thing scoring runs in the tests is the binary that scores them live.
 */

import { readFile } from 'node:fs/promises';

export async function resolve(specifier, context, next) {
  if (specifier.endsWith('.wasm')) {
    return { url: new URL(specifier, context.parentURL).href, shortCircuit: true };
  }
  return next(specifier, context);
}

export async function load(url, context, next) {
  if (url.endsWith('.wasm')) {
    const bytes = await readFile(new URL(url));
    // re-exported as source text rather than an object: a module loader
    // returns code, and the bytes are small enough that base64 costs
    // less than a side channel would
    return {
      format: 'module',
      shortCircuit: true,
      source: `const bytes = Uint8Array.from(atob(${JSON.stringify(bytes.toString('base64'))}), (c) => c.charCodeAt(0));
export default new WebAssembly.Module(bytes);`,
    };
  }
  return next(url, context);
}
