# Deterministic parsing for DSPy with beacon

[beacon](https://github.com/IND-Anshuman/beacon) is a library of deterministic
building blocks for LLM pipelines: the same input always produces byte-identical
output. Its DSPy integration is a strict JSON adapter and a schema-validating
module — which matters for DSPy specifically, because optimizers compare metrics
across many runs, and flaky parsing is noise in that signal.

## Install

```bash
pip install "llm-beacon[dspy]"
```

## Minimal example

```python
import dspy
from typing import Literal
from beacon.integrations.dspy import BeaconJSONAdapter, BeaconValidateSchema

dspy.configure(lm=dspy.LM("openai/gpt-4o"), adapter=BeaconJSONAdapter())

class IntentSignature(dspy.Signature):
    """Extract user intent from a message."""
    message: str = dspy.InputField()
    intent: Literal["cancel", "refund", "question"] = dspy.OutputField()
    confidence: float = dspy.OutputField()

class IntentModule(dspy.Module):
    def __init__(self):
        super().__init__()
        self.extract = dspy.ChainOfThought(IntentSignature)
        self.validate = BeaconValidateSchema(IntentSignature)

    def forward(self, message):
        return self.validate(self.extract(message=message))
```

## `BeaconJSONAdapter`

A subclass of `dspy.JSONAdapter` that keeps DSPy's prompt formatting but parses
responses with beacon's strict `extract_json`:

- strict JSON only, no silent repair;
- missing or malformed fields raise DSPy's `AdapterParseError`, feeding DSPy's
  own retry and fallback logic;
- values are then converted to the field annotations by DSPy's `parse_value`.

## `BeaconValidateSchema`

Builds a JSON Schema from a signature's output fields and validates predictions
against it, raising `SchemaValidationError`. A JSON Schema mapping works too.

## Why it matters for optimization

Optimizers like `BootstrapFewShot` compare metrics across many runs. With a
deterministic parser and validator, a metric change comes from your prompts and
demos — never from parsing that happened to differ between runs.

DSPy's adapter API is internal and changes between releases; tested against DSPy
3.x. Full reference:
<https://www.anshumanbuilds.dev/beacon/integrations/dspy/>.
