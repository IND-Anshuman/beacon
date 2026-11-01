"""Property-based / fuzz tests: beacon never crashes and never silently
changes valid data, for arbitrary input."""

from __future__ import annotations

import json

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

import beacon  # noqa: E402
from beacon import (  # noqa: E402
    detect_pii,
    extract_json,
    extract_json_detailed,
    hash_content,
    normalize,
    parse_tool_call,
    parse_tool_calls,
    redact,
    repair_json,
    template_variables,
    validate_schema,
)
from beacon.errors import BeaconError  # noqa: E402

# Anything a deterministic failure is allowed to be. A Rust panic surfaces as
# pyo3_runtime.PanicException (a BaseException, not Exception), so it is NOT in
# here and would escape and fail the test — which is the point.
ALLOWED = (BeaconError, ValueError, TypeError)

# JSON values that round-trip through json.dumps: finite numbers, UTF-8 text
# (no lone surrogates), bounded ints.
_jtext = st.text(st.characters(codec="utf-8"))
_scalars = (
    st.none()
    | st.booleans()
    | st.integers(min_value=-(10**15), max_value=10**15)
    | st.floats(allow_nan=False, allow_infinity=False)
    | _jtext
)
json_values = st.recursive(
    _scalars,
    lambda children: st.lists(children, max_size=4) | st.dictionaries(_jtext, children, max_size=4),
    max_leaves=15,
)

_TEXT_BLOCKS = (
    extract_json,
    extract_json_detailed,
    repair_json,
    parse_tool_call,
    parse_tool_calls,
    normalize,
    redact,
    detect_pii,
    template_variables,
    hash_content,
)


@settings(max_examples=300, deadline=None)
@given(text=st.text())
def test_blocks_never_crash_on_arbitrary_text(text: str) -> None:
    for fn in _TEXT_BLOCKS:
        try:
            fn(text)
        except ALLOWED:
            pass  # a clean, deterministic refusal is fine


@settings(max_examples=200, deadline=None)
@given(schema=json_values)
def test_validate_schema_never_crashes_on_arbitrary_schema(schema: object) -> None:
    try:
        validate_schema({"x": 1, "y": [2, 3]}, schema)  # type: ignore[arg-type]
    except ALLOWED:
        pass


@settings(max_examples=300, deadline=None)
@given(value=json_values)
def test_repair_json_never_changes_valid_json(value: object) -> None:
    r = repair_json(json.dumps(value))
    assert r.repairs == ()
    assert not r.incomplete
    assert r.value == value


@settings(max_examples=200, deadline=None)
@given(text=st.text())
def test_repaired_output_is_valid_json(text: str) -> None:
    try:
        r = repair_json(text)
    except BeaconError:
        return
    # Whatever it produced must itself be valid JSON that re-repairs cleanly.
    again = repair_json(json.dumps(r.value))
    assert again.value == r.value
    assert again.repairs == () and not again.incomplete


@settings(max_examples=300, deadline=None)
@given(value=json_values)
def test_hash_is_deterministic(value: object) -> None:
    assert hash_content(value) == hash_content(value)


@settings(max_examples=200, deadline=None)
@given(data=st.dictionaries(_jtext, _scalars, min_size=2, max_size=6))
def test_hash_ignores_dict_key_order(data: dict) -> None:
    reordered = dict(reversed(list(data.items())))
    assert hash_content(data) == hash_content(reordered)


@settings(max_examples=300, deadline=None)
@given(text=st.text(st.characters(codec="utf-8")))
def test_normalize_is_idempotent(text: str) -> None:
    once = normalize(text)
    assert normalize(once) == once


def test_panic_exception_would_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    # Guard the guard: confirm a non-Exception error is NOT swallowed by ALLOWED.
    class FakePanic(BaseException):
        pass

    assert not issubclass(FakePanic, ALLOWED)
    assert beacon.__version__  # sanity
