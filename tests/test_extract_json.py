from __future__ import annotations

import pytest

from beacon import (
    MalformedOutputError,
    NoJSONFoundError,
    SchemaValidationError,
    extract_json,
    extract_json_detailed,
)
from beacon.snapshots import assert_snapshot
from conftest import outcome

INTENT = {"intent": "cancel"}


# --------------------------------------------------------------------- basics


@pytest.mark.parametrize(
    "text",
    [
        'The user wants this: {"intent": "cancel"}',
        '```json\n{"intent": "cancel"}\n```',
        '```JSON\n{"intent": "cancel"}\n```',
        '```\n{"intent": "cancel"}\n```',
        '~~~json\n{"intent": "cancel"}\n~~~',
        '  ```json\n  {"intent": "cancel"}\n  ```',
        'Here is the JSON:\n{"intent": "cancel"}\nDone.',
        '{"intent": "cancel"}',
        '\n\n  {"intent": "cancel"}  \n',
        'Sure! ```json\n{"intent": "cancel"}\n``` Hope that helps.',
        'Result: {"intent": "cancel"}. Let me know if you need more.',
    ],
)
def test_finds_object_in_common_wrappers(text: str) -> None:
    assert extract_json(text) == INTENT


def test_multiline_object_with_preamble() -> None:
    text = 'Here is the JSON:\n{"intent": "cancel",\n "confidence": 0.9}\nDone.'
    assert extract_json(text) == {"intent": "cancel", "confidence": 0.9}


def test_nested_structures() -> None:
    assert extract_json('{"outer": {"inner": {"deep": [1, 2, 3]}}}') == {"outer": {"inner": {"deep": [1, 2, 3]}}}


def test_key_order_is_preserved() -> None:
    assert list(extract_json('{"z": 1, "a": 2, "m": 3}')) == ["z", "a", "m"]


def test_types_round_trip() -> None:
    value = extract_json('{"s": "x", "i": -7, "f": 2.5, "e": 1e3, "t": true, "f2": false, "n": null, "l": [], "o": {}}')
    assert value == {"s": "x", "i": -7, "f": 2.5, "e": 1000.0, "t": True, "f2": False, "n": None, "l": [], "o": {}}
    assert type(value["i"]) is int and type(value["e"]) is float


def test_big_integers_are_exact() -> None:
    assert extract_json("[123456789012345678901234567890]") == [123456789012345678901234567890]
    assert extract_json("[-99999999999999999999999]") == [-99999999999999999999999]


def test_unicode_and_escapes() -> None:
    assert extract_json('{"k": "caf\\u00e9 \\ud83d\\ude00 \\"q\\" \\n"}') == {"k": 'café 😀 "q" \n'}
    assert extract_json('{"日本": "語", "emoji": "🎉"}') == {"日本": "語", "emoji": "🎉"}


def test_braces_inside_strings_do_not_confuse_the_scanner() -> None:
    assert extract_json('{"code": "if (x) { return \\"}\\"; }"}') == {"code": 'if (x) { return "}"; }'}


def test_arrays() -> None:
    assert extract_json("Result: [1, 2, 3]") == [1, 2, 3]
    assert extract_json('[{"a": 1}, {"b": 2}]') == [{"a": 1}, {"b": 2}]


# --------------------------------------------------------------------- selection


def test_auto_kind_prefers_objects_over_citations() -> None:
    assert extract_json('According to [1] and [2], the answer is {"a": 1}') == {"a": 1}


@pytest.mark.parametrize(
    "select,expected",
    [("first", {"a": 1}), ("last", {"c": 3}), ("largest", {"bb": [1, 2, 3]})],
)
def test_select(select: str, expected: dict) -> None:
    text = '{"a": 1} then {"bb": [1, 2, 3]} then {"c": 3}'
    assert extract_json(text, select=select) == expected  # type: ignore[arg-type]


def test_select_only_rejects_multiple() -> None:
    with pytest.raises(MalformedOutputError) as exc:
        extract_json('{"a": 1} {"b": 2}', select="only")
    assert exc.value.code == "extract_json.multiple_candidates"
    assert exc.value.position == 9


def test_kind_filters() -> None:
    text = '[1, 2] and {"a": 1}'
    assert extract_json(text, kind="array") == [1, 2]
    assert extract_json(text, kind="object") == {"a": 1}
    assert extract_json(text, kind="any") == [1, 2]


