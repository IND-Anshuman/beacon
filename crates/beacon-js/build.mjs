// Builds the npm package: compiles beacon-js to wasm32 and runs wasm-bindgen
// into pkg/ (next to the hand-written facade). Requires the wasm32 target and
// wasm-bindgen on PATH (or set WASM_BINDGEN to its path); its version must match
// the `wasm-bindgen` crate version in Cargo.toml.
import { execFileSync } from 'node:child_process';
import { rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const crate = dirname(fileURLToPath(import.meta.url));
const wasmBindgen = process.env.WASM_BINDGEN || 'wasm-bindgen';
const pkg = join(crate, 'pkg');

execFileSync('cargo', ['build', '--release', '--target', 'wasm32-unknown-unknown'], { cwd: crate, stdio: 'inherit' });

const wasm = join(crate, 'target', 'wasm32-unknown-unknown', 'release', 'beacon_js.wasm');
execFileSync(wasmBindgen, ['--target', 'web', '--out-dir', pkg, wasm], { cwd: crate, stdio: 'inherit' });

// wasm-bindgen drops a `.gitignore` of `*` in the out-dir, which would also hide
// the hand-written package files. Remove it; ignoring is handled by
// crates/beacon-js/.gitignore instead.
rmSync(join(pkg, '.gitignore'), { force: true });

console.log('built pkg/');
