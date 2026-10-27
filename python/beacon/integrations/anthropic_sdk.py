"""Validated calls for the Anthropic Messages API (sync and async).

No dependency on the ``anthropic`` package: the response is duck-typed, so the
real SDK objects, plain dicts, and test fakes all work.

>>> from beacon.integrations.anthropic_sdk import validated_tool_call
>>> # response.content == [{"type": "tool_use", "name": "search", "input": {"q": "rust"}}]
>>> validated_tool_call(response)  # doctest: +SKIP
[{'name': 'search', 'arguments': {'q': 'rust'}}]

Anthropic returns tool calls as native ``tool_use`` content blocks whose
``input`` is already a parsed object, so beacon reads them directly into the
same ``{"name", "arguments"}`` shape every other integration produces. If a
response carries no ``tool_use`` block, the message text is parsed with
:func:`beacon.parse_tool_calls` for models that emit tool calls as text.
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


def _blocks(response: Any) -> list[Any]:
    content = _get(response, "content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return content
    return []


def response_text(response: Any) -> str:
    """The concatenated text of a Messages response.

    Raises :class:`~beacon.MalformedOutputError` (code
    ``anthropic.no_content``) when the response has no ``text`` block, e.g. a
    tool-use-only or empty response.
    """
    parts = [t for block in _blocks(response) if _get(block, "type") == "text" and isinstance(t := _get(block, "text"), str)]
    if not parts:
        raise MalformedOutputError("response has no text content", code="anthropic.no_content")
    return "".join(parts)


def validated_tool_call(
    response: Any,
    *,
    tool_schemas: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> list[dict[str, Any]]:
    """Tool calls from a Messages response, as ``{"name", "arguments"}`` dicts.

    Native ``tool_use`` blocks are used when present; otherwise the message
    text is parsed with :func:`beacon.parse_tool_calls`. ``tool_schemas`` maps
    tool names to JSON Schemas for their arguments; a call to an unknown tool
    raises :class:`~beacon.MalformedOutputError` (code
    ``anthropic.unknown_tool``) when it is given.
    """
    calls: list[dict[str, Any]] = []
    for block in _blocks(response):
        if _get(block, "type") != "tool_use":
            continue
        name = _get(block, "name")
        arguments = _get(block, "input")
        if arguments is None:
            arguments = {}
        elif isinstance(arguments, Mapping):
            arguments = dict(arguments)
        else:
            raise MalformedOutputError(
                f"tool_use input for {name!r} is not an object", code="anthropic.invalid_tool_input"
            )
        calls.append({"name": name, "arguments": arguments})

    if not calls:
        calls = parse_tool_calls(response_text(response))

    if tool_schemas is not None:
        for call in calls:
            schema = tool_schemas.get(call["name"])
            if schema is None:
                raise MalformedOutputError(
                    f"model called unknown tool {call['name']!r}", code="anthropic.unknown_tool"
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
    return client.messages.create


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
    """Call ``client.messages.create(**create_kwargs)`` and return the validated
    JSON (or an ``output_model`` instance).

    Args:
        client: An Anthropic-compatible client.
        schema: JSON Schema to validate against. Defaults to
            ``output_model.model_json_schema()``.
        output_model: Optional Pydantic model class to build from the JSON.
        select, kind: Passed to :func:`beacon.extract_json`.
        create: Use this callable instead of ``client.messages.create``.
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
    """Async version of :func:`validated_completion` for ``AsyncAnthropic``."""
    response = await _create(client, create)(**create_kwargs)
    text = response_text(response)
    return parse_structured(text, schema=schema, model=output_model, select=select, kind=kind)
