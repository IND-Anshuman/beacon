# beacon

[![PyPI version](https://img.shields.io/pypi/v/llm-beacon.svg)](https://pypi.org/project/llm-beacon/)
[![Downloads](https://img.shields.io/pypi/dm/llm-beacon.svg)](https://pypistats.org/packages/llm-beacon)
[![Python versions](https://img.shields.io/pypi/pyversions/llm-beacon.svg)](https://pypi.org/project/llm-beacon/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Rust](https://img.shields.io/badge/core-Rust-orange.svg)](https://www.rust-lang.org/)

> Deterministic, tested building blocks for AI pipelines.

Every block in beacon is a pure function with the same contract:
**same input → same output, every time, on every machine.**

Stop debugging why your pipeline gave a different result yesterday.

**[Documentation](https://www.anshumanbuilds.dev/beacon/)** · **[Playground](https://www.anshumanbuilds.dev/beacon/playground/)** · **[PyPI](https://pypi.org/project/llm-beacon/)** · **[GitHub](https://github.com/IND-Anshuman/beacon)**

beacon is the layer between your Python code and your LLM: prompt templating,
JSON extraction, tool-call parsing, schema validation, text normalization,
content hashing, PII redaction, retry classification, and snapshot testing.
The blocks are written in Rust (via [PyO3](https://github.com/PyO3/pyo3)).
They have strict contracts and stable error messages, and they never silently
"fix" your data.

## Install

```bash
pip install llm-beacon
```

The PyPI package is `llm-beacon`; the import name is `beacon`.

Python 3.10–3.14. Wheels are abi3, so one wheel per platform covers every
supported Python version. Integrations are optional extras:
`pip install "llm-beacon[langchain]"`, `[llamaindex]`, `[pydantic-ai]`, `[dspy]`,
`[openai]`.

## Quickstart

```python
from beacon import template, extract_json, validate_schema

# 1. Render a prompt deterministically (user input is XML-escaped by default)
prompt = template(
    "Extract the user's intent as JSON.\n<message>{message}</message>",
    message="I want to cancel my subscription",
)

# 2. Call your LLM (any client)
raw_response = llm.complete(prompt)
# e.g. 'Sure! ```json\n{"intent": "cancel", "confidence": 0.93}\n```'

# 3. Extract JSON from prose, fences, or both; malformed JSON raises
result = extract_json(raw_response)

# 4. Validate against a schema. Fails loudly, never coerces.
schema = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": ["cancel", "refund", "question"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["intent", "confidence"],
}
validate_schema(result, schema)
```

When something is wrong, the error tells you where:

```python
>>> extract_json('The user wants to {"intent": cancel')
MalformedOutputError: expected a JSON value, found 'c' (line 1, column 30)
>>> validate_schema({"intent": "explode", "confidence": 1.5}, schema)
SchemaValidationError: 2 schema violations:
  - /intent: "explode" is not one of ["cancel", "refund", "question"]
  - /confidence: 1.5 is greater than the maximum of 1
```

## The blocks

| Block | What it does |
| --- | --- |
| `template(source, **vars)` | `{name}` substitution, single pass, strict about missing/unused variables, XML-escapes values by default (`{name!raw}` to opt out) |
| `extract_json(text)` | Finds the JSON in fenced or prose-wrapped output; strict RFC 8259; `select=`/`kind=` for multiple values; errors include a position |
| `parse_tool_call(text)` | Hermes `<tool_call>`, Mistral `[TOOL_CALLS]`, Llama `<\|python_tag\|>`, `[TOOL_CALL]`, XML `<invoke>`, OpenAI/Anthropic JSON, `name(k=v)` |
| `validate_schema(value, schema)` | JSON Schema (incl. `$ref`, `anyOf`, Pydantic output). All violations come back in a fixed order with stable messages |
| `normalize(text)` | NFKC, whitespace collapsing, zero-width/control removal, optional accent stripping and lowercasing |
| `hash_content(value)` | BLAKE3 over a type-tagged canonical encoding; dict key order never matters |
| `redact(text)` / `detect_pii(text)` | Emails, phones, SSNs, Luhn-checked cards, API keys, JWTs, private keys, IPs, plus your own patterns and terms |
| `retry.classify(exc)` | Retry or fail, with a reason and a backoff delay. Jitter is deterministic, so the same failures give the same delays |

Full reference: [docs/blocks_reference.md](docs/blocks_reference.md).

## Pipelines

```python
from beacon import Block, Pipeline, extract_json, template

class ExtractIntent(Block):
    def __init__(self, llm):
        self.llm = llm

    def run(self, message: str) -> dict:
        prompt = template("Extract the intent from: <m>{message}</m>", message=message)
        return extract_json(self.llm(prompt), schema=INTENT_SCHEMA)

pipeline = Pipeline([ExtractIntent(llm), route_intent, format_reply])
pipeline.run("I want to cancel")
pipeline.run_traced("I want to cancel").trace()  # content hashes for each step
```

## Snapshot testing

Most LLM apps have no tests because the model's output isn't deterministic.
Everything *around* the model is, though. Record a model response once, then
snapshot what your code does with it:

```python
from beacon import extract_json
from beacon.snapshots import assert_snapshot

def test_cancel_intent():
    raw = open("fixtures/cancel.txt").read()       # recorded LLM response
    assert_snapshot("intents/cancel", extract_json(raw), input=raw, schema=INTENT_SCHEMA)
```

The first run writes `snapshots/intents/cancel.yaml`. Every later run compares
against it byte for byte and shows a diff if anything changed. CI (where
`CI` is set) fails on missing snapshots. When a change is intended:

```bash
python -m beacon.snapshots update
```

There's also a pytest `snapshot` fixture. See
[docs/snapshot_testing.md](docs/snapshot_testing.md).

## Integrations

| Framework | API |
| --- | --- |
| OpenAI SDK | `validated_completion`, `avalidated_completion`, `validated_tool_call` |
| LangChain | `BeaconPromptTemplate`, `BeaconJsonOutputParser`, `BeaconCallbackHandler` |
| LlamaIndex | `BeaconOutputParser` |
| Pydantic AI | `BeaconValidator` (`agent.output_validator(BeaconValidator(Model))`) |
| DSPy | `BeaconJSONAdapter`, `BeaconValidateSchema` |

See [docs/integrations.md](docs/integrations.md).

## Determinism guarantees

Pure functions, stable across runs, machines, and minor versions. Error
messages are part of the contract. All configuration is explicit, with no
environment variables or global flags. The full contract is in
[docs/determinism_guarantees.md](docs/determinism_guarantees.md).

## Development

```bash
git clone https://github.com/IND-Anshuman/beacon.git && cd beacon
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install maturin pytest pyyaml
maturin develop
pytest                                   # Python tests + snapshot tests
cargo test --no-default-features         # Rust core tests (no Python needed)
cargo clippy --all-targets -- -D warnings
python benches/determinism_overhead.py   # per-call overhead
```

## License

MIT
