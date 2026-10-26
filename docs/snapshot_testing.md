# Snapshot testing

LLM output isn't deterministic, but your code's handling of a *given* output
is. Record a model response once and snapshot what your parsing, validation
and post-processing do with it. You get regression tests for the part of the
app you actually control.

## API

```python
from beacon.snapshots import assert_snapshot   # alias: snapshot_test

assert_snapshot(name, value, *, input=..., schema=None, directory=None, mode=None)
```

* `name`: path-like id; `"intents/cancel"` → `snapshots/intents/cancel.yaml`.
  Use letters, digits, `_ - .` and `/`. Segments can't start with `.`.
* `value`: JSON-like data. Dataclasses, Pydantic models, enums, sets (sorted),
  bytes and **exceptions** (type, code, message, position) are converted
  automatically, so you can snapshot error behaviour too.
* `input`: recorded next to the value so the file explains itself.
* `schema`: the validation outcome is recorded as well.

pytest fixture (registered automatically):

```python
def test_something(snapshot):
    snapshot(result)                      # -> snapshots/<module>/<test>.yaml
    snapshot(other, name="custom/name")   # explicit name
```

Without a name, a second call in the same test gets a `-2` suffix, and so on.

## File format

```yaml
# beacon snapshot v1 — regenerate with: python -m beacon.snapshots update
name: extract_json/markdown_fence_basic
input: |-
  Here's the answer:
  ```json
  {"intent": "cancel", "confidence": 0.9}
  ```
value:
  intent: cancel
  confidence: 0.9
schema_validation:
  passed: true
  errors: []
```

Snapshots are written by beacon's own canonical YAML emitter and compared
**byte for byte**. No YAML parser runs at test time, so a PyYAML upgrade
can't change results. Mapping keys keep insertion order, which is itself
behaviour worth catching: `extract_json` preserves the model's key order. Files
are UTF-8 with LF line endings. Add this to `.gitattributes` so Windows
checkouts don't rewrite them:

```
snapshots/** text eol=lf
```

(CRLF checkouts are tolerated when comparing, but LF is what gets written.)

## Modes

| Mode | Missing snapshot | Different snapshot |
| --- | --- | --- |
| `new` (local default) | written, test passes | test fails with a diff |
| `check` (default when `CI` is set) | test fails | test fails with a diff |
| `update` | written | rewritten |

The first match wins:

1. `mode=` argument, or `beacon.snapshots.configure(mode=...)`
2. `pytest --beacon-snapshot=new|check|update`
3. `BEACON_SNAPSHOT_MODE` environment variable
4. `check` if `CI` is set to anything except `0`/`false`/`no`, else `new`

These only control what the test harness does with files. Block output never
depends on them.

## Where snapshots live

1. `directory=` argument / `configure(directory=...)`
2. `beacon_snapshot_dir` in pytest config (relative to the rootdir):

   ```toml
   [tool.pytest.ini_options]
   beacon_snapshot_dir = "snapshots"
   ```
3. Otherwise `snapshots/` next to the test file.

## CLI

```bash
python -m beacon.snapshots update [pytest args...]   # accept changes
python -m beacon.snapshots check  [pytest args...]   # what CI does
```

## Testing your own app

```python
import json
from pathlib import Path

from beacon.snapshots import assert_snapshot
from myapp.pipeline import build_pipeline

FIXTURES = Path(__file__).parent / "fixtures"

def fake_llm(responses):
    it = iter(responses)
    return lambda prompt: next(it)

def test_refund_flow():
    recorded = json.loads((FIXTURES / "refund_session.json").read_text())
    pipeline = build_pipeline(llm=fake_llm(recorded["responses"]))
    result = pipeline.run_traced(recorded["user_message"])
    assert_snapshot("flows/refund", {"output": result.output, "trace": result.trace()})
```

A runnable version is in `examples/08_snapshot_testing_your_app.py`.

## Tips

* Snapshot **errors** as well as successes. A changed error message is a
  behaviour change, since it may be what you feed back to the model.
* Prefer small, named snapshots over one large blob. Diffs stay readable.
* When a snapshot changes, read the diff before running `update`.
