from __future__ import annotations

import pytest

from beacon import MalformedOutputError, SchemaValidationError
from beacon.integrations.haystack import validate_replies


def test_validate_replies_first_reply() -> None:
    assert validate_replies(['Here you go: {"ok": true}']) == {"ok": True}


def test_validate_replies_index() -> None:
    assert validate_replies(["junk", '{"n": 1}'], reply_index=1) == {"n": 1}


def test_validate_replies_schema() -> None:
    schema = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}
    assert validate_replies(['{"n": 2}'], schema=schema) == {"n": 2}
    with pytest.raises(SchemaValidationError):
        validate_replies(['{"n": "x"}'], schema=schema)


def test_validate_replies_empty() -> None:
    with pytest.raises(MalformedOutputError) as exc:
        validate_replies([])
    assert exc.value.code == "haystack.no_content"


def test_output_validator_component() -> None:
    pytest.importorskip("haystack")
    from beacon.integrations.haystack import output_validator

    component = output_validator(schema={"type": "object", "required": ["ok"]})
    out = component.run(replies=['result: {"ok": true}'])
    assert out == {"json": {"ok": True}}
