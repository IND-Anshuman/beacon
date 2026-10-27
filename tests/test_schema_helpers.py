from __future__ import annotations

from types import SimpleNamespace
from typing import Optional

import pytest

import beacon
from beacon import SchemaError, SchemaValidationError, schema_from_model, schema_instructions, validate_model

SCHEMA = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}


def test_schema_instructions_is_stable_wording() -> None:
    text = schema_instructions({"type": "object", "properties": {"n": {"type": "integer"}}})
    assert text == (
        "Respond with a single JSON value that conforms to this JSON Schema:\n"
        "```json\n"
        "{\n"
        '  "type": "object",\n'
        '  "properties": {\n'
        '    "n": {\n'
        '      "type": "integer"\n'
        "    }\n"
        "  }\n"
        "}\n"
        "```"
    )


def test_schema_instructions_accepts_a_model() -> None:
    pydantic = pytest.importorskip("pydantic")

    class Intent(pydantic.BaseModel):
        intent: str

    from_model = schema_instructions(Intent)
    assert from_model == schema_instructions(Intent.model_json_schema())
    assert '"intent"' in from_model


def test_schema_instructions_is_exported_and_aliased_by_langchain() -> None:
    assert beacon.schema_instructions is schema_instructions


def test_schema_from_model_resolves_defs_and_optionals() -> None:
    pydantic = pytest.importorskip("pydantic")

    class Addr(pydantic.BaseModel):
        city: str
        zip: Optional[str] = None

    class Person(pydantic.BaseModel):
        name: str
        addr: Optional[Addr] = None

    schema = schema_from_model(Person)
    assert "$defs" in schema and "Addr" in schema["$defs"]
    # Optional[...] -> anyOf with a null branch; beacon validates both branches.
    beacon.validate_schema({"name": "A", "addr": None}, schema)
    beacon.validate_schema({"name": "A", "addr": {"city": "NYC"}}, schema)


def test_schema_from_model_rejects_unsupported_keyword_eagerly() -> None:
    fake = SimpleNamespace(model_json_schema=lambda: {"unknownKeyword": 1})
    with pytest.raises(SchemaError):
        schema_from_model(fake)


def test_schema_from_model_rejects_non_model() -> None:
    with pytest.raises(TypeError):
        schema_from_model(object())


def test_validate_model_builds_instance() -> None:
    pydantic = pytest.importorskip("pydantic")

    class Intent(pydantic.BaseModel):
        intent: str
        confidence: float

    result = validate_model({"intent": "cancel", "confidence": 0.9}, Intent)
    assert isinstance(result, Intent)
    assert result.intent == "cancel" and result.confidence == 0.9


def test_validate_model_uses_beacon_errors_not_pydantic() -> None:
    pydantic = pytest.importorskip("pydantic")

    class Intent(pydantic.BaseModel):
        intent: str
        confidence: float

    with pytest.raises(SchemaValidationError) as exc:
        validate_model({"intent": "cancel"}, Intent)
    assert exc.value.code == "schema.validation_failed"
    assert [(e["path"], e["keyword"]) for e in exc.value.errors] == [("", "required")]
