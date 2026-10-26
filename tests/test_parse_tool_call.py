from __future__ import annotations

import json

import pytest

from beacon import MalformedOutputError, NoToolCallFoundError, parse_tool_call, parse_tool_calls
from beacon.snapshots import assert_snapshot
from conftest import outcome

SEARCH = {"name": "search", "arguments": {"q": "rust"}}


def test_python_call_syntax() -> None:
    assert parse_tool_call('Call: search(query="rust async", limit=5)') == {
        "name": "search",
        "arguments": {"query": "rust async", "limit": 5},
    }


def test_bracket_format() -> None:
    assert parse_tool_call('[TOOL_CALL]name=search;args={"q":"rust"}[/TOOL_CALL]') == SEARCH
    assert parse_tool_call('[TOOL_CALL]{"name": "search", "arguments": {"q": "rust"}}[/TOOL_CALL]') == SEARCH


def test_plain_json() -> None:
    assert parse_tool_call('{"name": "search", "arguments": {"q": "rust"}}') == SEARCH


@pytest.mark.parametrize(
    "text,fmt",
    [
        ('<tool_call>\n{"name": "search", "arguments": {"q": "rust"}}\n</tool_call>', "hermes"),
        ('[TOOL_CALLS] [{"name": "search", "arguments": {"q": "rust"}}]', "mistral"),
        ('[TOOL_CALLS]search[ARGS]{"q": "rust"}', "mistral"),
        ('[TOOL_CALLS]search[CALL_ID]abc123[ARGS]{"q": "rust"}', "mistral"),
        ('<|python_tag|>{"name": "search", "parameters": {"q": "rust"}}<|eom_id|>', "llama"),
        ('<invoke name="search">\n<parameter name="q">rust</parameter>\n</invoke>', "xml_invoke"),
        ('<function_calls><invoke name="search"><parameter name="q">rust</parameter></invoke></function_calls>', "xml_invoke"),
        ('```json\n{"name": "search", "arguments": {"q": "rust"}}\n```', "json"),
        ('{"type": "tool_use", "id": "toolu_1", "name": "search", "input": {"q": "rust"}}', "json"),
        ('{"id": "call_1", "type": "function", "function": {"name": "search", "arguments": "{\\"q\\": \\"rust\\"}"}}', "json"),
        ('{"function_call": {"name": "search", "arguments": "{\\"q\\": \\"rust\\"}"}}', "json"),
        ('{"tool_calls": [{"function": {"name": "search", "arguments": {"q": "rust"}}}]}', "json"),
        ('{"name": "search", "args": {"q": "rust"}}', "json"),
        ("search(q='rust')", "python"),
    ],
)
def test_vendor_formats(text: str, fmt: str) -> None:
    calls = parse_tool_calls(text, include_format=True)
    assert calls == [{**SEARCH, "format": fmt}]


def test_python_literals() -> None:
    call = parse_tool_call("f(a='x', b=\"y\", c=True, d=None, e=false, g=null, h=[1, 'two'], i={'k': (1, 2)}, j=-1.5e3,)")
    assert call["arguments"] == {
        "a": "x",
        "b": "y",
        "c": True,
        "d": None,
        "e": False,
        "g": None,
        "h": [1, "two"],
        "i": {"k": [1, 2]},
        "j": -1500.0,
    }


def test_python_string_escapes() -> None:
    call = parse_tool_call(r"f(s='it\'s \"q\" \n é \x41')")
    assert call["arguments"]["s"] == "it's \"q\" \n é A"


def test_no_argument_call() -> None:
    assert parse_tool_call("Calling get_time() now") == {"name": "get_time", "arguments": {}}


def test_dotted_names() -> None:
    assert parse_tool_call('<|python_tag|>brave_search.call(query="x")')["name"] == "brave_search.call"


def test_json_missing_arguments_with_tool_use_type() -> None:
    assert parse_tool_call('{"type": "tool_use", "name": "now"}') == {"name": "now", "arguments": {}}


def test_multiple_calls() -> None:
    text = (
        '<tool_call>{"name": "a", "arguments": {}}</tool_call>\n'
        '<tool_call>{"name": "b", "arguments": {"x": 1}}</tool_call>'
    )
    assert [c["name"] for c in parse_tool_calls(text)] == ["a", "b"]
    with pytest.raises(MalformedOutputError) as exc:
        parse_tool_call(text)
    assert exc.value.code == "tool_call.multiple"


def test_mistral_list_of_calls() -> None:
    text = '[TOOL_CALLS] [{"name": "a", "arguments": {}}, {"name": "b", "arguments": {}}]'
    assert [c["name"] for c in parse_tool_calls(text)] == ["a", "b"]


def test_openai_arguments_string_is_parsed_strictly() -> None:
    with pytest.raises(MalformedOutputError) as exc:
        parse_tool_call('{"name": "f", "arguments": "{\'q\': 1}"}')
    assert exc.value.code == "tool_call.invalid_arguments"


def test_arguments_must_be_object() -> None:
    with pytest.raises(MalformedOutputError) as exc:
        parse_tool_call('{"name": "f", "arguments": [1, 2]}')
    assert exc.value.code == "tool_call.invalid_arguments"


def test_ambiguous_argument_keys() -> None:
    with pytest.raises(MalformedOutputError) as exc:
        parse_tool_call('{"name": "f", "arguments": {}, "parameters": {}}')
    assert exc.value.code == "tool_call.ambiguous_arguments"


def test_empty_name() -> None:
    with pytest.raises(MalformedOutputError) as exc:
        parse_tool_call('{"name": "", "arguments": {}}')
    assert exc.value.code == "tool_call.invalid_name"


