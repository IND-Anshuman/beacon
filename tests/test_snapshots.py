from __future__ import annotations

import dataclasses
import enum
import math
import subprocess
import sys
from pathlib import Path

import pytest

from beacon import MalformedOutputError, SnapshotMismatchError, _yaml, extract_json
from beacon.snapshots import (
    Snapshot,
    assert_snapshot,
    configure,
    main,
    render_snapshot,
    snapshot_test,
    to_snapshot_data,
)

yaml = pytest.importorskip("yaml")


@pytest.fixture
def snapdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A temp snapshot dir, isolated from the session's mode (env and CLI)."""
    from beacon.snapshots import _state

    monkeypatch.delenv("BEACON_SNAPSHOT_MODE", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(_state, "pytest_mode", None)
    return tmp_path / "snaps"


# --------------------------------------------------------------------- framework


def test_first_run_writes_then_compares(snapdir: Path) -> None:
    assert_snapshot("a/b", {"x": 1}, directory=snapdir, mode="new")
    path = snapdir / "a" / "b.yaml"
    assert path.read_text(encoding="utf-8").endswith("value:\n  x: 1\n")
    assert_snapshot("a/b", {"x": 1}, directory=snapdir, mode="new")
    with pytest.raises(SnapshotMismatchError) as exc:
        assert_snapshot("a/b", {"x": 2}, directory=snapdir, mode="new")
    assert exc.value.code == "snapshot.mismatch"
    assert "-  x: 1" in exc.value.diff and "+  x: 2" in exc.value.diff


def test_check_mode_fails_on_missing(snapdir: Path) -> None:
    with pytest.raises(SnapshotMismatchError) as exc:
        assert_snapshot("missing", 1, directory=snapdir, mode="check")
    assert exc.value.code == "snapshot.missing"
    assert not (snapdir / "missing.yaml").exists()


def test_update_mode_rewrites(snapdir: Path) -> None:
    assert_snapshot("u", 1, directory=snapdir, mode="new")
    assert_snapshot("u", 2, directory=snapdir, mode="update")
    assert_snapshot("u", 2, directory=snapdir, mode="check")


def test_mode_from_environment(snapdir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CI", "true")
    with pytest.raises(SnapshotMismatchError):
        assert_snapshot("env", 1, directory=snapdir)
    monkeypatch.setenv("BEACON_SNAPSHOT_MODE", "new")
    assert_snapshot("env", 1, directory=snapdir)
    monkeypatch.setenv("BEACON_SNAPSHOT_MODE", "bogus")
    with pytest.raises(ValueError, match="snapshot mode"):
        assert_snapshot("env", 1, directory=snapdir)


def test_crlf_checkouts_still_match(snapdir: Path) -> None:
    assert_snapshot("crlf", {"text": "a\nb"}, directory=snapdir, mode="new")
    path = snapdir / "crlf.yaml"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    assert_snapshot("crlf", {"text": "a\nb"}, directory=snapdir, mode="check")


def test_files_are_lf_utf8(snapdir: Path) -> None:
    assert_snapshot("enc", {"k": "café 🎉"}, directory=snapdir, mode="new")
    raw = (snapdir / "enc.yaml").read_bytes()
    assert b"\r\n" not in raw
    assert "café 🎉".encode() in raw


def test_input_and_schema_sections(snapdir: Path) -> None:
    schema = {"type": "object", "required": ["intent"]}
    text = render_snapshot("x", {"other": 1}, input="raw text", schema=schema)
    doc = yaml.safe_load(text)
    assert doc["input"] == "raw text"
    assert doc["schema_validation"] == {
        "passed": False,
        "errors": [{"path": "", "keyword": "required", "message": 'missing required property "intent"'}],
    }


@pytest.mark.parametrize("name", ["", "/abs", "a/../b", ".hidden", "a b", "a\\b", "a//b"])
def test_invalid_names(name: str, snapdir: Path) -> None:
    with pytest.raises(ValueError, match="invalid snapshot name"):
        assert_snapshot(name, 1, directory=snapdir)


def test_alias() -> None:
    assert snapshot_test is assert_snapshot


def test_configure(snapdir: Path) -> None:
    from beacon.snapshots import _state

    old_dir, old_mode = _state.configured_dir, _state.configured_mode
    try:
        configure(directory=snapdir, mode="new")
        assert_snapshot("configured", 1)
        assert (snapdir / "configured.yaml").exists()
        with pytest.raises(ValueError):
            configure(mode="sometimes")  # type: ignore[arg-type]
    finally:
        _state.configured_dir, _state.configured_mode = old_dir, old_mode


def test_snapshot_class_auto_names(snapdir: Path) -> None:
    snap = Snapshot("test_mod", "test_case[param-1]", directory=snapdir)
    snap(1)
    snap(2)
    snap(3, name="explicit")
    assert sorted(p.name for p in (snapdir / "test_mod").iterdir()) == ["test_case_param-1-2.yaml", "test_case_param-1.yaml"]
    assert (snapdir / "explicit.yaml").exists()


def test_pytest_fixture(snapshot: Snapshot) -> None:
    snapshot({"fixture": "works"})


def test_render_is_pure() -> None:
    a = render_snapshot("p", {"b": [1, 2], "a": None}, input="x")
    assert all(render_snapshot("p", {"b": [1, 2], "a": None}, input="x") == a for _ in range(50))


# --------------------------------------------------------------------- to_snapshot_data


def test_snapshot_data_conversions() -> None:
    class Color(enum.Enum):
        RED = "red"

    @dataclasses.dataclass
    class Point:
        x: int
        tags: frozenset

    assert to_snapshot_data(Color.RED) == "red"
    assert to_snapshot_data(Point(1, frozenset({"b", "a"}))) == {"x": 1, "tags": ["a", "b"]}
    assert to_snapshot_data(b"hi") == {"bytes_hex": "6869"}
    assert to_snapshot_data((1, 2)) == [1, 2]
    with pytest.raises(TypeError):
        to_snapshot_data(object())
    with pytest.raises(TypeError):
        to_snapshot_data({1: "a"})


def test_exceptions_snapshot_with_code_and_position() -> None:
    with pytest.raises(MalformedOutputError) as exc:
        extract_json('{"a": ')
    data = to_snapshot_data(exc.value)
    assert data["type"] == "MalformedOutputError"
    assert data["code"] == "json.unexpected_end"
    assert data["position"] == 6


def test_pydantic_models() -> None:
    pydantic = pytest.importorskip("pydantic")

    class M(pydantic.BaseModel):
        a: int
        b: list[str]

    assert to_snapshot_data(M(a=1, b=["x"])) == {"a": 1, "b": ["x"]}


# --------------------------------------------------------------------- YAML emitter

YAML_CASES = [
    None,
    True,
    0,
    -12,
    10**30,
    0.1,
    1e20,
    -0.0,
    "plain",
    "with space",
    "",
    " leading",
    "trailing ",
    "yes",
    "No",
    "null",
    "~",
    "123",
    "1.5",
    "2024-01-15",
    "a: b",
    "a #b",
    "- item",
    "[x]",
    "{x}",
    "'q'",
    '"dq"',
    "tab\there",
    "line1\nline2",
    "line1\nline2\n",
    "line1\n\n",
    "\nleading newline",
    "trailing space \nx",
    "bell\x07",
    "zero\u200bwidth",
    "café 🎉 日本語",
    "\u2028sep",
    "C:\\path",
    [],
    {},
    [1, [2, [3, []]], {"a": {}}],
    {"nested": {"list": [{"k": "v", "multi": "a\nb"}, ["x", "y"]], "empty": []}},
    {"weird key": 1, "123": 2, "": 3, "true": 4, "multi\nline": 5},
    ["a\nb", "c\n"],
]


@pytest.mark.parametrize("value", YAML_CASES, ids=[repr(v)[:30] for v in YAML_CASES])
def test_yaml_round_trips_through_pyyaml(value: object) -> None:
    text = _yaml.dump(value)
    assert yaml.safe_load(text) == value


def test_yaml_special_floats() -> None:
    assert _yaml.dump(math.inf) == ".inf\n"
    assert _yaml.dump(-math.inf) == "-.inf\n"
    assert math.isnan(yaml.safe_load(_yaml.dump(math.nan)))


def test_yaml_is_readable() -> None:
    text = _yaml.dump({"intent": "cancel", "confidence": 0.9, "tags": ["a", "b"], "note": "line1\nline2"})
    assert text == "intent: cancel\nconfidence: 0.9\ntags:\n  - a\n  - b\nnote: |-\n  line1\n  line2\n"


def test_yaml_rejects_non_str_keys() -> None:
    with pytest.raises(TypeError):
        _yaml.dump({1: 2})


# --------------------------------------------------------------------- CLI


def test_cli_usage() -> None:
    assert main([]) == 2
    assert main(["--help"]) == 0


def test_cli_update_runs_pytest(tmp_path: Path) -> None:
    test_file = tmp_path / "test_tmp.py"
    test_file.write_text(
        "from beacon.snapshots import assert_snapshot\n"
        "def test_x():\n"
        "    assert_snapshot('cli/value', {'n': 1})\n",
        encoding="utf-8",
    )
    cmd = [sys.executable, "-m", "beacon.snapshots", "check", str(test_file), "-q", "-p", "no:cacheprovider"]
    assert subprocess.run(cmd, cwd=tmp_path, capture_output=True).returncode != 0
    cmd[3] = "update"
    assert subprocess.run(cmd, cwd=tmp_path, capture_output=True).returncode == 0
    assert (tmp_path / "snapshots" / "cli" / "value.yaml").exists()
    cmd[3] = "check"
    assert subprocess.run(cmd, cwd=tmp_path, capture_output=True).returncode == 0
