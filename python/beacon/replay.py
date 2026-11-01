"""Record/replay of provider responses — VCR for LLMs.

A :class:`Cassette` keys each request by its deterministic BLAKE3 digest
(:func:`beacon.hash_content`) and stores request/response pairs in a JSON file.
In replay the stored response is returned without calling the provider; in
record the provider is called once and the response saved. This lets snapshot
tests run against byte-identical *real* traffic instead of hand-written
fixtures, with no network in CI.

    from beacon.replay import Cassette

    tape = Cassette("tests/cassettes/intents.json")  # "auto": replay if present, else record
    request = {"model": "gpt-4o", "messages": [...]}
    response = tape.play(request, lambda: client.chat.completions.create(**request))

Requests and responses are stored as JSON-like data (via
:func:`beacon.snapshots.to_snapshot_data`, so Pydantic model responses and the
like are coerced with ``model_dump``). A replayed response therefore comes back
as plain ``dict``/``list`` data, which beacon's duck-typed integrations accept.

Modes (``mode=`` or the ``BEACON_CASSETTE_MODE`` environment variable):

* ``auto`` — replay a recorded request, otherwise record it (default)
* ``replay`` — only replay; an unrecorded request raises (use this in CI)
* ``record`` — always call the provider and (re)record
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Optional, Union

from ._api import hash_content
from .snapshots import to_snapshot_data

__all__ = ["Cassette"]

_MODES = ("auto", "replay", "record")


class Cassette:
    """A file of recorded request/response pairs."""

    def __init__(self, path: Union[str, os.PathLike[str]], *, mode: Optional[str] = None) -> None:
        self.path = Path(path)
        resolved = mode or os.environ.get("BEACON_CASSETTE_MODE") or "auto"
        if resolved not in _MODES:
            raise ValueError(f"mode must be one of {', '.join(_MODES)}, got {resolved!r}")
        self.mode = resolved
        self._entries: dict[str, dict[str, Any]] = {}
        if self.path.exists():
            doc = json.loads(self.path.read_text(encoding="utf-8"))
            self._entries = dict(doc.get("entries", {}))

    def key(self, request: Any) -> str:
        """The deterministic cassette key for ``request`` (a 32-hex digest)."""
        return hash_content(to_snapshot_data(request), length=32)

    def play(self, request: Any, call: Callable[[], Any]) -> Any:
        """Return the recorded response for ``request``, or record ``call()``.

        In ``replay`` mode an unrecorded request raises :class:`LookupError`
        (nothing is called). Otherwise, on a miss, ``call()`` is invoked once,
        its result stored (coerced to JSON-like data) and returned.
        """
        key = self.key(request)
        if self.mode != "record" and key in self._entries:
            return self._entries[key]["response"]
        if self.mode == "replay":
            raise LookupError(f"no recorded response for this request in {self.path} (mode 'replay')")
        response = to_snapshot_data(call())
        self._entries[key] = {"request": to_snapshot_data(request), "response": response}
        self.save()
        return response

    def save(self) -> None:
        """Write the cassette to disk (keys sorted, so diffs are stable)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        doc = {"entries": dict(sorted(self._entries.items()))}
        with open(self.path, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, request: Any) -> bool:
        return self.key(request) in self._entries