@pytest.mark.parametrize(
    "text,code",
    [
        ("search(q=1, 5)", "tool_call.positional_argument"),
        ("search(q=1, q=2)", "tool_call.duplicate_argument"),
        ("search(q='unterminated)", "tool_call.unterminated_string"),
        ("search(q=undefined_name)", "tool_call.expected_value"),
        ("search(q=1 r=2)", "tool_call.expected_comma"),
        ("search(q={1: 2})", "tool_call.expected_key"),
        ('<tool_call>{"name": "f", "arguments": {}</tool_call>', "json.unexpected_end"),
        ("<tool_call>not json</tool_call>", "json.invalid_literal"),
        ("<tool_call>[1, 2]</tool_call>", "tool_call.unrecognized"),
        ('<tool_call>{"hello": "world"}</tool_call>', "tool_call.unrecognized"),
        ("[TOOL_CALL]garbage[/TOOL_CALL]", "tool_call.unrecognized"),
        ('{"name": "search", "arguments": {"q": "rust"', "json.unexpected_end"),
        ('<invoke name="">x</invoke>', "tool_call.invalid_name"),
        ("[TOOL_CALLS]search{}", "tool_call.unrecognized"),
    ],
)
def test_malformed_calls_raise_with_position(text: str, code: str) -> None:
    with pytest.raises(MalformedOutputError) as exc:
        parse_tool_call(text)
    assert exc.value.code == code
    assert exc.value.position is not None


@pytest.mark.parametrize(
    "text",
    [
        "Just a normal answer.",
        "",
        '{"name": "Alice", "age": 3}',
        '{"answer": 42}',
        "Use f(x) to compute it.",
        "print('hello')",
    ],
)
def test_no_tool_call(text: str) -> None:
    with pytest.raises(NoToolCallFoundError) as exc:
        parse_tool_call(text)
    assert exc.value.code == "tool_call.not_found"


def test_tagged_formats_take_priority_over_json() -> None:
    text = 'Example: {"name": "x", "arguments": {}}\n<tool_call>{"name": "real", "arguments": {}}</tool_call>'
    assert parse_tool_call(text)["name"] == "real"


def test_argument_order_is_preserved() -> None:
    call = parse_tool_call('{"name": "f", "arguments": {"z": 1, "a": 2, "m": 3}}')
    assert list(call["arguments"]) == ["z", "a", "m"]


def test_unicode_arguments() -> None:
    call = parse_tool_call('translate(text="こんにちは 🌸", to="fr")')
    assert call["arguments"]["text"] == "こんにちは 🌸"


def test_round_trip_through_json_dumps() -> None:
    call = {"name": "book", "arguments": {"when": "2026-01-01", "seats": 2, "vip": False}}
    assert parse_tool_call(json.dumps(call)) == call


CORPUS = {
    "python_kwargs": 'Call: search(query="rust async", limit=5)',
    "python_no_args": "I'll call get_time()",
    "python_nested_literals": "plot(xs=[1, 2, 3], style={'color': 'red', 'dash': None})",
    "python_positional": "search('rust')",
    "bracket_kv": '[TOOL_CALL]name=search;args={"q":"rust"}[/TOOL_CALL]',
    "bracket_json": '[TOOL_CALL]{"name": "search", "arguments": {"q": "rust"}}[/TOOL_CALL]',
    "hermes": '<tool_call>\n{"name": "get_weather", "arguments": {"city": "Paris"}}\n</tool_call>',
    "hermes_two_calls": '<tool_call>{"name": "a", "arguments": {}}</tool_call><tool_call>{"name": "b", "arguments": {}}</tool_call>',
    "hermes_truncated": '<tool_call>{"name": "get_weather", "arguments": {"city": "Par',
    "mistral_list": '[TOOL_CALLS] [{"name": "get_weather", "arguments": {"city": "Paris"}}]',
    "mistral_v11": '[TOOL_CALLS]get_weather[ARGS]{"city": "Paris"}',
    "llama_json": '<|python_tag|>{"name": "get_weather", "parameters": {"city": "Paris"}}<|eom_id|>',
    "llama_builtin": '<|python_tag|>brave_search.call(query="weather in Paris")<|eom_id|>',
    "xml_invoke": '<function_calls>\n<invoke name="get_weather">\n<parameter name="city">Paris</parameter>\n<parameter name="days">3</parameter>\n</invoke>\n</function_calls>',
    "openai_tool_call_item": '{"id": "call_abc", "type": "function", "function": {"name": "get_weather", "arguments": "{\\"city\\": \\"Paris\\"}"}}',
    "openai_message_tool_calls": '{"role": "assistant", "content": null, "tool_calls": [{"id": "1", "type": "function", "function": {"name": "a", "arguments": "{}"}}, {"id": "2", "type": "function", "function": {"name": "b", "arguments": "{\\"x\\": 1}"}}]}',
    "anthropic_tool_use": '{"type": "tool_use", "id": "toolu_01", "name": "get_weather", "input": {"city": "Paris"}}',
    "json_in_fence": 'I will call:\n```json\n{"name": "get_weather", "arguments": {"city": "Paris"}}\n```',
    "json_bad_arguments_string": '{"name": "f", "arguments": "{not json}"}',
    "plain_answer": "The weather in Paris is sunny.",
    "data_not_call": '{"name": "Alice", "email": "alice@example.com"}',
}


@pytest.mark.parametrize("case", sorted(CORPUS))
def test_snapshot_corpus(case: str) -> None:
    text = CORPUS[case]
    assert_snapshot(f"parse_tool_call/{case}", outcome(parse_tool_calls, text, include_format=True), input=text)
