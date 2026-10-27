"""Validated calls for the Google Gemini API (sync and async).

No dependency on ``google-genai`` / ``google-generativeai``: the response is
duck-typed, so the real SDK objects, plain dicts, and test fakes all work.
Both the camelCase wire shape (``functionCall``) and the SDK's snake_case
attribute (``function_call``) are accepted.

>>> from beacon.integrations.gemini_sdk import validated_tool_call
>>> validated_tool_call(response)  # doctest: +SKIP
[{'name': 'search', 'arguments': {'q': 'rust'}}]

Gemini returns tool calls as ``functionCall`` parts whose ``args`` is already a
parsed object, so beacon reads them directly into the same ``{"name",
"arguments"}`` shape every other integration produces. If a response carries no
function-call part, the text is parsed with :func:`beacon.parse_tool_calls`.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Mapping, Optional

from .._api import parse_tool_calls, validate_schema
from ..errors import MalformedOutputError, SchemaValidationError
from ._common import parse_structured

__all__ = ["validated_completion", "avalidated_completion", "validated_tool_call", "response_text"]


def _get(obj: Any, name: str) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name)
    return getattr(obj, name, None)


def _first(obj: Any, *names: str) -> Any:
    """First non-``None`` value among several attribute/key names."""
    for name in names:
        value = _get(obj, name)
        if value is not None:
            return value
    return None


def _parts(response: Any) -> list[Any]:
    candidates = _get(response, "candidates")
    if not candidates:
        return []
    content = _get(candidates[0], "content")
    parts = _get(content, "parts") if content is not None else None
    return list(parts) if parts else []


def _as_dict(value: Any, name: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    try:
        return dict(value)
    except (TypeError, ValueError) as exc:
        raise MalformedOutputError(
            f"functionCall args for {name!r} is not an object", code="gemini.invalid_tool_args"
        ) from exc


def response_text(response: Any) -> str:
    """The concatenated text of every text part of the first candidate.

    Raises :class:`~beacon.MalformedOutputError` (code ``gemini.no_content``)
    when the response has no text, e.g. a function-call-only response.
    """
    parts = [t for part in _parts(response) if isinstance(t := _get(part, "text"), str)]
    if not parts:
        raise MalformedOutputError("response has no text content", code="gemini.no_content")
    return "".join(parts)


def validated_tool_call(
    response: Any,
    *,
    tool_schemas: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> list[dict[str, Any]]:
    """Function calls from a Gemini response, as ``{"name", "arguments"}`` dicts.

    Native ``functionCall`` parts are used when present; otherwise the text is
    parsed with :func:`beacon.parse_tool_calls`. ``tool_schemas`` maps tool
    names to JSON Schemas for their arguments; a call to an unknown tool raises
    :class:`~beacon.MalformedOutputError` (code ``gemini.unknown_tool``) when
    it is given.
    """
    calls: list[dict[str, Any]] = []
    for part in _parts(response):
        fc = _first(part, "function_call", "functionCall")
        if fc is None:
            continue
        name = _get(fc, "name")
        calls.append({"name": name, "arguments": _as_dict(_get(fc, "args"), name)})

    if not calls:
        calls = parse_tool_calls(response_text(response))

    if tool_schemas is not None:
        for call in calls:
            schema = tool_schemas.get(call["name"])
            if schema is None:
                raise MalformedOutputError(
                    f"model called unknown tool {call['name']!r}", code="gemini.unknown_tool"
                )
            try:
                validate_schema(call["arguments"], schema)
            except SchemaValidationError as exc:
                exc.raw = json.dumps(call["arguments"])
                raise
    return calls


def _create(client: Any, create: Optional[Callable[..., Any]]) -> Callable[..., Any]:
    if create is not None:
        return create
    return client.models.generate_content


def validated_completion(
    client: Any,
    *,
    schema: Optional[Mapping[str, Any]] = None,
    output_model: Any = None,
    select: str = "first",
    kind: str = "auto",
    create: Optional[Callable[..., Any]] = None,
    **create_kwargs: Any,
) -> Any:
    """Call ``client.models.generate_content(**create_kwargs)`` and return the
    validated JSON (or an ``output_model`` instance).

    Args:
        client: A Gemini-compatible client.
        schema: JSON Schema to validate against. Defaults to
            ``output_model.model_json_schema()``.
        output_model: Optional Pydantic model class to build from the JSON.
        select, kind: Passed to :func:`beacon.extract_json`.
        create: Use this callable instead of ``client.models.generate_content``
            (e.g. a ``GenerativeModel.generate_content`` bound method).
    """
    response = _create(client, create)(**create_kwargs)
    text = response_text(response)
    return parse_structured(text, schema=schema, model=output_model, select=select, kind=kind)


async def avalidated_completion(
    client: Any,
    *,
    schema: Optional[Mapping[str, Any]] = None,
    output_model: Any = None,
    select: str = "first",
    kind: str = "auto",
    create: Optional[Callable[..., Any]] = None,
    **create_kwargs: Any,
) -> Any:
    """Async version of :func:`validated_completion` for the async Gemini client
    (e.g. ``client.aio.models.generate_content``)."""
    response = await _create(client, create)(**create_kwargs)
    text = response_text(response)
    return parse_structured(text, schema=schema, model=output_model, select=select, kind=kind)
