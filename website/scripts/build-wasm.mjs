// Builds the playground's WebAssembly module from beacon's Rust core and
// copies it to public/beacon.wasm. Requires the wasm32-unknown-unknown target:
//   rustup target add wasm32-unknown-unknown
import { execFileSync } from 'node:child_process';
import { copyFileSync, mkdirSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const crate = join(root, 'wasm');

execFileSync('cargo', ['build', '--release', '--target', 'wasm32-unknown-unknown'], {
  cwd: crate,
  stdio: 'inherit',
});

const built = join(crate, 'target', 'wasm32-unknown-unknown', 'release', 'beacon_wasm.wasm');
const out = join(root, 'public', 'beacon.wasm');
mkdirSync(dirname(out), { recursive: true });
copyFileSync(built, out);
console.log(`beacon.wasm: ${(statSync(out).size / 1024).toFixed(0)} KiB -> public/beacon.wasm`);
