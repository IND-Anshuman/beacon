"""Snapshot testing for the deterministic parts of LLM applications.

Record a canned LLM response once, then snapshot what your parsing,
validation and post-processing code does with it::

    from beacon.snapshots import assert_snapshot

    def test_cancel_intent():
        raw = load_fixture("cancel.txt")            # recorded LLM output
        result = extract_json(raw)
        assert_snapshot("intents/cancel", result, input=raw, schema=INTENT_SCHEMA)

The first run writes ``snapshots/intents/cancel.yaml``; later runs compare
against it byte for byte and fail with a diff on any change.

Modes (first match wins):

1. ``mode=`` argument / :func:`configure`
2. pytest ``--beacon-snapshot=new|check|update``
3. ``BEACON_SNAPSHOT_MODE`` environment variable
4. ``check`` if the ``CI`` environment variable is set, else ``new``

* ``new`` — write missing snapshots, fail on mismatch (local default)
* ``check`` — fail on missing or mismatched snapshots (CI default)
* ``update`` — rewrite snapshots that differ

These settings only change what the *test harness* does with files; they
never change what a beacon block returns.

CLI: ``python -m beacon.snapshots update [pytest args]`` re-runs pytest in
update mode; ``check`` re-runs it in check mode.
"""

from __future__ import annotations

import dataclasses
import difflib
import enum
import os
import re
import sys
from pathlib import Path
from typing import Any, Literal, Mapping, Optional, Union

from . import _yaml
from ._api import schema_errors
from .errors import BeaconError, SnapshotMismatchError

__all__ = [
    "assert_snapshot",
    "snapshot_test",
    "render_snapshot",
    "to_snapshot_data",
    "configure",
    "Snapshot",
    "SnapshotMode",
    "main",
]

SnapshotMode = Literal["new", "check", "update"]
_MODES = ("new", "check", "update")
_MISSING: Any = object()
_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.\-]*(?:/[A-Za-z0-9_][A-Za-z0-9_.\-]*)*")
HEADER = "# beacon snapshot v1 — regenerate with: python -m beacon.snapshots update"


class _State:
    configured_dir: Optional[Path] = None
    configured_mode: Optional[str] = None
    pytest_dir: Optional[Path] = None
    pytest_mode: Optional[str] = None
    #: (action, path) for every snapshot written this session.
    events: list[tuple[str, str]] = []


_state = _State()


def configure(*, directory: Union[str, os.PathLike[str], None] = None, mode: Optional[SnapshotMode] = None) -> None:
    """Set the snapshot directory and/or mode for this process."""
    if mode is not None and mode not in _MODES:
        raise ValueError(f"mode must be one of {', '.join(_MODES)}, got {mode!r}")
    if directory is not None:
        _state.configured_dir = Path(directory).resolve()
    if mode is not None:
        _state.configured_mode = mode


def _resolve_mode(mode: Optional[str]) -> str:
    for candidate in (mode, _state.configured_mode, _state.pytest_mode, os.environ.get("BEACON_SNAPSHOT_MODE")):
        if candidate:
            if candidate not in _MODES:
                raise ValueError(f"snapshot mode must be one of {', '.join(_MODES)}, got {candidate!r}")
            return candidate
    ci = os.environ.get("CI", "").strip().lower()
    return "check" if ci not in ("", "0", "false", "no") else "new"


def _caller_dir() -> Path:
    frame = sys._getframe(1)
    while frame is not None:
        filename = frame.f_code.co_filename
        if Path(filename).resolve() != Path(__file__).resolve():
            return Path(filename).resolve().parent
        frame = frame.f_back  # type: ignore[assignment]
    return Path.cwd()


def _resolve_dir(directory: Union[str, os.PathLike[str], None]) -> Path:
    if directory is not None:
        return Path(directory).resolve()
    if _state.configured_dir is not None:
        return _state.configured_dir
    if _state.pytest_dir is not None:
        return _state.pytest_dir
    return _caller_dir() / "snapshots"


def _check_name(name: str) -> None:
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ValueError(
            f"invalid snapshot name {name!r}: use letters, digits, '_', '-', '.', "
            "with '/' to separate directories (segments may not start with '.')"
        )


def to_snapshot_data(value: Any) -> Any:
    """Convert a value to JSON-like data for a snapshot.

    Dataclasses, Pydantic models, enums, sets, bytes and exceptions get a
    deterministic representation; other non-JSON types raise ``TypeError``.
    """
    if isinstance(value, enum.Enum):
        return to_snapshot_data(value.value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if isinstance(k, enum.Enum):
                k = k.value
            if not isinstance(k, str):
                raise TypeError(f"snapshot dict keys must be str, got {type(k).__name__}")
            out[k] = to_snapshot_data(v)
        return out
    if isinstance(value, (list, tuple)):
        return [to_snapshot_data(v) for v in value]
    if isinstance(value, (set, frozenset)):
        items = [to_snapshot_data(v) for v in value]
        return sorted(items, key=lambda x: (type(x).__name__, repr(x)))
    if isinstance(value, (bytes, bytearray)):
        return {"bytes_hex": bytes(value).hex()}
    if isinstance(value, BaseException):
        data: dict[str, Any] = {"type": type(value).__name__}
        if isinstance(value, BeaconError):
            data["code"] = value.code
        data["message"] = str(value)
        for attr in ("position", "line", "column", "names", "errors"):
            v = getattr(value, attr, None)
            if v is not None and v != ():
                data[attr] = to_snapshot_data(v)
        return data
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_snapshot_data(getattr(value, f.name)) for f in dataclasses.fields(value)}
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return to_snapshot_data(dump(mode="json"))
    raise TypeError(f"cannot snapshot a value of type {type(value).__name__}; convert it to JSON-like data first")


