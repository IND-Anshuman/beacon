from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from beacon import MalformedOutputError, NoToolCallFoundError, SchemaValidationError
from beacon.integrations.anthropic_sdk import (
    avalidated_completion,
    response_text,
    validated_completion,
    validated_tool_call,
)

SCHEMA = {"type": "object", "properties": {"intent": {"type": "string"}}, "required": ["intent"]}


def text_block(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def tool_block(name: str, input: Any) -> dict[str, Any]:
    return {"type": "tool_use", "id": "tu_1", "name": name, "input": input}


def message(content: Any) -> SimpleNamespace:
    return SimpleNamespace(content=content)


class FakeMessages:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.response


class FakeAsyncMessages(FakeMessages):
    async def create(self, **kwargs: Any) -> Any:  # type: ignore[override]
        self.calls.append(kwargs)
        return self.response


def client_for(response: Any, *, is_async: bool = False) -> SimpleNamespace:
    messages = (FakeAsyncMessages if is_async else FakeMessages)(response)
    return SimpleNamespace(messages=messages)


def test_response_text_joins_text_blocks_and_accepts_plain_string() -> None:
    assert response_text(message([text_block("Here: "), text_block('{"intent": "cancel"}')])) == (
        'Here: {"intent": "cancel"}'
    )
    assert response_text(message('{"a": 1}')) == '{"a": 1}'
    assert response_text({"content": [{"type": "text", "text": "hi"}]}) == "hi"


def test_validated_completion_returns_dict_and_forwards_kwargs() -> None:
    client = client_for(message([text_block('```json\n{"intent": "cancel"}\n```')]))
    result = validated_completion(
        client, model="claude-3-5-sonnet", messages=[{"role": "user", "content": "hi"}], schema=SCHEMA
    )
    assert result == {"intent": "cancel"}
    assert client.messages.calls == [{"model": "claude-3-5-sonnet", "messages": [{"role": "user", "content": "hi"}]}]


def test_schema_violation_has_raw_attached() -> None:
    client = client_for(message([text_block('{"other": 1}')]))
    with pytest.raises(SchemaValidationError) as exc:
        validated_completion(client, model="m", messages=[], schema=SCHEMA)
    assert exc.value.raw == '{"other": 1}'


def test_tool_use_blocks_are_read_directly() -> None:
    response = message([tool_block("search", {"q": "rust"}), tool_block("open", {"id": 3})])
    assert validated_tool_call(response) == [
        {"name": "search", "arguments": {"q": "rust"}},
        {"name": "open", "arguments": {"id": 3}},
    ]


def test_tool_schemas_reject_unknown_and_invalid() -> None:
    response = message([tool_block("search", {"q": "rust"})])
    schemas = {"search": {"type": "object", "required": ["q", "limit"]}}
    with pytest.raises(SchemaValidationError):
        validated_tool_call(response, tool_schemas=schemas)
    with pytest.raises(MalformedOutputError) as exc:
        validated_tool_call(response, tool_schemas={"other": {}})
    assert exc.value.code == "anthropic.unknown_tool"


def test_tool_use_only_response_has_no_text() -> None:
    with pytest.raises(MalformedOutputError) as exc:
        response_text(message([tool_block("search", {"q": "x"})]))
    assert exc.value.code == "anthropic.no_content"


def test_text_tool_calls_fallback() -> None:
    response = message([text_block('<tool_call>{"name": "f", "arguments": {"x": 1}}</tool_call>')])
    assert validated_tool_call(response) == [{"name": "f", "arguments": {"x": 1}}]


def test_no_tool_call_in_plain_text_raises() -> None:
    with pytest.raises(NoToolCallFoundError):
        validated_tool_call(message([text_block("just prose")]))


def test_invalid_tool_input_type() -> None:
    with pytest.raises(MalformedOutputError) as exc:
        validated_tool_call(message([tool_block("f", "not-an-object")]))
    assert exc.value.code == "anthropic.invalid_tool_input"


def test_output_model_and_async() -> None:
    pydantic = pytest.importorskip("pydantic")

    class Intent(pydantic.BaseModel):
        intent: str

    sync = validated_completion(
        client_for(message([text_block('{"intent": "refund"}')])), model="m", messages=[], output_model=Intent
    )
    assert isinstance(sync, Intent) and sync.intent == "refund"

    client = client_for(message([text_block('{"intent": "cancel"}')]), is_async=True)
    result = asyncio.run(avalidated_completion(client, model="m", messages=[], schema=SCHEMA))
    assert result == {"intent": "cancel"}
