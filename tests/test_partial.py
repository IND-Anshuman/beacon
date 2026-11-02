from __future__ import annotations

import json

import pytest

from beacon import parse_partial
from beacon.snapshots import assert_snapshot


def test_complete_value_is_complete() -> None:
    r = parse_partial('{"a": 1, "b": [true, null]}')
    assert r.value == {"a": 1, "b": [True, None]}
    assert r.complete is True
    assert r.consumed == len('{"a": 1, "b": [true, null]}')


def test_trailing_whitespace_is_still_complete() -> None:
    r = parse_partial('  {"a": 1}  \n')
    assert r.complete is True
    assert r.value == {"a": 1}
    assert r.consumed == len('  {"a": 1}')  # stops at end of value


def test_truncated_object_is_closed() -> None:
    r = parse_partial('{"a": 1, "b": {"c": 2')
    assert r.complete is False
    assert r.value == {"a": 1, "b": {"c": 2}}


def test_truncated_array_and_string() -> None:
    assert parse_partial("[1, 2, 3").value == [1, 2, 3]
    assert parse_partial('{"msg": "half').value == {"msg": "half"}
    assert parse_partial('{"msg": "half').complete is False


def test_dangling_key_is_dropped() -> None:
    for text in ('{"a": 1, "b"', '{"a": 1, "b":', '{"a": 1, "b": ', '{"a": 1, "cd'):
        r = parse_partial(text)
        assert r.value == {"a": 1}, text
        assert r.complete is False, text


def test_truncated_numbers_and_literals() -> None:
    assert parse_partial("[1, 2.").value == [1, 2]
    assert parse_partial("[1, 2.5e").value == [1, 2.5]
    assert parse_partial("[1, -").value == [1]
    assert parse_partial("[tr").value == []
    assert parse_partial("[true, fal").value == [True]


def test_empty_and_garbage() -> None:
    for text in ("", "   ", "not json", "}"):
        r = parse_partial(text)
        assert r.value is None, text
        assert r.complete is False, text
        assert r.consumed == 0, text


def test_scalars_are_complete() -> None:
    assert parse_partial("true").value is True
    assert parse_partial("null").value is None
    assert parse_partial("-0.5").value == -0.5
    assert parse_partial('"hi"').value == "hi"
    assert parse_partial("true").complete is True


def test_consumed_counts_code_points() -> None:
    text = '["é", "🥂"]'
    r = parse_partial(text)
    assert r.complete is True
    assert r.consumed == len(text)
    assert r.consumed < len(text.encode("utf-8"))


def test_result_is_a_dataclass() -> None:
    r = parse_partial("[1]")
    assert (r.value, r.complete, r.consumed) == ([1], True, 3)


def test_non_str_raises() -> None:
    with pytest.raises(TypeError):
        parse_partial(123)  # type: ignore[arg-type]


CORPUS = {
    "complete_object": '{"intent": "cancel", "confidence": 0.9}',
    "complete_array": "[1, 2, 3]",
    "complete_scalar": "true",
    "truncated_object": '{"a": 1, "b": {"c": 2',
    "truncated_array": "[1, 2, 3",
    "truncated_string": '{"message": "the answer is',
    "dangling_key": '{"a": 1, "b":',
    "truncated_number": "[1, 2, 3.14159e",
    "truncated_literal": "[true, fal",
    "nested_stream": '{"steps": [{"tool": "search", "args": {"q": "ru',
    "empty": "",
    "whitespace": "   \n",
    "not_json": "sure! here is the json:",
}


def _as_data(text: str) -> dict:
    r = parse_partial(text)
    return {"value": r.value, "complete": r.complete, "consumed": r.consumed}


@pytest.mark.parametrize("case", sorted(CORPUS))
def test_snapshot_corpus(case: str) -> None:
    text = CORPUS[case]
    assert_snapshot(f"parse_partial/{case}", _as_data(text), input={"text": text})


def test_prefixes_of_serialized_value_converge() -> None:
    # Feeding every prefix of a serialized JSON value must never crash, and the
    # final prefix must reproduce the whole value as complete.
    value = {"items": [1, 2.5, -3, "a\nb", True, None], "nested": {"x": [False]}}
    full = json.dumps(value)
    for i in range(len(full) + 1):
        parse_partial(full[:i])  # must not raise
    final = parse_partial(full)
    assert final.complete is True
    assert final.value == value
