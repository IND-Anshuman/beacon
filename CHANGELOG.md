# Changelog

All notable changes to beacon are documented here. beacon follows semantic
versioning, with the extra compatibility rules in
[docs/determinism_guarantees.md](docs/determinism_guarantees.md): patch
releases never change block output, including error messages.

Each release lists **Behaviour changes** separately. Those are any
input whose output differs from the previous release.

## [1.1.0] - unreleased

The Adoption & Launch phase: more framework adapters, problem-shaped docs and a
published benchmark. Purely additive — no existing block output, error code or
message changed.

### Added

- **Eight framework integrations** — thin, duck-typed adapters (no hard
  dependency on the framework) following the existing convention: OpenAI Agents
  SDK, smolagents, Haystack, Strands Agents, AutoGen, CrewAI, Agno and Semantic
  Kernel. Each normalizes tool calls to `{"name", "arguments"}` and/or validates
  output, with provider-prefixed error codes, plus a `pip install
  "llm-beacon[...]"` extra for each.
- **Vercel AI SDK adapter** (`llm-beacon/vercel`) — a duck-typed TypeScript
  adapter on the npm package: `validatedToolCalls`, `parseOutput` and
  `toolSchemas`, with the same behaviour and error codes as the Python adapters.
- **Recipes** — a symptom-organized documentation section (prose instead of
  JSON, truncated output, unknown tool, PII, retry storms, injection in a tool
  arg, and more), each page stating what the block does *not* do.
- **Overhead benchmark** — a docs page with the measured per-call cost of every
  block (microseconds), reproducible via `benches/determinism_overhead.py`.

### Behaviour changes

None. This release only adds adapters and documentation.

### Pinned data versions

- Unicode tables: 18.0.0 (`beacon.UNICODE_VERSION`).
- Canonical hash encoding: v1.
- Snapshot file format: v1.

## [1.0.0] - unreleased

v1.0 takes the core cross-language. The pure-Rust blocks are now a standalone,
publishable crate, and the same code ships to JavaScript/TypeScript via
WebAssembly — proven byte-identical to the Python package by a shared corpus.
No existing block output, error code or message changed.

### Added

- **`beacon-core` crate** — the pure-Rust blocks, dry-run-publishable to
  crates.io (no PyO3). The repo is now a Cargo workspace: `beacon-core`
  (core), `beacon-python` (the PyO3 `llm-beacon` wheels), `beacon-wasm` (the
  docs playground) and `beacon-js` (the npm package).
- **`parse_partial`** — parse an incomplete JSON prefix, as it streams, into
  the best value so far, reporting `complete` and `consumed`. Strict JSON
  tolerant only of truncation; no repair log. In `beacon`, `beacon.aio`, the
  CLI (`beacon partial`) and JavaScript.
- **`extract_citations`** — numeric markers (`[1]`, `[1, 2]`, `[1-3]`),
  Markdown footnotes (`[^id]`) and inline URLs, as ordered spans.
- **`detect_injection`** / **`scan_arguments`** — deterministic flag-only
  heuristics (SQL injection, shell metacharacters, path traversal, common
  prompt-injection phrases) over text and over tool-call arguments. Explicitly
  **not** a security guarantee.
- **`llm-beacon` npm package** — the full core compiled to WebAssembly with
  wasm-bindgen, with idiomatic TypeScript types; runs in Node (ESM) and the
  browser.
- A cross-language golden corpus asserting byte-identical output between the
  Python and JavaScript builds.

### Pinned data versions

- Unicode tables: 18.0.0 (`beacon.UNICODE_VERSION`).
- Canonical hash encoding: v1.
- Snapshot file format: v1.

## [0.1.0] - unreleased

First release, published on PyPI as `llm-beacon` (import name `beacon`).

### Added

- Blocks, implemented in Rust via PyO3 0.30: `template`, `template_variables`,
  `extract_json`, `extract_json_detailed`, `parse_tool_call`,
  `parse_tool_calls`, `validate_schema`, `schema_errors`, `normalize`,
  `hash_content`, `redact`, `detect_pii`, `retry.classify`,
  `retry.backoff_delay`, `retry.call`.
- `Pipeline` / `Block` composition with hash traces.
- Snapshot testing: `assert_snapshot`, pytest `snapshot` fixture,
  `--beacon-snapshot` option, `python -m beacon.snapshots update|check`.
- Integrations: OpenAI SDK, LangChain, LlamaIndex, Pydantic AI, DSPy.
- abi3 wheels for CPython 3.10+.

### Pinned data versions

- Unicode tables: 18.0.0 (`beacon.UNICODE_VERSION`).
- Canonical hash encoding: v1.
- Snapshot file format: v1.