def test_fences_win_over_prose_examples() -> None:
    text = 'For example {"x": 0} is wrong.\n```json\n{"real": 1}\n```'
    assert extract_json(text) == {"real": 1}


def test_non_json_fences_are_ignored() -> None:
    text = '```python\nprint({"not": "this"})\n```\nAnswer: {"a": 1}'
    # A python fence is not a JSON fence, so the whole text is scanned and the
    # first object found is inside the python fence.
    assert extract_json(text) == {"not": "this"}
    assert extract_json(text, select="last") == {"a": 1}


# --------------------------------------------------------------------- errors


def test_no_json_raises_by_default() -> None:
    with pytest.raises(NoJSONFoundError) as exc:
        extract_json("No JSON here at all")
    assert exc.value.code == "json.not_found"
    assert str(exc.value) == "no JSON object or array found in text"


def test_required_false_returns_none() -> None:
    assert extract_json("No JSON here at all", required=False) is None
    assert extract_json("", required=False) is None


def test_template_like_braces_are_not_json() -> None:
    assert extract_json("Hello {name}, see [note]", required=False) is None


def test_malformed_has_position() -> None:
    with pytest.raises(MalformedOutputError) as exc:
        extract_json('The user wants to {"intent": cancel')
    err = exc.value
    assert err.code == "json.expected_value"
    assert (err.position, err.line, err.column) == (29, 1, 30)
    assert str(err) == "expected a JSON value, found 'c' (line 1, column 30)"


@pytest.mark.parametrize(
    "text,code",
    [
        ('{"a": 1,}', "json.trailing_comma"),
        ("{'a': 1}", "json.expected_key"),
        ('{"a": [1, 2', "json.unexpected_end"),
        ('{"a": "unterminated', "json.unterminated_string"),
        ('{"a": NaN}', "json.expected_value"),
        ('{"a": 01}', "json.invalid_number"),
        ('{"a": 1, "a": 2}', "json.duplicate_key"),
        ('{"a": "x\ny"}', "json.control_character"),
        ('{"a": "\\q"}', "json.invalid_escape"),
        ('{"a": "\\ud800"}', "json.lone_surrogate"),
        ('{"a" 1}', "json.expected_colon"),
        ('{"a": 1 "b": 2}', "json.expected_comma"),
        ('{"a": tru}', "json.invalid_literal"),
        ('{"a": 1e999}', "json.number_out_of_range"),
        ('```json\n{"a": 1,}\n```', "json.trailing_comma"),
        ("```json\nnot json\n```", "json.expected_value"),
    ],
)
def test_strict_json_is_never_repaired(text: str, code: str) -> None:
    with pytest.raises(MalformedOutputError) as exc:
        extract_json(text)
    assert exc.value.code == code
    assert exc.value.position is not None


def test_truncated_response_does_not_return_inner_fragment() -> None:
    with pytest.raises(MalformedOutputError) as exc:
        extract_json('{"items": [{"a": 1}, {"b": 2}, {"c": ')
    assert exc.value.code == "json.unexpected_end"


def test_positions_count_code_points_not_bytes() -> None:
    with pytest.raises(MalformedOutputError) as exc:
        extract_json('日本語 {"a": x}')
    assert exc.value.position == 10
    assert '日本語 {"a": x}'[exc.value.position] == "x"


def test_deep_nesting_is_an_error_not_a_crash() -> None:
    with pytest.raises(MalformedOutputError) as exc:
        extract_json("[" * 600 + "]" * 600)
    assert exc.value.code == "json.too_deep"


def test_invalid_arguments() -> None:
    with pytest.raises(ValueError, match="select must be"):
        extract_json("{}", select="biggest")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="kind must be"):
        extract_json("{}", kind="dict")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="text must be str"):
        extract_json(b"{}")  # type: ignore[arg-type]


def test_schema_validation_is_applied() -> None:
    schema = {"type": "object", "required": ["intent", "confidence"]}
    with pytest.raises(SchemaValidationError) as exc:
        extract_json('{"intent": "cancel"}', schema=schema)
    assert exc.value.errors == [
        {"path": "", "keyword": "required", "message": 'missing required property "confidence"'}
    ]


# --------------------------------------------------------------------- detailed


