"""Semantic Kernel integration: normalize function calls and results.

No dependency on Semantic Kernel: ``FunctionCallContent`` /
``FunctionResultContent`` and chat messages are duck-typed, so real SK objects,
plain dicts and test fakes all work
(``pip install "llm-beacon[semantic-kernel]"`` only to run SK itself).

SK represents a tool call as a ``FunctionCallContent`` (a fully-qualified
``name``, or separate ``plugin_name`` / ``function_name``, plus ``arguments``
that may be a JSON string or a dict). :func:`validated_tool_call` normalizes
those to beacon's ``{"name", "arguments"}``; :func:`result_json` validates a
``FunctionResultContent``.

>>> from beacon.integrations.semantic_kernel import validated_tool_call
>>> validated_tool_call({"name": "search", "arguments": '{"q": "rust"}'})
[{'name': 'search', 'arguments': {'q': 'rust'}}]
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Optional

from .._api import extract_json, validate_schema
from ..errors import MalformedOutputError, SchemaValidationError
from ._common import validate_value

__all__ = ["validated_tool_call", "result_json"]


def _get(obj: Any, name: str) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name)
    return getattr(obj, name, None)


def _name(content: Any) -> Optional[str]:
    name = _get(content, "name")
    if isinstance(name, str) and name:
        return name
    function_name = _get(content, "function_name")
    if not function_name:
        return None
    plugin_name = _get(content, "plugin_name")
    return f"{plugin_name}-{function_name}" if plugin_name else str(function_name)


def _arguments(name: Any, args: Any) -> dict[str, Any]:
    if args is None:
        return {}
    if isinstance(args, Mapping):
        return dict(args)
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
        except json.JSONDecodeError as exc:
            raise MalformedOutputError(
                f"function arguments for {name!r} are not valid JSON", code="semantic_kernel.invalid_arguments"
            ) from exc
        if not isinstance(parsed, dict):
            raise MalformedOutputError(
                f"function arguments for {name!r} are not an object", code="semantic_kernel.invalid_arguments"
            )
        return parsed
    raise MalformedOutputError(
        f"function arguments for {name!r} are not an object", code="semantic_kernel.invalid_arguments"
    )


def _is_call(item: Any) -> bool:
    return _get(item, "function_name") is not None or _get(item, "arguments") is not None


def _calls(source: Any) -> list[Any]:
    items = _get(source, "items")
    if items is not None:
        return [item for item in items if _is_call(item)]
    return [source]


def validated_tool_call(
    source: Any,
    *,
    tool_schemas: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> list[dict[str, Any]]:
    """Function calls from an SK message or ``FunctionCallContent``.

    Accepts a chat message with ``items`` (function-call items are selected), or
    a bare ``FunctionCallContent``. JSON-string arguments are parsed strictly.
    ``tool_schemas`` maps tool names to JSON Schemas; a call to an unknown tool
    raises (code ``semantic_kernel.unknown_tool``).
    """
    calls: list[dict[str, Any]] = []
    for content in _calls(source):
        name = _name(content)
        if name is None:
            raise MalformedOutputError("SK function call has no name", code="semantic_kernel.invalid_call")
        calls.append({"name": name, "arguments": _arguments(name, _get(content, "arguments"))})
    if tool_schemas is not None:
        for call in calls:
            schema = tool_schemas.get(call["name"])
            if schema is None:
                raise MalformedOutputError(
                    f"model called unknown tool {call['name']!r}", code="semantic_kernel.unknown_tool"
                )
            try:
                validate_schema(call["arguments"], schema)
            except SchemaValidationError as exc:
                exc.raw = json.dumps(call["arguments"])
                raise
    return calls


def result_json(
    result: Any,
    *,
    schema: Optional[Mapping[str, Any]] = None,
    select: str = "first",
    kind: str = "auto",
) -> Any:
    """Structured, validated JSON from a ``FunctionResultContent`` (or its value).

    A string result is parsed with :func:`beacon.extract_json`; a structured
    result is validated directly. ``schema`` validates the value.
    """
    value = _get(result, "result")
    if value is None:
        value = result
    if isinstance(value, str):
        value = extract_json(value, select=select, kind=kind)
        if schema is not None:
            validate_schema(value, schema)
        return value
    if isinstance(value, Mapping):
        return validate_value(dict(value), schema=schema)
    if isinstance(value, list):
        return validate_value(list(value), schema=schema)
    raise MalformedOutputError("SK function result has no text or structured value", code="semantic_kernel.no_content")