def render_snapshot(
    name: str,
    value: Any,
    *,
    input: Any = _MISSING,
    schema: Optional[Mapping[str, Any]] = None,
) -> str:
    """The exact text of the snapshot file for these arguments (pure)."""
    _check_name(name)
    doc: dict[str, Any] = {"name": name}
    if input is not _MISSING:
        doc["input"] = to_snapshot_data(input)
    data = to_snapshot_data(value)
    doc["value"] = data
    if schema is not None:
        errors = schema_errors(data, schema)
        doc["schema_validation"] = {"passed": not errors, "errors": [dict(e) for e in errors]}
    return HEADER + "\n" + _yaml.dump(doc)


def _diff(old: str, new: str, path: Path) -> str:
    lines = difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=f"{path.name} (stored)",
        tofile=f"{path.name} (current)",
    )
    return "".join(lines)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def assert_snapshot(
    name: str,
    value: Any,
    *,
    input: Any = _MISSING,
    schema: Optional[Mapping[str, Any]] = None,
    directory: Union[str, os.PathLike[str], None] = None,
    mode: Optional[SnapshotMode] = None,
) -> None:
    """Compare ``value`` with the stored snapshot ``name``.

    Args:
        name: Snapshot name; ``/`` creates subdirectories
            (``"extract_json/fence"`` → ``snapshots/extract_json/fence.yaml``).
        value: JSON-like data (see :func:`to_snapshot_data`).
        input: Optional input to record alongside the value (e.g. the raw LLM
            response), so the snapshot file is self-explanatory.
        schema: Optional JSON Schema; the validation outcome is recorded too.
        directory: Override the snapshot directory.
        mode: Override the snapshot mode.

    Raises:
        SnapshotMismatchError: on a mismatch, or a missing snapshot in
            ``check`` mode.
    """
    text = render_snapshot(name, value, input=input, schema=schema)
    resolved_mode = _resolve_mode(mode)
    path = _resolve_dir(directory) / f"{name}.yaml"
    if not path.exists():
        if resolved_mode == "check":
            raise SnapshotMismatchError(
                f"snapshot {name!r} does not exist at {path} (mode 'check'); "
                "run `python -m beacon.snapshots update` to create it",
                code="snapshot.missing",
                path=str(path),
            )
        _write(path, text)
        _state.events.append(("written", str(path)))
        return
    with open(path, encoding="utf-8", newline="") as f:
        stored = f.read().replace("\r\n", "\n")
    if stored == text:
        return
    if resolved_mode == "update":
        _write(path, text)
        _state.events.append(("updated", str(path)))
        return
    diff = _diff(stored, text, path)
    raise SnapshotMismatchError(
        f"snapshot {name!r} does not match {path}\n"
        "run `python -m beacon.snapshots update` if the change is intended\n\n" + diff,
        code="snapshot.mismatch",
        path=str(path),
        diff=diff,
    )


#: Alias matching the name used in the project brief.
snapshot_test = assert_snapshot


def _sanitize(part: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.\-]+", "_", part).strip("_.") or "snapshot"
    return cleaned if cleaned[0].isalnum() or cleaned[0] == "_" else "_" + cleaned


class Snapshot:
    """The pytest ``snapshot`` fixture.

    ``snapshot(value)`` stores ``<module>/<test name>.yaml``; further calls in
    the same test get ``-2``, ``-3``… suffixes. Pass ``name=`` to choose.
    """

    def __init__(self, module: str, test: str, directory: Optional[Path] = None) -> None:
        self._prefix = f"{_sanitize(module)}/{_sanitize(test)}"
        self._directory = directory
        self._count = 0

    def __call__(self, value: Any, *, name: Optional[str] = None, input: Any = _MISSING, schema: Optional[Mapping[str, Any]] = None) -> None:
        self.assert_match(value, name=name, input=input, schema=schema)

    def assert_match(self, value: Any, *, name: Optional[str] = None, input: Any = _MISSING, schema: Optional[Mapping[str, Any]] = None) -> None:
        if name is None:
            self._count += 1
            name = self._prefix if self._count == 1 else f"{self._prefix}-{self._count}"
        assert_snapshot(name, value, input=input, schema=schema, directory=self._directory)


def main(argv: Optional[list[str]] = None) -> int:
    """``python -m beacon.snapshots {update,check} [pytest args...]``."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in ("update", "check"):
        print("usage: python -m beacon.snapshots {update,check} [pytest args...]")
        print("  update  re-run pytest and rewrite snapshots that differ")
        print("  check   re-run pytest and fail on missing or changed snapshots")
        return 0 if args and args[0] in ("-h", "--help") else 2
    try:
        import pytest
    except ImportError:  # pragma: no cover
        print("beacon.snapshots: pytest is required for this command", file=sys.stderr)
        return 2
    return int(pytest.main([*args[1:], f"--beacon-snapshot={args[0]}"]))


if __name__ == "__main__":
    raise SystemExit(main())
