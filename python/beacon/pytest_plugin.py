"""pytest plugin: the ``snapshot`` fixture and ``--beacon-snapshot`` option.

Registered automatically through the ``pytest11`` entry point when beacon is
installed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from . import snapshots


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("beacon")
    group.addoption(
        "--beacon-snapshot",
        action="store",
        choices=("new", "check", "update"),
        default=None,
        help="snapshot mode: new (write missing), check (fail on missing/changed), update (rewrite)",
    )
    parser.addini(
        "beacon_snapshot_dir",
        "directory for beacon snapshot files, relative to the rootdir (default: <test dir>/snapshots)",
        default="",
    )


def pytest_configure(config: pytest.Config) -> None:
    mode = config.getoption("--beacon-snapshot")
    if mode:
        snapshots._state.pytest_mode = mode
    directory = config.getini("beacon_snapshot_dir")
    if directory:
        snapshots._state.pytest_dir = (Path(str(config.rootpath)) / str(directory)).resolve()


def pytest_unconfigure(config: pytest.Config) -> None:
    snapshots._state.pytest_mode = None
    snapshots._state.pytest_dir = None


@pytest.fixture
def snapshot(request: pytest.FixtureRequest) -> snapshots.Snapshot:
    """Snapshot assertions named after the current test."""
    module = Path(str(request.node.path)).stem if hasattr(request.node, "path") else "tests"
    return snapshots.Snapshot(module, request.node.name)


def pytest_terminal_summary(terminalreporter: Any) -> None:
    events = snapshots._state.events
    if not events:
        return
    written = sum(1 for action, _ in events if action == "written")
    updated = sum(1 for action, _ in events if action == "updated")
    parts = []
    if written:
        parts.append(f"{written} written")
    if updated:
        parts.append(f"{updated} updated")
    terminalreporter.write_sep("-", f"beacon snapshots: {', '.join(parts)}")
