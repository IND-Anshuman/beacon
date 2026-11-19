"""Streaming engine: committed-item streaming and chunk-boundary invariance."""

from __future__ import annotations

import asyncio
import json

import pytest

import beacon
from beacon import (
    StreamParser,
    StreamRedactor,
    StreamToolCalls,
    parse_tool_calls,
    redact,
    stream_json,
    stream_redact,
    stream_tool_calls,
)

# ---------------------------------------------------------------- unit tests


def test_array_elements_commit_in_order() -> None:
    assert list(stream_json(["[1, 2", "3, 4", "5]"])) == [1, 23, 45]


def test_object_members_commit_as_key_value_pairs() -> None:
    assert list(stream_json(['{"a": 1, ', '"b": 2}'])) == [("a", 1), ("b", 2)]


def test_scalar_commits_only_at_close() -> None:
    # '4' then '2' must not emit 4 — a bare number has no delimiter
    assert list(stream_json(["4", "2"])) == [42]


def test_top_level_string_commits_at_close() -> None:
    assert list(stream_json(['"he', 'llo"'])) == ["hello"]


def test_nested_element_commits_as_a_whole() -> None:
    chunks = ['[{"id": 1, "n', 'ame": "a"}, {"id": 2, "name": "b"}]']
    assert list(stream_json(chunks)) == [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]


def test_empty_container_yields_nothing() -> None:
    assert list(stream_json(["[]"])) == []
    assert list(stream_json(["{}"])) == []


def test_truncated_container_flushes_tail_on_close() -> None:
    # stream ends mid-array; what arrived is final
    assert list(stream_json(["[1, 2, 3"])) == [1, 2, 3]


def test_streamparser_value_complete_consumed() -> None:
    sp = StreamParser()
    u1 = sp.feed('{"a": 1')
    assert u1.value == {"a": 1} and u1.complete is False
    assert u1.committed == ()
    u2 = sp.feed("}")
    assert u2.complete is True
    assert u2.committed == (("a", 1),)
    assert sp.value == {"a": 1} and sp.complete is True and sp.consumed == len('{"a": 1}')


def test_close_is_idempotent() -> None:
    sp = StreamParser()
    fed = sp.feed("[1, 2]")  # a complete array commits on feed
    assert fed.committed == (1, 2)
    assert sp.close().committed == ()  # nothing left to flush
    assert sp.close().committed == ()  # and closing again is a no-op


def test_feed_after_close_raises() -> None:
    sp = StreamParser()
    sp.close()
    with pytest.raises(ValueError):
        sp.feed("x")


def test_non_str_chunk_raises() -> None:
    sp = StreamParser()
    with pytest.raises(TypeError):
        sp.feed(b"bytes")  # type: ignore[arg-type]


def test_each_item_is_emitted_exactly_once() -> None:
    sp = StreamParser()
    seen: list = []
    for ch in "[1, 2, 3, 4]":
        seen += sp.feed(ch).committed
    seen += sp.close().committed
    assert seen == [1, 2, 3, 4]


# ---------------------------------------------------------------- async parity


def test_async_stream_matches_sync() -> None:
    chunks = ["[1, 2", "3, 4", "5]"]

    async def gen():
        for c in chunks:
            yield c

    async def run():
        return [x async for x in beacon.aio.stream_json(gen())]

    assert asyncio.run(run()) == list(stream_json(chunks))


# ---------------------------------------------------------------- fuzz

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

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


@given(json_values, st.data())
@settings(max_examples=300)
def test_chunk_boundary_invariance(value, data) -> None:
    s = json.dumps(value)
    baseline = list(stream_json([s]))
    # a randomly-sized even split...
    size = data.draw(st.integers(min_value=1, max_value=len(s)))
    even = [s[i : i + size] for i in range(0, len(s), size)]
    assert list(stream_json(even)) == baseline
    # ...and the finest possible split: one character per chunk
    assert list(stream_json(list(s))) == baseline


@given(json_values)
@settings(max_examples=300)
def test_final_value_round_trips(value) -> None:
    s = json.dumps(value)
    sp = StreamParser()
    for ch in s:  # feed one character at a time
        sp.feed(ch)
    sp.close()
    assert sp.value == json.loads(s)


@given(st.lists(json_values, max_size=6))
@settings(max_examples=200)
def test_array_stream_equals_the_list(items) -> None:
    s = json.dumps(items)
    assert list(stream_json([s])) == items
    assert list(stream_json(list(s))) == items  # char-by-char, same result


@given(st.dictionaries(_jtext, json_values, max_size=6))
@settings(max_examples=200)
def test_object_stream_equals_the_members(obj) -> None:
    s = json.dumps(obj)
    assert list(stream_json(list(s))) == list(obj.items())


# ---------------------------------------------------------------- streaming redaction


def test_stream_redact_joins_to_batch_redaction() -> None:
    out = "".join(stream_redact(["my email is al", "ice@example.com now"]))
    assert out == "my email is [REDACTED:email] now"
    assert out == redact("my email is alice@example.com now")


def test_secret_split_across_boundary_is_never_emitted_raw() -> None:
    text = "reach me at alice@example.com please"
    # the finest split cannot leak any prefix of the email
    pieces = list(stream_redact(list(text)))
    out = "".join(pieces)
    assert out == redact(text)
    assert "alice@example.com" not in out
    # no emitted piece ever contains an '@' from the raw address
    assert not any("alice" in p for p in pieces)


def test_redactor_feed_after_close_raises() -> None:
    r = StreamRedactor()
    r.close()
    with pytest.raises(ValueError):
        r.feed("x")


