"""Incremental JSON over a growing stream, built on the stateless
:func:`parse_partial`.

A :class:`StreamParser` accumulates chunks and, after each, reports the best
value so far, whether the value is complete, and any **newly-committed** top-level
items — elements of a top-level array, ``(key, value)`` members of a top-level
object, or a lone scalar at the end. An item is committed only once no further
input can change it (its following delimiter has been seen, or the stream was
closed), so committed items never change and are emitted exactly once.

**Chunk-boundary invariance** is the key property: the same bytes split into
chunks *any* way yield the same sequence of committed items and the same final
value. It follows from re-parsing the whole accumulated buffer and never
committing the last, still-growing element until it is delimited.

Everything here is deterministic — no clock, no model, no network — and adds no
new parser: it is :func:`parse_partial` driven incrementally.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator, Mapping, Optional

from ._api import PartialResult, Policy, detect_pii, parse_partial, parse_tool_calls, redact
from .errors import BeaconError

__all__ = [
    "StreamUpdate",
    "StreamParser",
    "stream_json",
    "StreamRedactor",
    "stream_redact",
    "StreamToolCalls",
    "stream_tool_calls",
]


@dataclass(frozen=True)
class StreamUpdate:
    """The state after feeding one chunk (or closing).

    ``value`` is the best value so far (open containers/strings closed);
    ``complete`` is whether the buffer is a whole JSON value; ``consumed`` is the
    code points parsed into ``value``; ``committed`` are the top-level items that
    settled *in this update* (array elements, object ``(key, value)`` members, or
    a final scalar) — each is yielded exactly once, in order.
    """

    value: Any
    complete: bool
    consumed: int
    committed: tuple[Any, ...] = field(default_factory=tuple)


def _committed_count(value: Any, complete: bool, closed: bool) -> int:
    if isinstance(value, (list, dict)):
        # Every element but the last is delimited (so final); the last is still
        # growing until the container completes or the stream closes.
        return len(value) if (complete or closed) else max(0, len(value) - 1)
    # A bare scalar has no closing delimiter (``4`` could become ``42``), so it
    # only settles when the stream is closed and parsed cleanly.
    return 1 if (closed and complete) else 0


def _items(value: Any, start: int, end: int) -> list[Any]:
    if start >= end:
        return []
    if isinstance(value, list):
        return value[start:end]
    if isinstance(value, dict):
        return list(value.items())[start:end]
    return [value]  # scalar: a single item at (0, 1)


class StreamParser:
    """Feed chunks with :meth:`feed`; read :attr:`value` / :attr:`complete`;
    collect settled items from each update's ``committed`` (or iterate
    :func:`stream_json`). Call :meth:`close` when the stream ends to flush the
    final, undelimited item (a bare scalar, or a truncated container's tail).
    """

    def __init__(self) -> None:
        self._buf = ""
        self._emitted = 0
        self._closed = False
        self._last: PartialResult | None = None

    def feed(self, chunk: str) -> StreamUpdate:
        """Append ``chunk`` and return the resulting :class:`StreamUpdate`."""
        if self._closed:
            raise ValueError("cannot feed a closed StreamParser")
        if not isinstance(chunk, str):
            raise TypeError(f"chunk must be str, got {type(chunk).__name__}")
        self._buf += chunk
        return self._update(closed=False)

    def close(self) -> StreamUpdate:
        """Mark the stream ended and flush any remaining settled items.

        Idempotent: closing again yields an update with no new ``committed``.
        """
        self._closed = True
        return self._update(closed=True)

    def _update(self, *, closed: bool) -> StreamUpdate:
        result = parse_partial(self._buf)
        self._last = result
        count = _committed_count(result.value, result.complete, closed)
        newly = _items(result.value, self._emitted, count)
        self._emitted = count
        return StreamUpdate(result.value, result.complete, result.consumed, tuple(newly))

    @property
    def value(self) -> Any:
        return self._last.value if self._last is not None else None

    @property
    def complete(self) -> bool:
        return self._last.complete if self._last is not None else False

    @property
    def consumed(self) -> int:
        return self._last.consumed if self._last is not None else 0

    @property
    def closed(self) -> bool:
        return self._closed

    def __repr__(self) -> str:
        return f"StreamParser(buffered={len(self._buf)}, emitted={self._emitted}, closed={self._closed})"


def stream_json(chunks: Iterable[str]) -> Iterator[Any]:
    """Yield each committed top-level item from an iterable of text chunks.

    A convenience over :class:`StreamParser` for the common "iterate results as
    they arrive" pattern — a model streaming a JSON array yields each element the
    moment it settles. Order is preserved and each item is yielded once.

    >>> list(stream_json(['[1, 2', '3, 4', '5]']))
    [1, 23, 45]
    """
    parser = StreamParser()
    for chunk in chunks:
        yield from parser.feed(chunk).committed
    yield from parser.close().committed


# ---------------------------------------------------------------- streaming redaction


class StreamRedactor:
    """Redact PII and secrets over a stream, never emitting a secret across a
    chunk boundary.

    Each :meth:`feed` returns the text that is now safe to emit — the redaction
    of the buffer up to a cut placed *before* any match that could still be
    growing. A match that spans a chunk boundary is therefore held back until it
    completes and is redacted. Call :meth:`close` to flush the tail.

    The guarantee: the concatenation of every :meth:`feed` / :meth:`close` return
    value equals :func:`redact` of the whole text — for *any* chunking — so a
    secret is never emitted in the clear. This holds for secrets up to
    ``max_secret_len`` characters (default 1024); a longer secret (e.g. a large
    PEM block) is reliably redacted only once fully buffered or at :meth:`close`.
    Deterministic; same bytes, same output, regardless of split.
    """

    def __init__(
        self,
        *,
        policy: Policy = "default",
        exclude: Iterable[str] = (),
        patterns: Optional[Mapping[str, str]] = None,
        terms: Optional[Mapping[str, Iterable[str]]] = None,
        replacement: str = "[REDACTED:{label}]",
        max_secret_len: int = 1024,
    ) -> None:
        if max_secret_len < 1:
            raise ValueError("max_secret_len must be >= 1")
        self._buf = ""
        self._cut = 0  # buffer chars already finalized (a non-match boundary)
        self._emitted = 0  # redacted chars already returned
        self._closed = False
        self._hold = max_secret_len - 1
        self._replacement = replacement
        self._kw: dict[str, Any] = {"policy": policy, "exclude": exclude, "patterns": patterns, "terms": terms}

    def feed(self, chunk: str) -> str:
        """Append ``chunk``; return the newly safe-to-emit redacted text."""
        if self._closed:
            raise ValueError("cannot feed a closed StreamRedactor")
        if not isinstance(chunk, str):
            raise TypeError(f"chunk must be str, got {type(chunk).__name__}")
        self._buf += chunk
        return self._flush(final=False)

    def close(self) -> str:
        """Flush and redact the remaining tail. Idempotent."""
        out = self._flush(final=True)
        self._closed = True
        return out

    def _flush(self, *, final: bool) -> str:
        if final:
            cut = len(self._buf)
        else:
            cut = max(self._cut, len(self._buf) - self._hold)
            if cut > self._cut:
                # never cut inside a complete match (detect_pii is position-sorted)
                for f in detect_pii(self._buf, **self._kw):
                    if f["start"] < cut < f["end"]:
                        cut = f["end"]
                        break
                    if f["start"] >= cut:
                        break
        if cut <= self._cut:
            return ""
        redacted_prefix = redact(self._buf[:cut], replacement=self._replacement, **self._kw)
        out = redacted_prefix[self._emitted :]
        self._cut = cut
        self._emitted = len(redacted_prefix)
        return out

    @property
    def closed(self) -> bool:
        return self._closed

    def __repr__(self) -> str:
        return f"StreamRedactor(buffered={len(self._buf)}, finalized={self._cut}, closed={self._closed})"


def stream_redact(chunks: Iterable[str], **kwargs: Any) -> Iterator[str]:
    """Redact a stream of text chunks, yielding safe-to-emit redacted text.

    A convenience over :class:`StreamRedactor`; keyword arguments are passed
    through (``policy``, ``replacement``, ``max_secret_len``, …). The
    concatenation of what it yields equals :func:`redact` of the whole input.

    >>> "".join(stream_redact(["my email is al", "ice@example.com now"]))
    'my email is [REDACTED:email] now'
    """
    redactor = StreamRedactor(**kwargs)
    for chunk in chunks:
        piece = redactor.feed(chunk)
        if piece:
            yield piece
    tail = redactor.close()
    if tail:
        yield tail


# ---------------------------------------------------------------- streaming tool calls


class StreamToolCalls:
    """Detect tool calls over a stream, emitting each as it completes.

    Each :meth:`feed` re-reads the accumulated buffer with
    :func:`parse_tool_calls` and returns the tool calls that are newly complete —
    across every format beacon recognizes (Hermes, OpenAI/Anthropic JSON,
    Mistral, Llama, XML, python call syntax). A call is emitted only once it has
    fully parsed, in text order, so a call split across chunks is never emitted
    half-formed. While the buffer ends in an incomplete or malformed call
    (:func:`parse_tool_calls` is all-or-nothing and raises), nothing new is
    emitted; the call is released once it completes.

    The collected result equals :func:`parse_tool_calls` of the whole text, in
    order, for any chunking — provided the whole text parses cleanly (:meth:`close`
    re-reads the full buffer) and uses a single tool-call format, as a real model
    stream does (:func:`parse_tool_calls` detects one format per text).
    Deterministic; no new parser.
    """

    def __init__(self, *, include_format: bool = False) -> None:
        self._buf = ""
        self._emitted = 0
        self._closed = False
        self._include_format = bool(include_format)

    def feed(self, chunk: str) -> list[dict[str, Any]]:
        """Append ``chunk``; return the tool calls that are now complete."""
        if self._closed:
            raise ValueError("cannot feed a closed StreamToolCalls")
        if not isinstance(chunk, str):
            raise TypeError(f"chunk must be str, got {type(chunk).__name__}")
        self._buf += chunk
        return self._flush()

    def close(self) -> list[dict[str, Any]]:
        """Flush any final complete calls. Idempotent."""
        out = self._flush()
        self._closed = True
        return out

    def _flush(self) -> list[dict[str, Any]]:
        try:
            calls = parse_tool_calls(self._buf, include_format=self._include_format)
        except (BeaconError, ValueError, TypeError):
            # the buffer ends in an incomplete or malformed call — hold until it
            # completes (parse_tool_calls is all-or-nothing)
            return []
        new = calls[self._emitted :]
        self._emitted = len(calls)
        return new

    @property
    def closed(self) -> bool:
        return self._closed

    def __repr__(self) -> str:
        return f"StreamToolCalls(buffered={len(self._buf)}, emitted={self._emitted}, closed={self._closed})"


def stream_tool_calls(chunks: Iterable[str], *, include_format: bool = False) -> Iterator[dict[str, Any]]:
    """Yield each tool call from a stream of text chunks, as it completes.

    A convenience over :class:`StreamToolCalls`; the yielded calls equal
    :func:`parse_tool_calls` of the whole text, in order, for any chunking.

    >>> list(stream_tool_calls(['search(query=', '"rust")']))
    [{'name': 'search', 'arguments': {'query': 'rust'}}]
    """
    detector = StreamToolCalls(include_format=include_format)
    for chunk in chunks:
        yield from detector.feed(chunk)
    yield from detector.close()
