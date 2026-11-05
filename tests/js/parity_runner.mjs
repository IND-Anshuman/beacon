// Cross-language parity runner. Reads a JSON array of calls from stdin
//   [{ "id": "...", "fn": "extractJson", "args": [ ... ] }, ...]
// and writes { id: { ok: "<string result>" } | { err: "<code>" } } to stdout.
// It calls the LOW-LEVEL wasm exports (which return beacon's canonical JSON
// text), so results can be compared byte-for-byte against the Python package.
import { readFileSync } from 'node:fs';
import initWasm, * as wasm from '../../crates/beacon-js/pkg/beacon_js.js';

const wasmUrl = new URL('../../crates/beacon-js/pkg/beacon_js_bg.wasm', import.meta.url);
await initWasm({ module_or_path: readFileSync(wasmUrl) });

const calls = JSON.parse(readFileSync(0, 'utf8'));
const out = {};
for (const { id, fn, args } of calls) {
  try {
    const result = wasm[fn](...args);
    out[id] = { ok: result === undefined ? '' : String(result) };
  } catch (e) {
    out[id] = { err: e && typeof e.code === 'string' ? e.code : `${e}` };
  }
}
process.stdout.write(JSON.stringify(out));
