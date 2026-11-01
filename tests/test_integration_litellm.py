from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from beacon import MalformedOutputError, SchemaValidationError
from beacon.integrations.litellm import (
    avalidated_completion,
    response_text,
    validated_completion,
    validated_tool_call,
)

SCHEMA = {"type": "object", "properties": {"intent": {"type": "string"}}, "required": ["intent"]}


def completion(content: Any = None, tool_calls: Any = None) -> SimpleNamespace:
    """A LiteLLM ModelResponse is OpenAI-shaped."""
    message = SimpleNamespace(content=content, tool_calls=tool_calls, refusal=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeCompletion:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.response


class FakeACompletion(FakeCompletion):
    async def __call__(self, **kwargs: Any) -> Any:  # type: ignore[override]
        self.calls.append(kwargs)
        return self.response


def test_validated_completion_forwards_kwargs_and_returns_dict() -> None:
    fake = FakeCompletion(completion('```json\n{"intent": "cancel"}\n```'))
    result = validated_completion(
        completion=fake, model="anthropic/claude-3-5-sonnet", messages=[{"role": "user", "content": "hi"}], schema=SCHEMA
    )
    assert result == {"intent": "cancel"}
    assert fake.calls == [{"model": "anthropic/claude-3-5-sonnet", "messages": [{"role": "user", "content": "hi"}]}]


def test_schema_violation_and_malformed_attach_raw() -> None:
    with pytest.raises(SchemaValidationError) as exc:
        validated_completion(completion=FakeCompletion(completion('{"other": 1}')), model="m", messages=[], schema=SCHEMA)
    assert exc.value.raw == '{"other": 1}'
    with pytest.raises(MalformedOutputError):
        validated_completion(completion=FakeCompletion(completion("no json here")), model="m", messages=[])


def test_output_model() -> None:
    pydantic = pytest.importorskip("pydantic")

    class Intent(pydantic.BaseModel):
        intent: str

    result = validated_completion(
        completion=FakeCompletion(completion('{"intent": "refund"}')), model="m", messages=[], output_model=Intent
    )
    assert isinstance(result, Intent) and result.intent == "refund"


def test_async_completion() -> None:
    fake = FakeACompletion(completion('{"intent": "cancel"}'))
    result = asyncio.run(avalidated_completion(acompletion=fake, model="m", messages=[], schema=SCHEMA))
    assert result == {"intent": "cancel"}


def test_native_tool_calls_reuse_openai_shape() -> None:
    call = SimpleNamespace(function=SimpleNamespace(name="search", arguments='{"q": "rust"}'))
    response = completion(None, tool_calls=[call])
    assert validated_tool_call(response) == [{"name": "search", "arguments": {"q": "rust"}}]


def test_response_text() -> None:
    assert response_text(completion("hello")) == "hello"


def test_missing_litellm_is_a_clear_error() -> None:
    import importlib.util

    if importlib.util.find_spec("litellm") is not None:
        pytest.skip("litellm is installed; the ImportError path cannot be exercised")
    with pytest.raises(ImportError, match=r"llm-beacon\[litellm\]"):
        validated_completion(model="m", messages=[])
