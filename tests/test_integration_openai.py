from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from beacon import MalformedOutputError, NoJSONFoundError, SchemaValidationError
from beacon.integrations.openai_sdk import (
    avalidated_completion,
    response_text,
    validated_completion,
    validated_tool_call,
)

SCHEMA = {"type": "object", "properties": {"intent": {"type": "string"}}, "required": ["intent"]}


def completion(content: Any = None, tool_calls: Any = None, refusal: Any = None) -> SimpleNamespace:
    message = SimpleNamespace(content=content, tool_calls=tool_calls, refusal=refusal)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeCompletions:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.response


class FakeAsyncCompletions(FakeCompletions):
    async def create(self, **kwargs: Any) -> Any:  # type: ignore[override]
        self.calls.append(kwargs)
        return self.response


def client_for(response: Any, *, is_async: bool = False) -> SimpleNamespace:
    completions = (FakeAsyncCompletions if is_async else FakeCompletions)(response)
    return SimpleNamespace(chat=SimpleNamespace(completions=completions))


def test_validated_completion_returns_dict_and_forwards_kwargs() -> None:
    client = client_for(completion('```json\n{"intent": "cancel"}\n```'))
    result = validated_completion(client, model="gpt-4o", messages=[{"role": "user", "content": "hi"}], schema=SCHEMA)
    assert result == {"intent": "cancel"}
    assert client.chat.completions.calls == [{"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]}]


def test_schema_violation_has_raw_attached() -> None:
    client = client_for(completion('{"other": 1}'))
    with pytest.raises(SchemaValidationError) as exc:
        validated_completion(client, model="m", messages=[], schema=SCHEMA)
    assert exc.value.raw == '{"other": 1}'


def test_malformed_and_missing_json() -> None:
    with pytest.raises(MalformedOutputError) as exc:
        validated_completion(client_for(completion('{"intent": ')), model="m", messages=[])
    assert exc.value.raw == '{"intent": '
    with pytest.raises(NoJSONFoundError):
        validated_completion(client_for(completion("I cannot help")), model="m", messages=[])


def test_refusal_and_empty_content() -> None:
    with pytest.raises(MalformedOutputError) as exc:
        validated_completion(client_for(completion(None, refusal="I can't")), model="m", messages=[])
    assert exc.value.code == "openai.no_content"
    assert "refusal: I can't" in str(exc.value)


def test_output_model() -> None:
    pydantic = pytest.importorskip("pydantic")

    class Intent(pydantic.BaseModel):
        intent: str

    result = validated_completion(client_for(completion('{"intent": "refund"}')), model="m", messages=[], output_model=Intent)
    assert isinstance(result, Intent) and result.intent == "refund"


def test_async() -> None:
    client = client_for(completion('{"intent": "cancel"}'), is_async=True)
    result = asyncio.run(avalidated_completion(client, model="m", messages=[], schema=SCHEMA))
    assert result == {"intent": "cancel"}


def test_responses_api_shape_and_dicts() -> None:
    assert response_text(SimpleNamespace(output_text='{"a": 1}')) == '{"a": 1}'
    assert response_text({"choices": [{"message": {"content": "hi"}}]}) == "hi"
    custom = validated_completion(None, create=lambda **kw: SimpleNamespace(output_text='{"intent": "x"}'), input="q")
    assert custom == {"intent": "x"}


def test_native_tool_calls() -> None:
    call = SimpleNamespace(id="c1", type="function", function=SimpleNamespace(name="search", arguments='{"q": "rust"}'))
    response = completion(None, tool_calls=[call])
    assert validated_tool_call(response) == [{"name": "search", "arguments": {"q": "rust"}}]
    schemas = {"search": {"type": "object", "required": ["q", "limit"]}}
    with pytest.raises(SchemaValidationError):
        validated_tool_call(response, tool_schemas=schemas)
    with pytest.raises(MalformedOutputError) as exc:
        validated_tool_call(response, tool_schemas={"other": {}})
    assert exc.value.code == "openai.unknown_tool"


def test_native_tool_call_with_bad_arguments_json() -> None:
    call = SimpleNamespace(function=SimpleNamespace(name="search", arguments="{'q': 1}"))
    with pytest.raises(MalformedOutputError) as exc:
        validated_tool_call(completion(None, tool_calls=[call]))
    assert exc.value.code == "tool_call.invalid_arguments"


def test_text_tool_calls_fallback() -> None:
    response = completion('<tool_call>{"name": "f", "arguments": {"x": 1}}</tool_call>')
    assert validated_tool_call(response) == [{"name": "f", "arguments": {"x": 1}}]


def test_real_openai_types() -> None:
    types = pytest.importorskip("openai.types.chat")
    response = types.ChatCompletion.model_validate(
        {
            "id": "x",
            "object": "chat.completion",
            "created": 0,
            "model": "gpt-4o",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": 'Sure: {"intent": "cancel"}'},
                }
            ],
        }
    )
    client = client_for(response)
    assert validated_completion(client, model="gpt-4o", messages=[], schema=SCHEMA) == {"intent": "cancel"}
