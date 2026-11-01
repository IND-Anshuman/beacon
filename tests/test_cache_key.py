from __future__ import annotations

import pytest

from beacon import cache_key


def test_deterministic_and_stable_length() -> None:
    k = cache_key("You are a helpful assistant.", [{"name": "search"}])
    assert k == cache_key("You are a helpful assistant.", [{"name": "search"}])
    assert len(k) == 32 and all(c in "0123456789abcdef" for c in k)


def test_part_order_is_significant() -> None:
    assert cache_key("sys", ["a", "b"]) != cache_key("sys", ["b", "a"])
    assert cache_key("a", "b") != cache_key("b", "a")
    assert cache_key("a", "b") != cache_key("ab")  # structure matters, not concatenation


def test_dict_key_order_within_a_part_is_not_significant() -> None:
    assert cache_key({"a": 1, "b": 2}) == cache_key({"b": 2, "a": 1})


def test_length_option() -> None:
    assert len(cache_key("x", length=16)) == 16
    assert len(cache_key("x", length=64)) == 64


def test_requires_at_least_one_part() -> None:
    with pytest.raises(ValueError):
        cache_key()


def test_different_content_differs() -> None:
    assert cache_key("system v1") != cache_key("system v2")
