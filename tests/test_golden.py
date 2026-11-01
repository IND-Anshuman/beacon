from __future__ import annotations

from pathlib import Path

import pytest

from beacon import SnapshotMismatchError, extract_json
from beacon.snapshots import assert_golden

CASES = {
    "fence": '```json\n{"a": 1}\n```',
    "inline": 'here: {"b": 2} done',
    "no_json": "just some prose",  # fn raises -> captured as an error outcome
}


def test_writes_then_matches_whole_corpus(tmp_path: Path) -> None:
    assert_golden("extract", extract_json, CASES, directory=tmp_path, mode="new")
    assert (tmp_path / "extract" / "fence.yaml").exists()
    assert (tmp_path / "extract" / "no_json.yaml").exists()
    # second run compares in check mode and passes
    assert_golden("extract", extract_json, CASES, directory=tmp_path, mode="check")


def test_missing_in_check_mode_is_a_gate(tmp_path: Path) -> None:
    with pytest.raises(SnapshotMismatchError):
        assert_golden("extract", extract_json, CASES, directory=tmp_path, mode="check")


def test_change_fails_and_reports_the_cases(tmp_path: Path) -> None:
    assert_golden("g", str.upper, {"a": "hi", "b": "yo"}, directory=tmp_path, mode="new")
    with pytest.raises(SnapshotMismatchError) as exc:
        assert_golden("g", str.lower, {"a": "hi", "b": "yo"}, directory=tmp_path, mode="check")
    msg = str(exc.value)
    assert exc.value.code == "golden.mismatch"
    assert "2 of 2" in msg and "a" in msg and "b" in msg


def test_errors_are_captured_deterministically(tmp_path: Path) -> None:
    # extract_json raises on "no_json"; the error outcome is snapshotted and
    # matches on re-run.
    assert_golden("e", extract_json, {"nojson": "prose"}, directory=tmp_path, mode="new")
    assert_golden("e", extract_json, {"nojson": "prose"}, directory=tmp_path, mode="check")
