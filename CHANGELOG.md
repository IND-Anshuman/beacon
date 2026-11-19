# Changelog

All notable changes to beacon are documented here. beacon follows semantic
versioning, with the extra compatibility rules in
[docs/determinism_guarantees.md](docs/determinism_guarantees.md): patch
releases never change block output, including error messages.

Each release lists **Behaviour changes** separately. Those are any
input whose output differs from the previous release.

## [Unreleased] - v2.0 Pillars A, B, C & D (verifiable + streaming + bindings + conformance)

The first v2.0 pillars, and the developer-experience pass. Purely additive —
no existing block output, error code or message changed. (Version number to be
assigned by the maintainer; suggested minor bump, e.g. `1.2.0`.)

### Added

- **Provenance ledger** — `Pipeline.run_recorded` / `arun_recorded` emit a
  tamper-evident `Ledger` (a `hash_content` chain of per-block records), and
  `beacon.verify` (plus `beacon.aio.verify`) checks it offline: chain integrity
  always, and full output reproduction when given the pipeline and inputs. No
  model, no network. New public types: `Ledger`, `LedgerRecord`,
  `RecordedResult`, `VerifyReport`. Non-deterministic data (timestamps, host)
  lives in `Ledger.meta`, outside the hashed content. Records what the
  deterministic boundary did — not an evaluation of the model.
- **Streaming engine** — `StreamParser` (and the `stream_json` /
  `beacon.aio.stream_json` generators) drive `parse_partial` incrementally over
  a growing stream, emitting committed top-level items (array elements, object
  members, or a final scalar) the moment each settles. The headline property is
  **chunk-boundary invariance** — the same bytes, split any way, yield the same
  items and final value — fuzz-tested over arbitrary JSON. New public types:
  `StreamParser`, `StreamUpdate`.
- **Streaming redaction** — `StreamRedactor` / `stream_redact` /
  `beacon.aio.stream_redact` redact a text stream so that a secret is never
  emitted across a chunk boundary; the concatenated output equals `redact` of
  the whole text, for any split (fuzz-tested). Holds secrets up to
  `max_secret_len` (default 1024) across a boundary.
- **Streaming tool-call detection** — `StreamToolCalls` / `stream_tool_calls` /
  `beacon.aio.stream_tool_calls` emit each tool call (any recognized format) the
  moment it finishes parsing; the yielded calls equal `parse_tool_calls` of the
  whole text, in order, for any chunking (fuzz-tested).
- **Cross-language conformance** — a single language-neutral golden corpus
  (`tests/conformance/corpus.json`, 29 cases across 15 blocks) that the Python
  wheels *and* the JavaScript/wasm package are both asserted byte-identical
  against, plus a reproducible determinism report
  (`tests/conformance/report.py`) and a docs page. Regenerate the golden
  deliberately with `python tests/conformance/generate.py`.
- **`beacon-ffi` crate** — a stable C ABI over `beacon-core` (all 15
  cross-language blocks), the FFI foundation for native bindings (Go, JVM, C).
  Returns beacon's canonical JSON text, byte-identical to the other bindings;
  thread-local error codes, a `beacon.h` header, and Rust-tested marshalling.
  Builds to a `cdylib`/`staticlib`.
- **Error diagnostics** — `BeaconError.explain()` (deterministic cause/fix/
  context), `.details()` (structured dict), and `beacon.explain_code(code)`.
- **CLI** — `beacon doctor` (versions + pinned data versions), `beacon explain
  <code>`, and a global `beacon --explain <command> …`.

### Behaviour changes

None. Additive only.

### Pinned data versions

- Unicode tables: 18.0.0 (`beacon.UNICODE_VERSION`).
- Canonical hash encoding: v1.
- Snapshot file format: v1.
- Ledger format: v1.

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