def test_detailed_reports_span_and_source() -> None:
    text = 'Sure:\n```json\n{"a": 1}\n```'
    d = extract_json_detailed(text)
    assert d.value == {"a": 1}
    assert d.source == "fence"
    assert text[d.start : d.end] == '{"a": 1}'
    assert extract_json_detailed('  {"a": 1} ').source == "whole"
    assert extract_json_detailed('x {"a": 1} y').source == "inline"
    assert extract_json_detailed('{"a": 1} {"b": 2}').candidates == 2


def test_same_input_same_output_many_times() -> None:
    text = 'noise {"b": [1, {"c": "d"}], "a": 0.1} more'
    first = extract_json(text)
    assert all(extract_json(text) == first for _ in range(200))


# --------------------------------------------------------------------- snapshots

CORPUS = {
    "markdown_fence_basic": 'Here\'s the answer:\n```json\n{"intent": "cancel", "confidence": 0.9}\n```\nHope that helps!',
    "trailing_prose_basic": 'The result is {"intent": "cancel", "confidence": 0.9}. Let me know if you need more.',
    "nested_object": 'Output: {"user": {"name": "Alice", "prefs": {"theme": "dark"}}}',
    "bare_object": '{"intent": "refund"}',
    "bare_array": '["a", "b", "c"]',
    "array_of_objects": '[{"id": 1}, {"id": 2}]',
    "unlabelled_fence": 'Sure:\n```\n{"ok": true}\n```',
    "tilde_fence": '~~~json\n{"ok": true}\n~~~',
    "indented_fence": '   ```json\n   {"ok": true}\n   ```',
    "unclosed_fence_valid": '```json\n{"ok": true}\n',
    "unclosed_fence_truncated": '```json\n{"ok": tr',
    "two_fences": '```json\n{"a": 1}\n```\nand\n```json\n{"b": 2}\n```',
    "fence_and_prose_example": 'E.g. {"x": 0}\n```json\n{"real": 1}\n```',
    "citations_then_object": 'Per [1], [2] and [3]: {"answer": 42}',
    "citations_only": "Sources: [1] [2]",
    "multiple_objects": '{"a": 1} and then {"b": 2}',
    "unicode_keys": '{"città": "Roma", "emoji": "🎉", "rtl": "שלום"}',
    "escaped_strings": '{"path": "C:\\\\Users", "quote": "\\"hi\\"", "nl": "a\\nb"}',
    "big_integer": '{"id": 123456789012345678901234567890}',
    "floats": '{"a": 0.1, "b": 1e-7, "c": 1.5e+300, "d": -0.0}',
    "empty_containers": '{"a": {}, "b": []}',
    "deeply_nested": '{"a": {"b": {"c": {"d": {"e": [[[1]]]}}}}}',
    "template_braces_then_json": 'Fill {name} and {date}. Data: {"filled": true}',
    "json_in_sentence_with_braces": 'Use the {} operator. {"op": "{}"}',
    "no_json": "I could not determine the intent.",
    "empty_string": "",
    "only_whitespace": "   \n\t ",
    "truncated_object": '{"intent": "cancel", "confid',
    "truncated_nested": '{"items": [{"a": 1}, {"b": 2}, {"c": ',
    "trailing_comma": '{"a": 1, "b": 2,}',
    "single_quotes": "{'intent': 'cancel'}",
    "unquoted_value": 'The user wants to {"intent": cancel',
    "python_literals": '{"ok": True, "v": None}',
    "comment_in_json": '{"a": 1 // one\n}',
    "nan_value": '{"score": NaN}',
    "duplicate_keys": '{"a": 1, "a": 2}',
    "literal_newline_in_string": '{"text": "line1\nline2"}',
    "lone_surrogate": '{"s": "\\udc00"}',
    "leading_zero": '{"n": 007}',
    "multiline_preamble": 'Thinking...\nStep 1: parse.\nStep 2: answer.\n\n{"intent": "question",\n "confidence": 0.42}\n\nDone.',
    "json_fence_with_language_suffix": '```json title="out"\n{"a": 1}\n```',
    "crlf_line_endings": '```json\r\n{"a": 1}\r\n```',
}


@pytest.mark.parametrize("case", sorted(CORPUS))
def test_snapshot_corpus(case: str) -> None:
    text = CORPUS[case]
    result = outcome(extract_json_detailed, text)
    assert_snapshot(f"extract_json/{case}", result, input=text)
