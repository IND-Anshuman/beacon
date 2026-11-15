from __future__ import annotations

from types import SimpleNamespace

import pytest

from beacon import MalformedOutputError, SchemaValidationError
from beacon.integrations.openai_agents import tool_schemas, validated_output, validated_tool_call

SEARCH = {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}


def test_tool_schemas_from_function_tools() -> None:
    tool = SimpleNamespace(name="search", params_json_schema=SEARCH)
    assert tool_schemas([tool])["search"]["required"] == ["q"]


def test_validated_tool_call_json_string_args() -> None:
    assert validated_tool_call({"name": "search", "arguments": '{"q": "rust"}'}, {"search": SEARCH}) == {
        "name": "search",
        "arguments": {"q": "rust"},
    }


def test_validated_tool_call_unknown_and_violation() -> None:
    with pytest.raises(MalformedOutputError) as exc:
        validated_tool_call({"name": "nope", "arguments": "{}"}, {"search": SEARCH})
    assert exc.value.code == "openai_agents.unknown_tool"
    with pytest.raises(SchemaValidationError) as exc2:
        validated_tool_call({"name": "search", "arguments": "{}"}, {"search": SEARCH})
    assert exc2.value.raw == "{}"


def test_validated_tool_call_invalid_json() -> None:
    with pytest.raises(MalformedOutputError) as exc:
        validated_tool_call({"name": "search", "arguments": "{bad"})
    assert exc.value.code == "openai_agents.invalid_arguments"


def test_validated_output_text() -> None:
    result = SimpleNamespace(final_output='The plan is {"intent": "cancel"}')
    assert validated_output(result) == {"intent": "cancel"}


def test_validated_output_structured_model() -> None:
    model = SimpleNamespace(model_dump=lambda mode="json": {"intent": "keep"})
    assert validated_output(SimpleNamespace(final_output=model)) == {"intent": "keep"}


def test_validated_output_no_content() -> None:
    with pytest.raises(MalformedOutputError) as exc:
        validated_output(SimpleNamespace(final_output=123))
    assert exc.value.code == "openai_agents.no_content"
