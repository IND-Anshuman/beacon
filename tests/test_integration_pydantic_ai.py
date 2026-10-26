from __future__ import annotations

import pytest
from pydantic import BaseModel

from beacon import SchemaValidationError
from beacon.integrations.pydantic_ai import BeaconValidator


class Intent(BaseModel):
    intent: str
    confidence: float


INTENT_SCHEMA = {
    "type": "object",
    "properties": {"intent": {"enum": ["cancel", "refund"]}, "confidence": {"type": "number", "maximum": 1}},
    "required": ["intent", "confidence"],
}


def test_model_instances_pass_through() -> None:
    v = BeaconValidator(Intent)
    out = Intent(intent="cancel", confidence=0.4)
    assert v(out) is out


def test_text_output_is_parsed() -> None:
    v = BeaconValidator(Intent)
    assert v('Sure: {"intent": "cancel", "confidence": 0.4}') == Intent(intent="cancel", confidence=0.4)


def test_extra_constraints_from_a_schema() -> None:
    v = BeaconValidator(INTENT_SCHEMA, retry=False)
    with pytest.raises(SchemaValidationError) as exc:
        v({"intent": "explode", "confidence": 3})
    assert [e["keyword"] for e in exc.value.errors] == ["enum", "maximum"]


def test_model_retry_when_pydantic_ai_installed() -> None:
    pai = pytest.importorskip("pydantic_ai")
    v = BeaconValidator(INTENT_SCHEMA)
    with pytest.raises(pai.ModelRetry) as exc:
        v({"intent": "explode", "confidence": 0.5})
    assert '"explode" is not one of ["cancel", "refund"]' in str(exc.value)


def test_agent_round_trip_with_test_model() -> None:
    pai = pytest.importorskip("pydantic_ai")
    from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    replies = iter(['{"intent": "explode", "confidence": 0.5}', '{"intent": "cancel", "confidence": 0.5}'])

    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(next(replies))])

    agent = pai.Agent(FunctionModel(model), output_type=str)
    agent.output_validator(BeaconValidator(INTENT_SCHEMA))
    result = agent.run_sync("I want to cancel")
    assert result.output == {"intent": "cancel", "confidence": 0.5}
