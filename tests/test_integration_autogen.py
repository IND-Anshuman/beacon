from __future__ import annotations

from types import SimpleNamespace

import pytest

from beacon import MalformedOutputError, SchemaValidationError
from beacon.integrations.autogen import parse_output, validated_tool_call

SEARCH = {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}


def test_openai_style_tool_calls_with_json_string_args() -> None:
    message = {"tool_calls": [{"function": {"name": "search", "arguments": '{"q": "rust"}'}}]}
    assert validated_tool_call(message) == [{"name": "search", "arguments": {"q": "rust"}}]


def test_function_call_field() -> None:
    message = SimpleNamespace(function_call=SimpleNamespace(name="search", arguments='{"q": "go"}'))
    assert validated_tool_call(message) == [{"name": "search", "arguments": {"q": "go"}}]


def test_bare_function_call_with_dict_args() -> None:
    call = SimpleNamespace(name="search", arguments={"q": "zig"})
    assert validated_tool_call(call) == [{"name": "search", "arguments": {"q": "zig"}}]


def test_missing_arguments_default_to_empty() -> None:
    assert validated_tool_call({"name": "ping", "arguments": None}) == [{"name": "ping", "arguments": {}}]


def test_invalid_json_arguments() -> None:
    with pytest.raises(MalformedOutputError) as exc:
        validated_tool_call({"name": "search", "arguments": "{not json"})
    assert exc.value.code == "autogen.invalid_arguments"


def test_non_object_json_arguments() -> None:
    with pytest.raises(MalformedOutputError) as exc:
        validated_tool_call({"name": "search", "arguments": "[1, 2]"})
    assert exc.value.code == "autogen.invalid_arguments"


def test_unknown_tool() -> None:
    with pytest.raises(MalformedOutputError) as exc:
        validated_tool_call({"name": "nope", "arguments": {}}, tool_schemas={"search": SEARCH})
    assert exc.value.code == "autogen.unknown_tool"


def test_schema_violation_attaches_raw() -> None:
    with pytest.raises(SchemaValidationError) as exc:
        validated_tool_call({"name": "search", "arguments": {}}, tool_schemas={"search": SEARCH})
    assert exc.value.raw == "{}"


def test_no_tool_call() -> None:
    with pytest.raises(MalformedOutputError) as exc:
        validated_tool_call({"content": "just text"})
    assert exc.value.code == "autogen.no_tool_call"


def test_parse_output_extracts_json() -> None:
    assert parse_output({"content": 'Here: {"ok": true}'}) == {"ok": True}
    assert parse_output('{"ok": false}') == {"ok": False}


def test_parse_output_no_content() -> None:
    with pytest.raises(MalformedOutputError) as exc:
        parse_output({"content": None})
    assert exc.value.code == "autogen.no_content"
