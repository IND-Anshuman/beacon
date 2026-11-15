"""AutoGen integration: normalize tool/function calls to beacon's shape.

No dependency on AutoGen: calls and messages are duck-typed, so AutoGen Core's
``FunctionCall`` objects, the AgentChat / legacy ``pyautogen`` OpenAI-style
``tool_calls`` / ``function_call`` message fields, plain dicts and test fakes
all work (``pip install "llm-beacon[autogen]"`` only to run AutoGen itself).

>>> from beacon.integrations.autogen import validated_tool_call
>>> validated_tool_call({"name": "search", "arguments": '{"q": "rust"}'})
[{'name': 'search', 'arguments': {'q': 'rust'}}]

A call to an unknown tool raises :class:`~beacon.MalformedOutputError` (code
``autogen.unknown_tool``); arguments that are not valid JSON object text raise
``autogen.invalid_arguments``.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Optional

from .._api import validate_schema
from ..errors import MalformedOutputError, SchemaValidationError
from ._common import parse_structured

__all__ = ["validated_tool_call", "parse_output"]


def _get(obj: Any, name: str) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name)
    return getattr(obj, name, None)


def _arguments(name: Any, arguments: Any) -> dict[str, Any]:
    """Normalize a tool call's arguments to a dict (JSON-string args are parsed)."""
    if arguments is None:
        return {}
    if isinstance(arguments, Mapping):
        return dict(arguments)
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError as exc:
            raise MalformedOutputError(
                f"tool call arguments for {name!r} are not valid JSON", code="autogen.invalid_arguments"
            ) from exc
        if not isinstance(parsed, dict):
            raise MalformedOutputError(
                f"tool call arguments for {name!r} are not an object", code="autogen.invalid_arguments"
            )
        return parsed
    raise MalformedOutputError(f"tool call arguments for {name!r} are not an object", code="autogen.invalid_arguments")


def _calls(source: Any) -> list[dict[str, Any]]:
    tool_calls = _get(source, "tool_calls")
    if tool_calls:
        out = []
        for call in tool_calls:
            fn = _get(call, "function")
            target = fn if fn is not None else call
            name = _get(target, "name")
            out.append({"name": name, "arguments": _arguments(name, _get(target, "arguments"))})
        return out
    function_call = _get(source, "function_call")
    if function_call is not None:
        name = _get(function_call, "name")
        return [{"name": name, "arguments": _arguments(name, _get(function_call, "arguments"))}]
    name = _get(source, "name")
    if name is not None:
        return [{"name": name, "arguments": _arguments(name, _get(source, "arguments"))}]
    raise MalformedOutputError("no tool call found in AutoGen message", code="autogen.no_tool_call")


def validated_tool_call(
    source: Any,
    *,
    tool_schemas: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> list[dict[str, Any]]:
    """Tool calls from an AutoGen message or ``FunctionCall``, as ``{"name", "arguments"}``.

    Accepts a message with OpenAI-style ``tool_calls`` / ``function_call``, or a
    bare ``FunctionCall``-like object with ``name`` and ``arguments``. JSON-string
    arguments are parsed strictly. ``tool_schemas`` maps tool names to JSON
    Schemas; a call to an unknown tool raises (code ``autogen.unknown_tool``).
    """
    calls = _calls(source)
    if tool_schemas is not None:
        for call in calls:
            schema = tool_schemas.get(call["name"])
            if schema is None:
                raise MalformedOutputError(f"model called unknown tool {call['name']!r}", code="autogen.unknown_tool")
            try:
                validate_schema(call["arguments"], schema)
            except SchemaValidationError as exc:
                exc.raw = json.dumps(call["arguments"])
                raise
    return calls


def parse_output(
    message: Any,
    *,
    schema: Optional[Mapping[str, Any]] = None,
    output_model: Any = None,
    select: str = "first",
    kind: str = "auto",
) -> Any:
    """Extract and validate JSON from an AutoGen text message (or a plain string).

    Raises :class:`~beacon.MalformedOutputError` (code ``autogen.no_content``)
    when the message carries no text content.
    """
    content = message if isinstance(message, str) else _get(message, "content")
    if not isinstance(content, str):
        raise MalformedOutputError("AutoGen message has no text content", code="autogen.no_content")
    return parse_structured(content, schema=schema, model=output_model, select=select, kind=kind)
