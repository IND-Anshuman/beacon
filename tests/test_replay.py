from __future__ import annotations

from pathlib import Path

import pytest

from beacon.replay import Cassette


def completion(content: str) -> dict:
    return {"choices": [{"message": {"content": content, "role": "assistant"}}]}


def test_record_then_replay_calls_provider_once(tmp_path: Path) -> None:
    path = tmp_path / "tape.json"
    request = {"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]}
    calls = {"n": 0}

    def call() -> dict:
        calls["n"] += 1
        return completion('{"intent": "cancel"}')

    tape = Cassette(path)  # auto
    first = tape.play(request, call)
    second = tape.play(request, call)
    assert first == second == completion('{"intent": "cancel"}')
    assert calls["n"] == 1  # recorded once, replayed thereafter
    assert path.exists() and request in tape


def test_key_is_order_independent(tmp_path: Path) -> None:
    tape = Cassette(tmp_path / "t.json")
    assert tape.key({"a": 1, "b": 2}) == tape.key({"b": 2, "a": 1})
    assert tape.key({"a": 1}) != tape.key({"a": 2})


def test_replay_mode_never_calls_and_raises_on_miss(tmp_path: Path) -> None:
    path = tmp_path / "tape.json"
    request = {"model": "m", "messages": []}
    Cassette(path).play(request, lambda: completion("{}"))  # record it

    replay = Cassette(path, mode="replay")
    assert replay.play(request, lambda: pytest.fail("must not call in replay")) == completion("{}")
    with pytest.raises(LookupError):
        replay.play({"model": "m", "messages": [{"role": "user", "content": "new"}]}, lambda: completion("{}"))


def test_persists_across_instances(tmp_path: Path) -> None:
    path = tmp_path / "tape.json"
    request = {"model": "m", "messages": [{"role": "user", "content": "q"}]}
    Cassette(path).play(request, lambda: completion('{"ok": true}'))

    reopened = Cassette(path, mode="replay")
    assert len(reopened) == 1
    assert reopened.play(request, lambda: pytest.fail("should replay")) == completion('{"ok": true}')


def test_record_mode_always_calls(tmp_path: Path) -> None:
    path = tmp_path / "tape.json"
    request = {"model": "m", "messages": []}
    Cassette(path).play(request, lambda: completion("{}"))
    calls = {"n": 0}

    def call() -> dict:
        calls["n"] += 1
        return completion('{"fresh": true}')

    rec = Cassette(path, mode="record")
    assert rec.play(request, call) == completion('{"fresh": true}')
    assert calls["n"] == 1  # re-recorded despite an existing entry


def test_env_var_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BEACON_CASSETTE_MODE", "replay")
    with pytest.raises(LookupError):
        Cassette(tmp_path / "none.json").play({"a": 1}, lambda: {})
