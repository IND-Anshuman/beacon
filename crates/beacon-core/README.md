# beacon-core

Deterministic, tested building blocks for AI pipelines — the pure-Rust core of
[beacon](https://github.com/IND-Anshuman/beacon).

beacon's value is a **determinism contract**: the same input produces
byte-identical output on every machine, forever — including error messages,
which are part of the public contract. The core is pure Rust with **no clock,
RNG, locale, env, network, or model call** anywhere.

Each block sits at the boundary between model output and application code, is
provider-agnostic, and never calls or scores a model.

## Blocks

| Module | What it does |
| --- | --- |
| `extract_json` | Find and extract JSON embedded in free-form model output. |
| `repair` | Recover a usable value from malformed/truncated JSON, with a repair log. |
| `json` | beacon's own strict, position-tracking JSON parser. |
| `parse_tool_call` | Parse tool/function calls from model output, format-agnostic. |
| `validate_schema` | Validate a value against a JSON Schema subset, with stable errors. |
| `template` | Render prompts from a small, strict, escaping template language. |
| `normalize` | Unicode normalization, accent/control/zero-width stripping. |
| `hash` | Canonical, order-independent hashing of JSON-like values (BLAKE3). |
| `redact` | Detect and redact PII with a deterministic ruleset. |
| `retry` | Classify provider errors and compute deterministic backoff. |

## Usage

```rust
use beacon_core::extract_json::{extract_required, Kind, Select};

let found = extract_required(r#"Here you go: {"ok": true}"#, Select::First, Kind::Auto)?;
assert_eq!(found.value.to_json(), r#"{"ok":true}"#);
# Ok::<(), beacon_core::error::BlockError>(())
```

Bindings for Python (`llm-beacon` on PyPI, import name `beacon`), JavaScript/TypeScript
(npm), and a WebAssembly playground bridge are built on top of this crate.

## License

MIT
