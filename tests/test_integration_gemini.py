from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from beacon import MalformedOutputError, NoToolCallFoundError, SchemaValidationError
from beacon.integrations.gemini_sdk import (
    avalidated_completion,
    response_text,
    validated_completion,
    validated_tool_call,
)

SCHEMA = {"type": "object", "properties": {"intent": {"type": "string"}}, "required": ["intent"]}


def response_of(parts: list[Any]) -> SimpleNamespace:
    content = SimpleNamespace(parts=parts)
    return SimpleNamespace(candidates=[SimpleNamespace(content=content)])


def text_part(text: str) -> SimpleNamespace:
    return SimpleNamespace(text=text, function_call=None)


def fc_part_snake(name: str, args: Any) -> SimpleNamespace:
    return SimpleNamespace(text=None, function_call=SimpleNamespace(name=name, args=args))


def fc_part_camel(name: str, args: Any) -> dict[str, Any]:
    return {"functionCall": {"name": name, "args": args}}


class FakeModels:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def generate_content(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.response


class FakeAsyncModels(FakeModels):
    async def generate_content(self, **kwargs: Any) -> Any:  # type: ignore[override]
        self.calls.append(kwargs)
        return self.response


def client_for(response: Any) -> SimpleNamespace:
    return SimpleNamespace(models=FakeModels(response))


def test_response_text_joins_text_parts() -> None:
    assert response_text(response_of([text_part("Here: "), text_part('{"intent": "cancel"}')])) == (
        'Here: {"intent": "cancel"}'
    )


def test_validated_completion_returns_dict_and_forwards_kwargs() -> None:
    client = client_for(response_of([text_part('```json\n{"intent": "cancel"}\n```')]))
    result = validated_completion(client, model="gemini-2.0-flash", contents="hi", schema=SCHEMA)
    assert result == {"intent": "cancel"}
    assert client.models.calls == [{"model": "gemini-2.0-flash", "contents": "hi"}]


def test_function_call_parts_snake_and_camel() -> None:
    snake = response_of([fc_part_snake("search", {"q": "rust"})])
    assert validated_tool_call(snake) == [{"name": "search", "arguments": {"q": "rust"}}]
    camel = response_of([fc_part_camel("open", {"id": 3})])
    assert validated_tool_call(camel) == [{"name": "open", "arguments": {"id": 3}}]


def test_tool_schemas_reject_unknown_and_invalid() -> None:
    response = response_of([fc_part_snake("search", {"q": "rust"})])
    with pytest.raises(SchemaValidationError):
        validated_tool_call(response, tool_schemas={"search": {"type": "object", "required": ["q", "limit"]}})
    with pytest.raises(MalformedOutputError) as exc:
        validated_tool_call(response, tool_schemas={"other": {}})
    assert exc.value.code == "gemini.unknown_tool"


def test_function_call_only_response_has_no_text() -> None:
    with pytest.raises(MalformedOutputError) as exc:
        response_text(response_of([fc_part_snake("search", {"q": "x"})]))
    assert exc.value.code == "gemini.no_content"


def test_text_tool_calls_fallback() -> None:
    response = response_of([text_part('<tool_call>{"name": "f", "arguments": {"x": 1}}</tool_call>')])
    assert validated_tool_call(response) == [{"name": "f", "arguments": {"x": 1}}]


def test_no_tool_call_in_plain_text_raises() -> None:
    with pytest.raises(NoToolCallFoundError):
        validated_tool_call(response_of([text_part("just prose")]))


def test_output_model_and_async() -> None:
    pydantic = pytest.importorskip("pydantic")

    class Intent(pydantic.BaseModel):
        intent: str

    sync = validated_completion(
        client_for(response_of([text_part('{"intent": "refund"}')])), model="m", contents="q", output_model=Intent
    )
    assert isinstance(sync, Intent) and sync.intent == "refund"

    models = FakeAsyncModels(response_of([text_part('{"intent": "cancel"}')]))
    result = asyncio.run(avalidated_completion(None, create=models.generate_content, model="m", contents="q", schema=SCHEMA))
    assert result == {"intent": "cancel"}
