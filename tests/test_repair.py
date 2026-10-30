from __future__ import annotations

import pytest

from beacon import NoJSONFoundError, SchemaValidationError, repair_json
from beacon.snapshots import assert_snapshot


def kinds(text: str) -> list[str]:
    return [r.kind for r in repair_json(text).repairs]


def test_clean_json_is_not_repaired() -> None:
    r = repair_json('{"a": 1, "b": [true, null, "x"]}')
    assert r.value == {"a": 1, "b": [True, None, "x"]}
    assert r.repairs == ()
    assert r.repaired is False
    assert r.incomplete is False


def test_trailing_comma() -> None:
    r = repair_json('{"a": 1, "b": 2,}')
    assert r.value == {"a": 1, "b": 2}
    assert kinds('{"a": 1, "b": 2,}') == ["trailing_comma"]
    assert repair_json("[1, 2, 3, ]").value == [1, 2, 3]


def test_single_quotes_and_unquoted_keys_and_python_literals() -> None:
    r = repair_json("{intent: 'cancel', ok: True, v: None}")
    assert r.value == {"intent": "cancel", "ok": True, "v": None}
    assert set(kinds("{intent: 'cancel', ok: True, v: None}")) == {
        "unquoted_keys",
        "single_quotes",
        "python_literals",
    }


def test_comments_and_nan_infinity() -> None:
    assert repair_json('{\n  // c\n  "a": 1 /* x */\n}').value == {"a": 1}
    r = repair_json('{"a": NaN, "b": Infinity, "c": -Infinity}')
    assert r.value == {"a": None, "b": None, "c": None}
    assert kinds('[NaN, Infinity]') == ["nan_infinity", "nan_infinity"]


def test_duplicate_keys_keep_last() -> None:
    r = repair_json('{"a": 1, "a": 2, "a": 3}')
    assert r.value == {"a": 3}
    assert kinds('{"a": 1, "a": 2}') == ["duplicate_keys"]


def test_leading_zeros_and_big_integers() -> None:
    assert repair_json("[007, -042, 0]").value == [7, -42, 0]
    assert kinds("[007]") == ["leading_zeros"]
    big = 123456789012345678901234567890
    r = repair_json(f"[{big}]")
    assert r.value == [big] and r.repairs == ()  # preserved exactly, no repair


def test_bom_and_control_chars() -> None:
    assert repair_json('﻿{"a": 1}').repairs[0].kind == "bom"
    r = repair_json('{"a": "line1\nline2"}')
    assert r.value == {"a": "line1\nline2"}
    assert kinds('{"a": "x\ty"}') == ["control_chars"]


def test_truncation_closes_and_marks_incomplete() -> None:
    r = repair_json('{"a": 1, "b": {"c": 2')
    assert r.value == {"a": 1, "b": {"c": 2}}
    assert r.incomplete is True
    last = r.repairs[-1]
    assert last.kind == "truncated"
    assert "} }" in last.detail
    # dangling key with no value is dropped
    d = repair_json('{"a": 1, "b":')
    assert d.value == {"a": 1} and d.incomplete is True
    # unterminated string
    assert repair_json('{"a": "oops').value == {"a": "oops"}


def test_schema_option_validates_repaired_value() -> None:
    schema = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}
    assert repair_json('{"n": 1,}', schema=schema).value == {"n": 1}
    with pytest.raises(SchemaValidationError):
        repair_json('{"n": "x",}', schema=schema)


def test_no_json_raises() -> None:
    for text in ("", "   \n ", "just prose", "// only a comment"):
        with pytest.raises(NoJSONFoundError):
            repair_json(text)


def test_offsets_are_code_points() -> None:
    r = repair_json('{"é": 1,}')
    tc = next(x for x in r.repairs if x.kind == "trailing_comma")
    assert tc.at == 7


def test_repair_is_deterministic() -> None:
    text = "{a: 'x', b: [1, 2,], c: None} // tail"
    first = repair_json(text)
    second = repair_json(text)
    assert first == second


def test_never_crashes_on_truncated_prefixes() -> None:
    full = '{"users": [{"name": "Ann", "tags": ["a", "b"], "meta": {"n": 1}}, {"name": "Bo"}]}'
    for i in range(1, len(full) + 1):
        try:
            result = repair_json(full[:i])
        except NoJSONFoundError:
            continue
        # Any prefix that parses must round-trip to importable data.
        assert isinstance(result.repairs, tuple)


CORPUS = {
    "trailing_comma": '{"a": 1, "b": 2,}',
    "single_quotes": "{'intent': 'cancel'}",
    "unquoted_keys": "{intent: 1, score: 2}",
    "python_literals": '{"ok": True, "no": False, "v": None}',
    "comments": '{\n  // intent\n  "a": 1 /* inline */\n}',
    "nan_infinity": '{"a": NaN, "b": Infinity, "c": -Infinity}',
    "bom": '﻿{"a": 1}',
    "duplicate_keys": '{"a": 1, "a": 2, "a": 3}',
    "leading_zeros": "[007, -042, 0, 0.5]",
    "control_chars": '{"a": "line1\nline2"}',
    "truncated_object": '{"a": 1, "b": {"c": 2',
    "truncated_array": "[1, 2, 3",
    "truncated_dangling_key": '{"a": 1, "b":',
    "kitchen_sink": "{a: 'x', b: [1, 2,], c: None, d: NaN,}",
}


def _as_data(text: str) -> dict:
    r = repair_json(text)
    return {
        "value": r.value,
        "incomplete": r.incomplete,
        "repairs": [{"kind": x.kind, "at": x.at, "detail": x.detail} for x in r.repairs],
    }


@pytest.mark.parametrize("case", sorted(CORPUS))
def test_snapshot_corpus(case: str) -> None:
    text = CORPUS[case]
    assert_snapshot(f"repair_json/{case}", _as_data(text), input={"text": text})
