# beacon docs site

The documentation website for beacon: a custom landing page plus
[Starlight](https://starlight.astro.build) docs, with a live playground that
runs beacon's Rust core in the browser via WebAssembly.

```bash
npm install
npm run wasm      # build public/beacon.wasm from ../src (needs: rustup target add wasm32-unknown-unknown)
npm run dev       # http://localhost:4321
npm run build     # static site in dist/
```

| Path | What |
| --- | --- |
| `src/pages/index.astro` | landing page (sections in `src/components/landing/`) |
| `src/pages/playground.astro` | full-screen playground |
| `src/components/Playground.astro` | the playground component (also embedded in block docs) |
| `src/scripts/playground-config.ts` | playground operations, fields and presets |
| `src/content/docs/` | the docs, as MDX |
| `wasm/` | the WebAssembly bridge crate (no wasm-bindgen; JSON in, JSON out) |
| `astro.config.mjs` | Starlight config and sidebar |

Deployment: `.github/workflows/docs.yml` builds the wasm engine and the site
and publishes to GitHub Pages. `SITE_URL`, `BASE_PATH` and `PUBLIC_REPO_URL`
are set automatically there. `PUBLIC_REPO_URL` defaults to
https://github.com/IND-Anshuman/beacon. The live site is https://www.anshumanbuilds.dev/beacon/.
