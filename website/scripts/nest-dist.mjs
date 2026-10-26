// When the site is mounted at a subpath (BASE_PATH=/beacon), move the build
// output into dist/<base>/ so a static host serves it at that URL without
// needing rewrite rules. No-op when BASE_PATH is unset or "/".
import { mkdirSync, readdirSync, renameSync } from 'node:fs';
import { join } from 'node:path';

const base = (process.env.BASE_PATH ?? '/').replace(/^\/+|\/+$/g, '');
if (!base) process.exit(0);

const dist = 'dist';
const target = join(dist, base);
mkdirSync(target, { recursive: true });
for (const name of readdirSync(dist)) {
  if (name === base.split('/')[0]) continue;
  renameSync(join(dist, name), join(target, name));
}
console.log(`nested dist/ -> ${target}/`);
