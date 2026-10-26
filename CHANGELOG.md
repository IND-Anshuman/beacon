# Changelog

All notable changes to beacon are documented here. beacon follows semantic
versioning, with the extra compatibility rules in
[docs/determinism_guarantees.md](docs/determinism_guarantees.md): patch
releases never change block output, including error messages.

Each release lists **Behaviour changes** separately. Those are any
input whose output differs from the previous release.

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
