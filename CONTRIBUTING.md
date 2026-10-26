# Contributing to beacon

Thanks for helping. Issues and pull requests go to
[IND-Anshuman/beacon](https://github.com/IND-Anshuman/beacon).

beacon's value is its contract: same input, same output, on every machine,
across versions. Every change is reviewed against
[docs/determinism_guarantees.md](docs/determinism_guarantees.md).

## Setup

```bash
git clone https://github.com/IND-Anshuman/beacon.git && cd beacon
python -m venv .venv
. .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install maturin pytest pyyaml pydantic
maturin develop                   # builds the Rust extension into the venv
pytest
cargo test --no-default-features  # pure-Rust core, no Python needed
```

Optional, for the integration tests:
`pip install langchain-core llama-index-core pydantic-ai-slim dspy openai`.

### Windows without Visual Studio Build Tools

The default Rust target on Windows (`x86_64-pc-windows-msvc`) needs the MSVC
linker. If you don't have it, the GNU toolchain works for local development:

```bash
rustup toolchain install stable-x86_64-pc-windows-gnu
rustup override set stable-x86_64-pc-windows-gnu
# PyO3's raw-dylib linking needs binutils' `as`, which the GNU toolchain lacks;
# link against the Python DLL directly instead:
export PYO3_USE_RAW_DYLIB=0
export RUSTFLAGS="-L native=<path to your Python install dir containing python3.dll>"
maturin develop
```

## Rules for changes

1. **No hidden inputs.** Blocks never read the clock, environment variables,
   the locale, files or the network, and they keep no state between calls.
   Every option is an explicit parameter.
2. **No `unwrap()`/`expect()`/`panic!` in non-test Rust code.** A panic kills
   the user's Python process. Clippy enforces this (`cargo clippy
   --all-targets -- -D warnings`).
3. **Never repair input silently.** Strict parsing, explicit errors.
4. **Error messages are API.** Don't change a message or `code` in a patch
   release. New errors and new messages go in a minor release, listed under
   "Behaviour changes" in `CHANGELOG.md`, and are added to the error code
   table in `docs/blocks_reference.md`.
5. **Snapshot changes need justification.** If `pytest` reports a snapshot
   diff, read it. If the change is intended, run
   `python -m beacon.snapshots update`, commit the updated `.yaml` files, and
   explain the change in the PR.
6. **Positions are code points.** Anything reported to Python as an offset
   counts Unicode code points, not bytes.
7. **Tests with every change.** Add unit tests and, for new behaviour, a
   snapshot case in the block's corpus.

## Layout

```
src/            Rust core (pure; no pyo3 types) + src/lib.rs, src/convert.rs (bindings)
python/beacon/  Python package: wrappers, errors, Pipeline, snapshots, integrations
tests/          pytest suite (unit + snapshot corpora + integrations)
snapshots/      golden files, compared byte for byte in CI on Linux/macOS/Windows
benches/        per-block overhead benchmark (< 0.5 ms budget)
examples/       runnable examples (offline, fake models)
docs/           user documentation and the determinism contract
```
