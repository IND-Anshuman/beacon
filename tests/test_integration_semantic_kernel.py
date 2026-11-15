from __future__ import annotations

from types import SimpleNamespace

import pytest

from beacon import MalformedOutputError, SchemaValidationError
from beacon.integrations.semantic_kernel import result_json, validated_tool_call

SEARCH = {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}


def test_bare_call_with_json_string_args() -> None:
    assert validated_tool_call({"name": "search", "arguments": '{"q": "rust"}'}) == [
        {"name": "search", "arguments": {"q": "rust"}}
    ]


def test_name_from_plugin_and_function() -> None:
    call = SimpleNamespace(plugin_name="web", function_name="search", arguments={"q": "go"}, name=None)
    assert validated_tool_call(call) == [{"name": "web-search", "arguments": {"q": "go"}}]


def test_message_with_items_filters_calls() -> None:
    message = {
        "items": [
            {"text": "some assistant text"},
            {"function_name": "search", "arguments": {"q": "zig"}},
        ]
    }
    assert validated_tool_call(message) == [{"name": "search", "arguments": {"q": "zig"}}]


def test_invalid_json_args() -> None:
    with pytest.raises(MalformedOutputError) as exc:
        validated_tool_call({"name": "search", "arguments": "{bad"})
    assert exc.value.code == "semantic_kernel.invalid_arguments"


def test_unknown_tool_and_violation() -> None:
    with pytest.raises(MalformedOutputError) as exc:
        validated_tool_call({"name": "nope", "arguments": {}}, tool_schemas={"search": SEARCH})
    assert exc.value.code == "semantic_kernel.unknown_tool"
    with pytest.raises(SchemaValidationError) as exc2:
        validated_tool_call({"name": "search", "arguments": {}}, tool_schemas={"search": SEARCH})
    assert exc2.value.raw == "{}"


def test_result_json_text_and_structured() -> None:
    assert result_json(SimpleNamespace(result='The answer is {"answer": 42}.')) == {"answer": 42}
    assert result_json({"result": {"answer": 42}}, schema={"type": "object", "required": ["answer"]}) == {"answer": 42}


def test_result_json_no_content() -> None:
    with pytest.raises(MalformedOutputError) as exc:
        result_json(SimpleNamespace(result=123))
    assert exc.value.code == "semantic_kernel.no_content"
