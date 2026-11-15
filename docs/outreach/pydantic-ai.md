# Validating outputs with beacon

[beacon](https://github.com/IND-Anshuman/beacon) is a library of deterministic
building blocks for LLM pipelines — same input, byte-identical output, error
messages included. Its Pydantic AI integration is an **output validator** that
checks model output against a schema and, on failure, raises `ModelRetry` with a
stable, identical message — so the agent re-asks the model with precise feedback.

## Install

```bash
pip install "llm-beacon[pydantic-ai]"
```

## Minimal example

```python
from pydantic import BaseModel
from pydantic_ai import Agent
from beacon.integrations.pydantic_ai import BeaconValidator

class Intent(BaseModel):
    intent: str
    confidence: float

agent = Agent("openai:gpt-4o", output_type=Intent)
agent.output_validator(BeaconValidator(Intent))
```

Pydantic AI registers output validators with the `output_validator` decorator or
method — there is no `result_validator=` keyword.

## Stricter than the model allows

Pass a JSON Schema with constraints your model class doesn't express (enums,
bounds). For an `output_type=str` agent, beacon extracts and validates the JSON
from the text:

```python
INTENT = {
    "type": "object",
    "properties": {"intent": {"enum": ["cancel", "refund", "question"]},
                   "confidence": {"type": "number"}},
    "required": ["intent", "confidence"],
}
agent = Agent("openai:gpt-4o", output_type=str)
agent.output_validator(BeaconValidator(INTENT))

# If the model answers {"intent": "unsubscribe", ...}, it is re-prompted with:
#   1 schema violation:
#     - /intent: "unsubscribe" is not one of ["cancel", "refund", "question"]
```

Because the feedback message is deterministic, the same mistake always produces
the same retry prompt — reproducible agent behaviour, and snapshot-testable.
`BeaconValidator(...).validate(output)` runs the same checks without the
`ModelRetry` translation (handy in tests; works without Pydantic AI installed).

Full reference: <https://www.anshumanbuilds.dev/beacon/integrations/pydantic-ai/>.
