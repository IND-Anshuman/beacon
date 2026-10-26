from __future__ import annotations

from typing import Literal

import pytest

from beacon import SchemaValidationError
from beacon.integrations.dspy import BeaconValidateSchema

dspy = pytest.importorskip("dspy")

from beacon.integrations.dspy import BeaconJSONAdapter  # noqa: E402


class IntentSignature(dspy.Signature):
    """Extract user intent from a message."""

    message: str = dspy.InputField()
    intent: Literal["cancel", "refund", "question"] = dspy.OutputField()
    confidence: float = dspy.OutputField()


def test_adapter_parses_fenced_json() -> None:
    adapter = BeaconJSONAdapter()
    out = adapter.parse(IntentSignature, 'Reasoning...\n```json\n{"intent": "cancel", "confidence": 0.9}\n```')
    assert out == {"intent": "cancel", "confidence": 0.9}


def test_adapter_rejects_malformed_and_missing_fields() -> None:
    from dspy.utils.exceptions import AdapterParseError

    adapter = BeaconJSONAdapter()
    with pytest.raises(AdapterParseError) as exc:
        adapter.parse(IntentSignature, '{"intent": "cancel", "confidence": ')
    assert "unexpected end of input" in str(exc.value)
    with pytest.raises(AdapterParseError, match="missing output fields: confidence"):
        adapter.parse(IntentSignature, '{"intent": "cancel"}')


def test_validator_with_signature() -> None:
    validate = BeaconValidateSchema(IntentSignature)
    pred = dspy.Prediction(intent="cancel", confidence=0.4)
    assert validate(pred) is pred
    with pytest.raises(SchemaValidationError) as exc:
        validate(dspy.Prediction(intent="explode", confidence="high"))
    assert [e["path"] for e in exc.value.errors] == ["/intent", "/confidence"]


def test_validator_with_schema_mapping_and_dicts() -> None:
    validate = BeaconValidateSchema({"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]})
    assert validate({"n": 1}) == {"n": 1}
    with pytest.raises(SchemaValidationError):
        validate({"n": "1"})


def test_module_pipeline_with_dummy_lm() -> None:
    from dspy.utils.dummies import DummyLM

    lm = DummyLM([{"intent": "refund", "confidence": 0.8}], adapter=BeaconJSONAdapter())

    class IntentModule(dspy.Module):
        def __init__(self) -> None:
            super().__init__()
            self.extract = dspy.Predict(IntentSignature)
            self.validate = BeaconValidateSchema(IntentSignature)

        def forward(self, message: str) -> object:
            return self.validate(self.extract(message=message))

    with dspy.context(lm=lm, adapter=BeaconJSONAdapter()):
        result = IntentModule()(message="I want my money back")
    assert (result.intent, result.confidence) == ("refund", 0.8)
