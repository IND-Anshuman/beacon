from __future__ import annotations

import pytest

from beacon import MalformedOutputError, SchemaValidationError
from beacon.integrations.strands import parse_tool_use, result_json, tool_schemas, validated_tool_call

SPEC = {
    "name": "search",
    "description": "search",
    "inputSchema": {"json": {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}},
}


def test_tool_schemas_from_specs() -> None:
    assert tool_schemas([SPEC])["search"]["required"] == ["q"]
    assert tool_schemas([{"toolSpec": SPEC}])["search"]["required"] == ["q"]


def test_tool_schemas_no_schema() -> None:
    assert tool_schemas([{"name": "noargs"}]) == {"noargs": {}}


def test_parse_tool_use_wrapped_and_bare() -> None:
    assert parse_tool_use({"toolUse": {"name": "search", "input": {"q": "rust"}}}) == {
        "name": "search",
        "arguments": {"q": "rust"},
    }
    assert parse_tool_use({"name": "ping", "input": None}) == {"name": "ping", "arguments": {}}


def test_parse_tool_use_bad_input() -> None:
    with pytest.raises(MalformedOutputError) as exc:
        parse_tool_use({"name": "x", "input": [1]})
    assert exc.value.code == "strands.invalid_call"


def test_validated_tool_call_unknown_and_bad_args() -> None:
    with pytest.raises(MalformedOutputError) as exc:
        validated_tool_call({"toolUse": {"name": "nope", "input": {}}}, [SPEC])
    assert exc.value.code == "strands.unknown_tool"
    with pytest.raises(SchemaValidationError) as exc2:
        validated_tool_call({"toolUse": {"name": "search", "input": {}}}, [SPEC])
    assert exc2.value.raw == "{}"


def test_result_json_prefers_json_block() -> None:
    r = {"toolResult": {"status": "success", "content": [{"json": {"answer": 42}}]}}
    assert result_json(r) == {"answer": 42}


def test_result_json_parses_text_block() -> None:
    r = {"toolResult": {"status": "success", "content": [{"text": 'The answer is {"answer": 42}.'}]}}
    assert result_json(r, schema={"type": "object", "required": ["answer"]}) == {"answer": 42}


def test_result_json_error_status() -> None:
    r = {"toolResult": {"status": "error", "content": [{"text": "boom"}]}}
    with pytest.raises(MalformedOutputError) as exc:
        result_json(r)
    assert exc.value.code == "strands.tool_error"
    assert "boom" in str(exc.value)
