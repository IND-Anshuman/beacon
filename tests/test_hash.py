from __future__ import annotations

import enum
import math

import pytest

from beacon import hash_content, normalize
from beacon.snapshots import assert_snapshot

# Pinned digests live in snapshots/hash/pinned_digests.yaml. They must be
# identical on every OS, Python version and CPU; a change means the canonical
# encoding changed, which is a major-version change.
PINNED = {
    "null": None,
    "true": True,
    "int": 42,
    "float": 0.9,
    "str": "hello",
    "intent": {"intent": "cancel", "confidence": 0.9},
}


def test_key_order_does_not_matter() -> None:
    assert hash_content({"a": 1, "b": 2}) == hash_content({"b": 2, "a": 1})
    nested_a = {"x": {"p": [1, {"q": 1, "r": 2}]}, "y": None}
    nested_b = {"y": None, "x": {"p": [1, {"r": 2, "q": 1}]}}
    assert hash_content(nested_a) == hash_content(nested_b)


def test_list_order_matters() -> None:
    assert hash_content([1, 2, 3]) != hash_content([3, 2, 1])


def test_type_aware() -> None:
    values = [1, 1.0, True, "1", [1], {"0": 1}, None, 0, 0.0, -0.0, False, "", [], {}, b"1", (1, 2)]
    digests = [hash_content(v) for v in values[:-1]]
    assert len(set(digests)) == len(digests)


def test_list_equals_dict_with_index_keys_is_false() -> None:
    assert hash_content([1, 2, 3]) != hash_content({"0": 1, "1": 2, "2": 3})


def test_tuple_hashes_like_list() -> None:
    assert hash_content((1, "a")) == hash_content([1, "a"])


def test_nan_is_canonical() -> None:
    assert hash_content(float("nan")) == hash_content(-math.nan) == hash_content(math.nan)


def test_big_ints() -> None:
    assert hash_content(10**40) == hash_content(10**40)
    assert hash_content(10**40) != hash_content(10**40 + 1)
    assert hash_content(-(10**40)) != hash_content(10**40)


def test_str_subclasses_hash_as_str() -> None:
    class Color(str, enum.Enum):
        RED = "red"

    assert hash_content(Color.RED) == hash_content("red")


def test_length() -> None:
    assert len(hash_content("x")) == 16
    assert len(hash_content("x", length=64)) == 64
    assert hash_content("x", length=8) == hash_content("x", length=64)[:8]
    for bad in (0, 65, -1):
        with pytest.raises(ValueError, match="length must be between 1 and 64"):
            hash_content("x", length=bad)
    with pytest.raises(TypeError):
        hash_content("x", length=True)


@pytest.mark.parametrize("bad", [{1, 2}, object(), 1j, {"a": {1: 2}}])
def test_unsupported_types(bad: object) -> None:
    with pytest.raises(TypeError):
        hash_content(bad)


def test_unicode_strings_are_hashed_as_utf8() -> None:
    assert hash_content("é") != hash_content("é")
    assert hash_content(normalize("é")) == hash_content(normalize("é"))


def test_deep_nesting_is_an_error_not_a_crash() -> None:
    value: object = []
    for _ in range(600):
        value = [value]
    with pytest.raises(ValueError, match="nested deeper"):
        hash_content(value)


def test_pinned_digests() -> None:
    actual = {name: hash_content(value) for name, value in PINNED.items()}
    assert_snapshot("hash/pinned_digests", actual)


CORPUS = {
    "empty_values": [None, "", [], {}, 0, 0.0, False],
    "llm_result": {"intent": "cancel", "confidence": 0.9, "entities": [{"type": "plan", "value": "pro"}]},
    "unicode": {"日本語": "テキスト", "emoji": "🎉", "rtl": "שלום"},
    "numbers": [1, -1, 1.5, -0.0, 1e300, 10**30, float("inf"), float("-inf")],
}


@pytest.mark.parametrize("case", sorted(CORPUS))
def test_snapshot_corpus(case: str) -> None:
    value = CORPUS[case]
    result = {"hash16": hash_content(value), "hash64": hash_content(value, length=64)}
    assert_snapshot(f"hash/{case}", result, input=repr(value))
