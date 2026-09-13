/**
 * Registers the .wasm loader. Separate from the loader itself because
 * `--import` runs on the main thread while the hooks run off it.
 */

import { register } from 'node:module';

register('./wasm-loader.mjs', import.meta.url);
