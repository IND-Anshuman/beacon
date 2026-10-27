from __future__ import annotations

import json
from pathlib import Path

import pytest

from beacon.cli import main


def test_extract_inline_text(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["extract", "-t", 'prose {"a": 1} more']) == 0
    assert json.loads(capsys.readouterr().out) == {"a": 1}


def test_extract_from_stdin(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO('```json\n{"intent": "cancel"}\n```'))
    assert main(["extract"]) == 0
    assert json.loads(capsys.readouterr().out) == {"intent": "cancel"}


def test_extract_malformed_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["extract", "-t", '{"a": ']) == 1
    assert "beacon:" in capsys.readouterr().err


def test_validate_ok_and_fail(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    schema = tmp_path / "schema.json"
    schema.write_text(json.dumps({"type": "object", "required": ["n"], "properties": {"n": {"type": "integer"}}}))
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"n": 1}))
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"n": "x"}))

    assert main(["validate", str(schema), str(good)]) == 0
    assert capsys.readouterr().out == ""

    assert main(["validate", str(schema), str(bad)]) == 1
    err = capsys.readouterr().err
    assert "/n: type:" in err


def test_redact(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["redact", "-t", "Email me at alice@example.com"]) == 0
    assert capsys.readouterr().out == "Email me at [REDACTED:email]"


def test_parse_tool(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["parse-tool", "-t", 'search(query="rust", limit=5)']) == 0
    assert json.loads(capsys.readouterr().out) == [{"name": "search", "arguments": {"query": "rust", "limit": 5}}]


def test_hash_is_deterministic(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["hash", "-t", "hello"]) == 0
    first = capsys.readouterr().out.strip()
    assert main(["hash", "-t", "hello"]) == 0
    assert capsys.readouterr().out.strip() == first
    assert main(["hash", "-t", "hello", "--length", "8"]) == 0
    assert len(capsys.readouterr().out.strip()) == 8


def test_missing_file_exits_1(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    assert main(["extract", str(tmp_path / "nope.txt")]) == 1
    assert "beacon:" in capsys.readouterr().err


def test_no_command_is_usage_error() -> None:
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2
