from __future__ import annotations

from types import SimpleNamespace

import pytest

from beacon import MalformedOutputError, SchemaValidationError
from beacon.integrations.smolagents import parse_final_answer, tool_schemas


def test_tool_schemas_from_inputs() -> None:
    tool = SimpleNamespace(
        name="get_weather",
        inputs={
            "city": {"type": "string", "description": "the city"},
            "days": {"type": "integer", "nullable": True},
        },
    )
    schemas = tool_schemas([tool])
    assert schemas["get_weather"] == {
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "the city"},
            "days": {"type": "integer"},
        },
        "required": ["city"],
    }


def test_tool_schemas_non_json_type_has_no_type() -> None:
    tool = {"name": "see", "inputs": {"photo": {"type": "image"}}}
    assert tool_schemas([tool])["see"] == {"type": "object", "properties": {"photo": {}}, "required": ["photo"]}


def test_tool_schemas_missing_name() -> None:
    with pytest.raises(MalformedOutputError) as exc:
        tool_schemas([{"inputs": {}}])
    assert exc.value.code == "smolagents.invalid_tool"


def test_parse_final_answer_string() -> None:
    assert parse_final_answer('The answer is {"city": "Paris"}') == {"city": "Paris"}


def test_parse_final_answer_already_structured() -> None:
    schema = {"type": "object", "required": ["city"]}
    assert parse_final_answer({"city": "Paris"}, schema=schema) == {"city": "Paris"}
    assert parse_final_answer([1, 2, 3]) == [1, 2, 3]


def test_parse_final_answer_structured_violation() -> None:
    with pytest.raises(SchemaValidationError):
        parse_final_answer({"city": 1}, schema={"type": "object", "properties": {"city": {"type": "string"}}})


def test_parse_final_answer_non_text() -> None:
    with pytest.raises(MalformedOutputError) as exc:
        parse_final_answer(42)
    assert exc.value.code == "smolagents.no_content"
