from __future__ import annotations

from types import SimpleNamespace

import pytest

from beacon import MalformedOutputError, SchemaValidationError
from beacon.integrations.agno import parse_output, validated_tool_call

SEARCH = {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}


def test_single_execution_dict_args() -> None:
    assert validated_tool_call({"tool_name": "search", "tool_args": {"q": "rust"}}) == [
        {"name": "search", "arguments": {"q": "rust"}}
    ]


def test_response_with_tools_list_and_json_string_args() -> None:
    response = SimpleNamespace(tools=[SimpleNamespace(tool_name="search", tool_args='{"q": "go"}')])
    assert validated_tool_call(response) == [{"name": "search", "arguments": {"q": "go"}}]


def test_invalid_json_args() -> None:
    with pytest.raises(MalformedOutputError) as exc:
        validated_tool_call({"tool_name": "search", "tool_args": "{bad"})
    assert exc.value.code == "agno.invalid_arguments"


def test_unknown_tool_and_schema_violation() -> None:
    with pytest.raises(MalformedOutputError) as exc:
        validated_tool_call({"tool_name": "nope", "tool_args": {}}, tool_schemas={"search": SEARCH})
    assert exc.value.code == "agno.unknown_tool"
    with pytest.raises(SchemaValidationError) as exc2:
        validated_tool_call({"tool_name": "search", "tool_args": {}}, tool_schemas={"search": SEARCH})
    assert exc2.value.raw == "{}"


def test_missing_tool_name() -> None:
    with pytest.raises(MalformedOutputError) as exc:
        validated_tool_call({"tool_args": {}})
    assert exc.value.code == "agno.invalid_call"


def test_parse_output_text_and_structured() -> None:
    assert parse_output({"content": 'Final: {"ok": true}'}) == {"ok": True}
    model = SimpleNamespace(model_dump=lambda mode="json": {"ok": False})
    assert parse_output(SimpleNamespace(content=model)) == {"ok": False}


def test_parse_output_no_content() -> None:
    with pytest.raises(MalformedOutputError) as exc:
        parse_output(SimpleNamespace(content=123))
    assert exc.value.code == "agno.no_content"