def test_redactor_non_str_raises() -> None:
    with pytest.raises(TypeError):
        StreamRedactor().feed(b"bytes")  # type: ignore[arg-type]


def test_redactor_bad_max_secret_len() -> None:
    with pytest.raises(ValueError):
        StreamRedactor(max_secret_len=0)


def test_redactor_passes_options_through() -> None:
    text = "ip 10.0.0.1 and mail a@b.io"
    out = "".join(stream_redact(list(text), policy="strict", replacement="X"))
    assert out == redact(text, policy="strict", replacement="X")
    assert "10.0.0.1" not in out


# a token stream: ordinary words interleaved with real secrets
_WORDS = ["hello", "the", "user", "wrote", "please", "contact", "at", "or", "and", "info"]
_SECRETS = ["alice@example.com", "bob.smith@test.org", "123-45-6789", "x@y.io"]
_tokens = st.lists(st.sampled_from(_WORDS + _SECRETS), min_size=1, max_size=30)


@given(_tokens, st.data())
@settings(max_examples=300)
def test_stream_redaction_equals_batch_for_any_split(tokens, data) -> None:
    text = " ".join(tokens)
    batch = redact(text)
    size = data.draw(st.integers(min_value=1, max_value=len(text)))
    parts = [text[i : i + size] for i in range(0, len(text), size)]
    assert "".join(stream_redact(parts)) == batch
    assert "".join(stream_redact(list(text))) == batch  # one char at a time


def test_async_stream_redact_matches_sync() -> None:
    chunks = ["send to ali", "ce@example.com and 123-45", "-6789 done"]

    async def gen():
        for c in chunks:
            yield c

    async def run():
        return [p async for p in beacon.aio.stream_redact(gen())]

    assert "".join(asyncio.run(run())) == "".join(stream_redact(chunks))
    assert "".join(stream_redact(chunks)) == redact("".join(chunks))


# ---------------------------------------------------------------- streaming tool calls


def test_single_tool_call_emits_when_complete() -> None:
    assert list(stream_tool_calls(["search(query=", '"rust")'])) == [
        {"name": "search", "arguments": {"query": "rust"}}
    ]


def test_tool_call_not_emitted_until_complete() -> None:
    det = StreamToolCalls()
    assert det.feed('search(query="ru') == []  # still open
    assert det.feed('st")') == [{"name": "search", "arguments": {"query": "rust"}}]
    assert det.close() == []


def test_multiple_tool_calls_stream_in_order() -> None:
    chunks = ['search(a=1) ', 'lookup(b=', '2) ', 'fetch(c=3)']
    out = list(stream_tool_calls(chunks))
    assert out == [
        {"name": "search", "arguments": {"a": 1}},
        {"name": "lookup", "arguments": {"b": 2}},
        {"name": "fetch", "arguments": {"c": 3}},
    ]


def test_json_and_hermes_formats() -> None:
    hermes = '<tool_call>{"name": "f", "arguments": {"x": 1}}</tool_call>'
    assert list(stream_tool_calls(list(hermes))) == [{"name": "f", "arguments": {"x": 1}}]
    j = '{"name": "g", "arguments": {"y": 2}}'
    assert list(stream_tool_calls(list(j))) == [{"name": "g", "arguments": {"y": 2}}]


def test_include_format() -> None:
    out = list(stream_tool_calls(['search(q="x")'], include_format=True))
    assert out[0]["name"] == "search" and out[0]["format"] == "python"


def test_tool_feed_after_close_raises() -> None:
    det = StreamToolCalls()
    det.close()
    with pytest.raises(ValueError):
        det.feed("x")


def test_tool_non_str_raises() -> None:
    with pytest.raises(TypeError):
        StreamToolCalls().feed(b"bytes")  # type: ignore[arg-type]


def test_async_stream_tool_calls_matches_sync() -> None:
    chunks = ['think... search(q=', '"rust") then ', 'lookup(id=5)']

    async def gen():
        for c in chunks:
            yield c

    async def run():
        return [c async for c in beacon.aio.stream_tool_calls(gen())]

    assert asyncio.run(run()) == list(stream_tool_calls(chunks))


# A model emits one tool-call format, so a real stream is single-format
# (parse_tool_calls does global format detection). We fuzz each format on its own.
_FORMAT_POOLS = [
    ['search(query="rust", limit=5)', "ping()", "lookup(id=7)"],  # python syntax
    [
        '<tool_call>{"name": "f", "arguments": {"x": 1}}</tool_call>',
        '<tool_call>{"name": "g", "arguments": {"y": [1, 2]}}</tool_call>',
    ],  # hermes
    ['{"name": "a", "arguments": {"n": 1}}', '{"name": "b", "arguments": {}}'],  # bare json
]


@st.composite
def _single_format_stream(draw):
    pool = draw(st.sampled_from(_FORMAT_POOLS))
    calls = draw(st.lists(st.sampled_from(pool), min_size=1, max_size=5))
    joiner = draw(st.sampled_from([" ", "\n", " then "]))
    return joiner.join(calls)


@given(_single_format_stream(), st.data())
@settings(max_examples=300)
def test_stream_tool_calls_equals_batch_for_any_split(text, data) -> None:
    try:
        batch = parse_tool_calls(text)
    except (beacon.BeaconError, ValueError, TypeError):
        return  # the contract is for text that parses cleanly as a whole
    size = data.draw(st.integers(min_value=1, max_value=len(text)))
    parts = [text[i : i + size] for i in range(0, len(text), size)]
    # any split yields exactly the batch result, in order (invariance + soundness:
    # a partial call wrongly emitted would diverge from the batch here)
    assert list(stream_tool_calls(parts)) == batch
    assert list(stream_tool_calls(list(text))) == batch  # one char at a time
