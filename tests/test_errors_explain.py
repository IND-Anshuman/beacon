"""Developer-experience surface: ``BeaconError.explain()`` / ``.details()`` and
the ``guidance_for`` / ``explain_code`` helpers. All deterministic, no I/O."""

from __future__ import annotations

import pytest

import beacon
from beacon.errors import (
    MalformedOutputError,
    MissingVariableError,
    SchemaValidationError,
    explain_code,
    guidance_for,
)


def test_explain_has_code_cause_and_fix() -> None:
    with pytest.raises(beacon.NoJSONFoundError) as exc:
        beacon.extract_json("no json here at all")
    text = exc.value.explain()
    assert text.startswith("[json.not_found]")
    assert "Cause:" in text
    assert "Fix:" in text
    assert "repair_json" in text  # the guidance points at the right block


def test_explain_is_deterministic() -> None:
    a = MalformedOutputError("bad", code="json.unexpected_end", position=5, line=1, column=6)
    b = MalformedOutputError("bad", code="json.unexpected_end", position=5, line=1, column=6)
    assert a.explain() == b.explain()
    # position context is rendered
    assert "line 1, column 6 (offset 5)" in a.explain()


def test_explain_notes_raw_attribute() -> None:
    err = MalformedOutputError("bad", code="malformed_output", raw='{"x"')
    assert ".raw" in err.explain()


def test_details_drops_none_and_converts_tuples() -> None:
    err = MalformedOutputError("bad", code="json.unexpected_end", position=3)
    d = err.details()
    assert d["code"] == "json.unexpected_end"
    assert d["message"] == "bad"
    assert d["position"] == 3
    assert "line" not in d and "raw" not in d  # None fields omitted

    names = MissingVariableError("missing a, b", names=["a", "b"])
    nd = names.details()
    assert nd["names"] == ["a", "b"]  # tuple -> list, JSON-friendly
    assert isinstance(nd["names"], list)


def test_schema_violations_appear_in_explain() -> None:
    err = SchemaValidationError(
        "2 schema violations",
        errors=[
            {"path": "/n", "keyword": "type", "message": "expected integer"},
            {"path": "", "keyword": "required", "message": "missing 'id'"},
        ],
    )
    text = err.explain()
    assert "Violations:" in text
    assert "/n: type: expected integer" in text
    assert "(root): required: missing 'id'" in text


def test_schema_violations_are_truncated() -> None:
    errs = [{"path": f"/f{i}", "keyword": "type", "message": "x"} for i in range(15)]
    err = SchemaValidationError("many", errors=errs)
    text = err.explain()
    assert "... and 5 more" in text


def test_missing_variable_lists_names() -> None:
    err = MissingVariableError("missing", names=["age", "name"])
    assert "Variables: age, name" in err.explain()


def test_guidance_for_matches_exact_suffix_and_prefix() -> None:
    assert guidance_for("json.not_found") is not None
    # suffix family: any provider's unknown_tool
    assert guidance_for("crewai.unknown_tool") == guidance_for("vercel.unknown_tool")
    assert guidance_for("crewai.unknown_tool")[0].startswith("The model called a tool")
    # prefix family: an unregistered json.* code still gets json guidance
    assert guidance_for("json.unexpected_end") is not None
    assert guidance_for("json.unexpected_end")[1].count("repair_json") >= 1
    # nothing matches
    assert guidance_for("totally.unrelated_code") is None


def test_explain_code_for_unknown() -> None:
    out = explain_code("totally.unrelated_code")
    assert "No specific guidance" in out
    assert "unknown_tool" in out  # lists the known families


def test_guidance_text_is_ascii() -> None:
    # beacon explain output can be redirected to a cp1252 pipe on Windows; our
    # guidance text must never raise UnicodeEncodeError there.
    from beacon.errors import _FAMILY_PREFIX, _FAMILY_SUFFIX, _GUIDANCE

    for code in list(_GUIDANCE) + list(_FAMILY_PREFIX) + list(_FAMILY_SUFFIX):
        explain_code(code).encode("ascii")


def test_explain_code_is_public() -> None:
    assert beacon.explain_code("json.not_found") == explain_code("json.not_found")
