# Quickstart

Five minutes from install to a tested pipeline.

## 1. Install

```bash
pip install llm-beacon
```

## 2. Render a prompt

```python
from beacon import template

prompt = template(
    "Classify the intent of the message as JSON with keys intent and confidence.\n"
    "<message>{message}</message>",
    message=user_message,
)
```

`template` refuses to render with a missing variable (`MissingVariableError`)
or an unused one (`ExtraVariableError`), and it XML-escapes values so a user
can't close `</message>` and slip instructions in after it.

## 3. Parse the response

```python
from beacon import extract_json, validate_schema

INTENT = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": ["cancel", "refund", "question"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["intent", "confidence"],
}

raw = llm(prompt)                      # any client
result = extract_json(raw, schema=INTENT)
```

`extract_json` finds the JSON in fences or prose and parses it strictly. If
the model writes a trailing comma or gets cut off mid-object, you get a
`MalformedOutputError` with the exact position rather than a silently
"repaired" guess.

## 4. Handle failures deterministically

```python
from beacon import MalformedOutputError, SchemaValidationError, retry

try:
    result = extract_json(raw, schema=INTENT)
except (MalformedOutputError, SchemaValidationError) as err:
    # err.code is stable (e.g. "json.trailing_comma"); str(err) is too, so
    # feeding it back to the model gives the same correction every time.
    result = extract_json(llm(prompt + f"\n\nYour last answer was invalid: {err}"), schema=INTENT)

decision = retry.classify(api_error, attempt=2)   # RetryDecision(action=..., delay_seconds=...)
```

## 5. Snapshot-test it

Save a real model response to `tests/fixtures/cancel.txt`, then:

```python
# tests/test_intent.py
from pathlib import Path
from beacon import extract_json
from beacon.snapshots import assert_snapshot

def test_cancel():
    raw = Path(__file__).with_name("fixtures").joinpath("cancel.txt").read_text()
    assert_snapshot("intent/cancel", extract_json(raw), input=raw, schema=INTENT)
```

```bash
pytest                                # first run writes snapshots/intent/cancel.yaml
pytest                                # later runs compare byte for byte
python -m beacon.snapshots update     # accept intended changes
```

Commit the `snapshots/` directory. Every behaviour change in your parsing
code now shows up as a reviewable diff.

## Next

* [blocks_reference.md](blocks_reference.md): every option and error code
* [snapshot_testing.md](snapshot_testing.md): modes, fixture, CI
* [integrations.md](integrations.md): LangChain, LlamaIndex, Pydantic AI, DSPy, OpenAI
* [determinism_guarantees.md](determinism_guarantees.md): the contract
