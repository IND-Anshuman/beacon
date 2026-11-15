from __future__ import annotations

from types import SimpleNamespace

import pytest

from beacon import MalformedOutputError, SchemaValidationError
from beacon.integrations.crewai import parse_output, raw_text

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}


def test_raw_text_from_output_and_string() -> None:
    assert raw_text({"raw": "hello"}) == "hello"
    assert raw_text("plain") == "plain"


def test_raw_text_missing() -> None:
    with pytest.raises(MalformedOutputError) as exc:
        raw_text({"json_dict": {}})
    assert exc.value.code == "crewai.no_content"


def test_parse_output_from_raw_text() -> None:
    assert parse_output({"raw": 'Result: {"ok": true}'}) == {"ok": True}


def test_parse_output_prefers_json_dict() -> None:
    out = {"raw": "ignored text", "json_dict": {"ok": True}}
    assert parse_output(out, schema=SCHEMA) == {"ok": True}


def test_parse_output_uses_pydantic_view() -> None:
    model = SimpleNamespace(model_dump=lambda mode="json": {"ok": False})
    assert parse_output(SimpleNamespace(raw="ignored", json_dict=None, pydantic=model)) == {"ok": False}


def test_parse_output_schema_violation_attaches_raw() -> None:
    with pytest.raises(SchemaValidationError) as exc:
        parse_output({"raw": "x", "json_dict": {"ok": "nope"}}, schema=SCHEMA)
    assert '"ok"' in exc.value.raw


def test_parse_output_from_text_schema_violation() -> None:
    with pytest.raises(SchemaValidationError):
        parse_output({"raw": '{"ok": 1}'}, schema=SCHEMA)
