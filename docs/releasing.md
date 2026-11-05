# Releasing beacon (maintainer handoff)

This is the checklist for cutting a release. **Claude never runs these steps** —
`cargo publish`, `npm publish` and the PyPI upload are credentialed, irreversible
actions on your accounts. Everything below has been taken to dry-run and is
green; you run the real publishes.

## 0. Version numbers

The v1.0 work is documented as `1.0.0` in both changelogs, but the manifests
currently read **`0.3.0`** (an interim bump made on `fix/release-version-bump`).
Decide the release version and set it in **all** of these before tagging:

| File | Field |
| --- | --- |
| `Cargo.toml` | `[workspace.package] version` |
| `pyproject.toml` | `[project] version` |
| `crates/beacon-js/pkg/package.json` | `version` (the npm package) |

`crates/beacon-js/Cargo.toml` and `crates/beacon-wasm/Cargo.toml` are
`publish = false` and their versions don't ship anywhere.

## 1. Rust core → crates.io (`beacon-core`)

Verified: `cargo publish -p beacon-core --dry-run --allow-dirty` packages cleanly
(21 files). The name `beacon-core` is free on crates.io.

```bash
cargo login            # once, with your crates.io token
cargo publish -p beacon-core
```

`beacon-python`, `beacon-wasm` and `beacon-js` are `publish = false` and are not
pushed to crates.io.

## 2. Python wheels → PyPI (`llm-beacon`)

Handled by the **Release** workflow (`.github/workflows/release.yml`,
maturin-action + trusted publishing). Publish a GitHub Release (or run the
workflow manually); it builds abi3 wheels for every platform and an sdist and
uploads them. No local step is required.

To verify locally first:

```bash
# GNU toolchain on this machine — see the windows-gnu-build note:
RUSTFLAGS="-L native=C:/Users/knigh/AppData/Local/Programs/Python/Python314/libs" \
  PYO3_USE_RAW_DYLIB=0 maturin build --release
```

## 3. JavaScript → npm (`llm-beacon`)

The name `llm-beacon` is **free on npm** (it mirrors the PyPI dist name).

Build the package, then publish from `crates/beacon-js/pkg`:

```bash
cd crates/beacon-js
WASM_BINDGEN=/path/to/wasm-bindgen node build.mjs   # compiles wasm + generates bindings
cd pkg
npm pack            # inspect the tarball (verified: 8 files, ~514 kB)
npm publish         # the real publish
```

### wasm-bindgen on this machine

`wasm-bindgen` **cannot be compiled from source on the rustup GNU toolchain
here** — `cargo install wasm-bindgen-cli` fails building `windows-sys`
(`dlltool.exe` not found), the same gap behind the raw-dylib issue (see the
`windows-gnu-build` note). The verified builds used the **official prebuilt
`wasm-bindgen` 0.2.130** binary (matching the `wasm-bindgen` crate pinned in
`crates/beacon-js/Cargo.toml`). For a release build, put a matching
`wasm-bindgen` 0.2.130 on `PATH` (download the prebuilt release binary, or build
on an MSVC toolchain), or pass it via `WASM_BINDGEN`. If you bump the
`wasm-bindgen` crate, install the CLI of the **same** version.

## 4. What's verified green

- `cargo test -p beacon-core --no-default-features` — 112 tests.
- `cargo clippy --all-targets` (default and `--no-default-features`) — clean;
  `beacon-js` clippy (wasm target) — clean.
- Full `pytest` in strict snapshot-check mode — 762 passed, 2 skipped.
- `ruff check` — clean.
- `beacon-js`: Node (ESM) smoke and a browser smoke both pass.
- Cross-language golden corpus (`tests/test_parity_js.py`) — 28 cases,
  byte-identical Python vs JavaScript.
- `cargo publish -p beacon-core --dry-run` and `npm pack` — clean.

## 5. Not done here (by design)

- No commits, no branches, no pull requests — you commit everything.
- No real publishes to crates.io, PyPI or npm.

The npm package build **is** wired into CI: the `js` job in
`.github/workflows/ci.yml` installs the prebuilt `wasm-bindgen` CLI (pinned to
`0.2.130`, matching the crate), runs `node crates/beacon-js/build.mjs`, the Node
ESM smoke test, and the `tests/test_parity_js.py` corpus against a freshly built
wheel, and clippy-checks `beacon-js` on the wasm target (that crate is
`exclude`d from the workspace, so the `rust` job never sees it). If you bump the
`wasm-bindgen` crate, bump the `wasm-bindgen-cli@<version>` in that job to match.
