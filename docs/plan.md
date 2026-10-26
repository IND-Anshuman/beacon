# beacon v0.1 — implementation plan (revised)

> beacon is the deterministic layer between your Python code and your LLM.
> Drop-in building blocks for prompt templating, structured output parsing,
> retry classification, output validation, and snapshot-based testing — same
> input, same output, every time.

This is the working plan the v0.1 code was built against. It follows the
original project brief, with the changes listed in **Deviations from the
original brief** below. Each deviation exists because the original version
conflicted with the determinism contract, with the real API of a dependency,
or with the toolchain available in late 2026.

## Architecture

```
            Python user code
                   │
   beacon (python/beacon)  ── thin, typed wrappers, Pipeline/Block,
                   │          snapshots, retry policy, integrations
                   │
   beacon._beacon_native   ── PyO3 0.30 bindings (src/lib.rs)
                   │
   pure-Rust core (src/*.rs) ── no pyo3 types, unit-tested with
                                `cargo test --no-default-features`
```

* The Rust core never touches Python objects. Every block takes and returns
  plain Rust data (`Value`, `String`, structs) and reports failures as a
  `BlockError { kind, code, message, position }`.
* `src/lib.rs` (behind the default `python` cargo feature) converts between
  Python objects and core types and raises the Python exception classes defined
  in `beacon/errors.py`.
* No block reads environment variables, the clock, the locale, or global
  mutable state. Regexes are compiled once (pure, result-independent).

## The blocks

| Block | Rust module | Python entry point |
| --- | --- | --- |
| template | `template.rs` | `beacon.template`, `beacon.template_variables` |
| extract_json | `extract_json.rs` + `json.rs` | `beacon.extract_json`, `beacon.extract_json_detailed` |
| parse_tool_call | `parse_tool_call.rs` | `beacon.parse_tool_call`, `beacon.parse_tool_calls` |
| validate_schema | `validate_schema.rs` | `beacon.validate_schema`, `beacon.schema_errors` |
| normalize | `normalize.rs` | `beacon.normalize` |
| hash_content | `hash.rs` | `beacon.hash_content` |
| redact | `redact.rs` | `beacon.redact`, `beacon.detect_pii` |
| retry | `retry.rs` | `beacon.retry.classify`, `beacon.retry.backoff_delay`, `beacon.retry.call` |

