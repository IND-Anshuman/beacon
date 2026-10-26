"""DSPy: beacon's strict JSON adapter and a schema-validating module.

Runs offline with DSPy's DummyLM. With a real LM:

    dspy.configure(lm=dspy.LM("openai/gpt-4o"), adapter=BeaconJSONAdapter())

Because parsing and validation are deterministic, optimizer runs (e.g.
BootstrapFewShot) are evaluated against a stable parser: a metric change comes
from the prompts, never from flaky parsing.
Requires: pip install "llm-beacon[dspy]"
"""

from __future__ import annotations

from typing import Literal

import dspy
from dspy.utils.dummies import DummyLM

from beacon import SchemaValidationError
from beacon.integrations.dspy import BeaconJSONAdapter, BeaconValidateSchema


class IntentSignature(dspy.Signature):
    """Extract user intent from a message."""

    message: str = dspy.InputField()
    intent: Literal["cancel", "refund", "question"] = dspy.OutputField()
    confidence: float = dspy.OutputField()


class IntentModule(dspy.Module):
    def __init__(self) -> None:
        super().__init__()
        self.extract = dspy.Predict(IntentSignature)
        self.validate = BeaconValidateSchema(IntentSignature)

    def forward(self, message: str) -> dspy.Prediction:
        return self.validate(self.extract(message=message))


adapter = BeaconJSONAdapter()
lm = DummyLM([{"intent": "refund", "confidence": 0.82}], adapter=adapter)
with dspy.context(lm=lm, adapter=adapter):
    pred = IntentModule()(message="I want my money back")
print(pred.intent, pred.confidence)

# The adapter parses raw completions strictly:
print(adapter.parse(IntentSignature, 'Thinking...\n```json\n{"intent": "question", "confidence": 0.4}\n```'))

# The validator checks predictions against the signature's schema:
try:
    BeaconValidateSchema(IntentSignature)(dspy.Prediction(intent="explode", confidence=2))
except SchemaValidationError as err:
    print(err)
