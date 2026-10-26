"""Pydantic AI: beacon as an output validator, with precise retry feedback.

Runs offline with Pydantic AI's FunctionModel. The fake model first answers
with an out-of-range intent; beacon's validator raises ModelRetry with a stable
message and the "model" corrects itself.
Requires: pip install "llm-beacon[pydantic-ai]"
"""

from __future__ import annotations

from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from beacon.integrations.pydantic_ai import BeaconValidator

INTENT = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": ["cancel", "refund", "question"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["intent", "confidence"],
}


def fake_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    if len(messages) == 1:  # first attempt
        return ModelResponse(parts=[TextPart('{"intent": "unsubscribe", "confidence": 0.8}')])
    # On retry, the last request carries the validator's feedback.
    feedback = messages[-1].parts[-1]
    print("feedback the model received:", getattr(feedback, "content", feedback))
    return ModelResponse(parts=[TextPart('```json\n{"intent": "cancel", "confidence": 0.8}\n```')])


agent = Agent(FunctionModel(fake_model), output_type=str)
agent.output_validator(BeaconValidator(INTENT))

result = agent.run_sync("Please stop my subscription")
print(result.output)
