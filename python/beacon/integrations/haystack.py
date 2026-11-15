"""Haystack integration: an output-adapter component that extracts + validates.

The core function :func:`validate_replies` is duck-typed and needs no Haystack
install. :func:`output_validator` builds a Haystack 2.x pipeline **component**
(that one needs ``pip install "llm-beacon[haystack]"``); it wraps the same
function so a generator's ``replies`` become validated JSON inside a pipeline.

>>> from beacon.integrations.haystack import validate_replies
>>> validate_replies(['Here you go: {"ok": true}'])
{'ok': True}
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from ..errors import MalformedOutputError
from ._common import parse_structured, require

__all__ = ["validate_replies", "output_validator"]


def validate_replies(
    replies: Any,
    *,
    schema: Optional[Mapping[str, Any]] = None,
    output_model: Any = None,
    select: str = "first",
    kind: str = "auto",
    reply_index: int = 0,
) -> Any:
    """Extract and validate JSON from a Haystack generator's ``replies`` list.

    By default the first reply is used. Raises
    :class:`~beacon.MalformedOutputError` (code ``haystack.no_content``) when
    there is no text reply at ``reply_index``.
    """
    if not replies or reply_index >= len(replies):
        raise MalformedOutputError("Haystack generator produced no replies", code="haystack.no_content")
    text = replies[reply_index]
    if not isinstance(text, str):
        raise MalformedOutputError("Haystack reply is not text", code="haystack.no_content")
    return parse_structured(text, schema=schema, model=output_model, select=select, kind=kind)


def output_validator(
    *,
    schema: Optional[Mapping[str, Any]] = None,
    output_model: Any = None,
    select: str = "first",
    kind: str = "auto",
) -> Any:
    """A Haystack 2.x component that validates a generator's replies as JSON.

    Requires Haystack. Add it to a pipeline after a generator and connect
    ``generator.replies`` to it; it exposes ``run(replies) -> {"json": ...}``.
    Parsing failures raise the usual :class:`~beacon.MalformedOutputError` /
    :class:`~beacon.SchemaValidationError`, so a pipeline's error handling sees
    the beacon error directly.
    """
    haystack = require("haystack", "haystack", "beacon.integrations.haystack.output_validator")
    component = haystack.component

    @component
    class BeaconOutputValidator:
        def __init__(self) -> None:
            self._schema = dict(schema) if schema is not None else None

        @component.output_types(json=Any)
        def run(self, replies: list[str]) -> dict[str, Any]:
            return {
                "json": validate_replies(
                    replies, schema=self._schema, output_model=output_model, select=select, kind=kind
                )
            }

    return BeaconOutputValidator()