Settled design questions (the brief's Q1–Q5):

1. **Multiple JSON values** — `select="first"` by default; `"last"`,
   `"largest"`, `"only"` (raise if more than one) are available.
2. **Template escaping** — on by default (`escape="xml"` escapes `& < >` so
   user input cannot close a `</tag>`); `{name!raw}` opts a single variable out;
   `escape="none"` / `"json"` are available. Substitution is single-pass, so
   values are never re-expanded.
3. **Coercion** — never. `"42"` does not satisfy `{"type": "number"}`.
4. **redact vs detect** — two functions: `redact()` and `detect_pii()`.
5. **Streaming tool calls** — not in v0.1.

## Deviations from the original brief

| Brief said | v0.1 does | Why |
| --- | --- | --- |
| `jsonschema` crate for validation | Own validator for the JSON Schema subset LLM apps use (incl. `$ref`/`$defs`, `anyOf`, Pydantic output) | Error text and error order are part of the contract. A third-party crate can change both in any release; owning the validator makes them ours to version. Unsupported keywords raise `SchemaError` instead of being silently ignored. |
| `serde_json` for parsing LLM output | Own strict RFC 8259 parser (`json.rs`) | Same reason (stable error messages), plus code-point positions for Python, exact big integers, and a hard nesting limit so malformed input can never crash the interpreter. `serde_json` is kept as a dev-dependency only. |
| Python sources in `src/python/` | `python/beacon/` (maturin mixed layout) | Standard maturin layout; keeps Rust `src/` Rust-only. |
| `beaconPromptTemplate`, `beaconValidator`, … | `BeaconPromptTemplate`, `BeaconValidator`, … | PEP 8 class names. |
| Pydantic AI `Agent(result_validator=...)` | `agent.output_validator(BeaconValidator(Model))` | That keyword does not exist in Pydantic AI; output validators are registered with the decorator, and failures raise `ModelRetry`. |
| `template(..., strict=True)` opt-in | `strict=True` is the default | The brief recommends strict mode and lists "don't silently fix" as a pitfall; a missing variable rendering as `{name}` is a silent fix. |
| "Exponential backoff with jitter" | Jitter derived from `blake3(jitter_key, attempt)`; delays computed in integer milliseconds | Random jitter breaks "same input → same output". |
| Python 3.9–3.13 | Python 3.10–3.14 (abi3 wheel, `abi3-py310`) | 3.9 reached end-of-life in Oct 2025; 3.14 is current. |
| `pyo3 = "0.30"` with `extension-module` | `pyo3 = "0.30"`, no `extension-module` feature | Deprecated in PyO3 0.30; maturin ≥ 1.9.4 handles linking. |
| `once_cell`, `parking_lot` | `std::sync::LazyLock`; no locks | Both are in std now; blocks hold no shared mutable state, so no locks are needed. |
| `unicode-normalization` not listed | Added | `normalize()` needs NFC/NFKC/NFD/NFKD; the crate pins a Unicode version, which keeps output stable. |
| `extract_json("No JSON")` returns `None` "or raises" | Raises `NoJSONFoundError` by default; `required=False` returns `None` | Fail loudly by default. |
| Snapshot format "YAML or JSON" | YAML written by beacon's own canonical emitter; comparison is byte-equality of the canonical text | No YAML parser is needed at test time, so there is no PyYAML-version drift; diffs are readable in PRs. Files are always LF (+ `.gitattributes`). |
| `pip install beacon` | Distribution name `llm-beacon` (`pip install llm-beacon`) | `beacon` is taken on PyPI. The import name stays `beacon`. |

## Exceptions

```
BeaconError
├── MalformedOutputError (ValueError)    code, position, line, column
│   ├── NoJSONFoundError
│   └── NoToolCallFoundError
├── SchemaValidationError (ValueError)   errors=[{path, keyword, message}]
├── SchemaError (ValueError)             the schema itself is invalid/unsupported
├── TemplateError (ValueError)
│   ├── TemplateSyntaxError              position
│   ├── MissingVariableError             names
│   └── ExtraVariableError               names
└── SnapshotMismatchError (AssertionError)
```

Every error carries a stable `code` (e.g. `json.unterminated_string`). Codes and
message templates are listed in `docs/blocks_reference.md` and snapshot-tested.

## Snapshot framework

* `assert_snapshot(name, value, *, input=None, schema=None)` (alias
  `snapshot_test`) and a pytest `snapshot` fixture.
* Modes: `new` (write missing, fail on mismatch — local default), `check` (fail
  on missing or mismatch — default when `CI` is set), `update` (rewrite).
  Selected by `--beacon-snapshot=…`, `BEACON_SNAPSHOT_MODE`, or `configure()`.
  These knobs only affect the test harness, never block output.
* CLI: `python -m beacon.snapshots update|check [pytest args]`.
* Snapshot location: `beacon_snapshot_dir` ini option (this repo: `snapshots/`),
  else `<test file dir>/snapshots/`.

## Integrations (all optional extras, all import-guarded)

| Integration | Public API |
| --- | --- |
| OpenAI SDK | `validated_completion`, `avalidated_completion`, `validated_tool_call` |
| LangChain | `BeaconPromptTemplate`, `BeaconJsonOutputParser`, `BeaconCallbackHandler` |
| Pydantic AI | `BeaconValidator` |
| LlamaIndex | `BeaconOutputParser` |
| DSPy | `BeaconJSONAdapter`, `BeaconValidateSchema` |

Each integration has a fake-client test that always runs and real-library tests
that run when the library is installed.

## Build phases (as executed)

1. Scaffolding: Cargo + maturin mixed project, exception hierarchy, CI.
2. Core blocks in Rust in dependency order: normalize → hash → json parser →
   extract_json → validate_schema → template → redact → parse_tool_call → retry.
3. Python layer: typed wrappers, `Pipeline`/`Block`, `retry` policy helpers.
4. Snapshot framework + pytest plugin + CLI.
5. Integrations.
6. Tests (Rust unit + pytest + ≥100 snapshot files), benchmark, docs, examples.

## Definition of done (v0.1)

- [x] All 8 blocks in Rust; no `unwrap()`/`expect()`/`panic!` outside tests (enforced by clippy)
- [x] `cargo clippy --all-targets -- -D warnings` clean, `cargo test` green
- [x] pytest green; ≥100 snapshot files under `snapshots/`
- [x] Snapshot framework with pytest plugin and CLI
- [x] Five integrations with tests
- [x] `docs/determinism_guarantees.md`, `docs/blocks_reference.md`, quickstart, integrations, snapshot docs
- [x] Benchmark proving < 0.5 ms per block call on typical inputs
- [ ] Cross-platform CI green (workflow written; needs a GitHub push to run)
- [ ] Published to PyPI as `llm-beacon`
