from __future__ import annotations

from typing import Any, Callable

from beacon.errors import BeaconError
from beacon.snapshots import to_snapshot_data


def outcome(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> dict[str, Any]:
    """Run a block and capture its result *or* its error as snapshot data."""
    try:
        return {"ok": to_snapshot_data(fn(*args, **kwargs))}
    except (BeaconError, ValueError, TypeError) as exc:
        return {"error": to_snapshot_data(exc)}
