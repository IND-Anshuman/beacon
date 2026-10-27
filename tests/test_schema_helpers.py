from __future__ import annotations

import pytest

import beacon
from beacon import schema_instructions


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
