from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from beacon import MalformedOutputError, SchemaValidationError
from beacon.integrations.mcp import parse_call, result_json, result_text, tool_schemas, validate_call

SEARCH = {
    "name": "search",
    "description": "search the web",
    "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]},
}


def text_block(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def result(content: list, *, is_error: bool = False, structured: Any = None) -> dict[str, Any]:
    r: dict[str, Any] = {"content": content, "isError": is_error}
    if structured is not None:
        r["structuredContent"] = structured
    return r


def test_tool_schemas_from_dicts_and_objects() -> None:
    obj = SimpleNamespace(name="open", inputSchema={"type": "object"})
    schemas = tool_schemas([SEARCH, obj])
    assert schemas["search"]["required"] == ["q"]
    assert schemas["open"] == {"type": "object"}


def test_tool_schemas_without_schema_accepts_anything() -> None:
    assert tool_schemas([{"name": "noargs"}]) == {"noargs": {}}


def test_parse_call_normalizes_and_defaults_arguments() -> None:
    assert parse_call({"name": "search", "arguments": {"q": "rust"}}) == {"name": "search", "arguments": {"q": "rust"}}
    assert parse_call(SimpleNamespace(name="ping", arguments=None)) == {"name": "ping", "arguments": {}}


def test_parse_call_rejects_bad_shapes() -> None:
    with pytest.raises(MalformedOutputError) as exc:
        parse_call({"arguments": {}})
    assert exc.value.code == "mcp.invalid_call"
    with pytest.raises(MalformedOutputError):
        parse_call({"name": "x", "arguments": [1, 2]})


def test_validate_call_against_tool_list_and_map() -> None:
    call = validate_call({"name": "search", "arguments": {"q": "rust"}}, [SEARCH])
    assert call == {"name": "search", "arguments": {"q": "rust"}}
    # also accepts a prebuilt {name: schema} map
    assert validate_call({"name": "search", "arguments": {"q": "x"}}, tool_schemas([SEARCH]))["name"] == "search"


def test_validate_call_unknown_tool_and_bad_args() -> None:
    with pytest.raises(MalformedOutputError) as exc:
        validate_call({"name": "nope", "arguments": {}}, [SEARCH])
    assert exc.value.code == "mcp.unknown_tool"
    with pytest.raises(SchemaValidationError) as exc2:
        validate_call({"name": "search", "arguments": {}}, [SEARCH])
    assert exc2.value.raw == "{}"


def test_result_text_and_no_content() -> None:
    assert result_text(result([text_block("hello "), text_block("world")])) == "hello world"
    with pytest.raises(MalformedOutputError) as exc:
        result_text(result([{"type": "image", "data": "..."}]))
    assert exc.value.code == "mcp.no_content"


def test_result_json_prefers_structured_content() -> None:
    r = result([text_block("ignored")], structured={"answer": 42})
    assert result_json(r) == {"answer": 42}


def test_result_json_parses_text_content() -> None:
    r = result([text_block('The result is {"answer": 42}.')])
    assert result_json(r) == {"answer": 42}
    assert result_json(r, schema={"type": "object", "required": ["answer"]}) == {"answer": 42}


def test_result_json_schema_violation() -> None:
    r = result([text_block('{"answer": "x"}')])
    with pytest.raises(SchemaValidationError):
        result_json(r, schema={"type": "object", "properties": {"answer": {"type": "integer"}}})


def test_result_json_error_result() -> None:
    r = result([text_block("tool blew up")], is_error=True)
    with pytest.raises(MalformedOutputError) as exc:
        result_json(r)
    assert exc.value.code == "mcp.tool_error"
    assert "tool blew up" in str(exc.value)
