"""Agno integration: normalize tool calls and validate agent output.

No dependency on Agno: the run response and its tool executions are duck-typed,
so real Agno objects, plain dicts and test fakes all work
(``pip install "llm-beacon[agno]"`` only to run Agno itself).

An Agno ``RunResponse`` carries ``content`` (the final answer) and ``tools``
(the tool executions, each with ``tool_name`` and ``tool_args``).
:func:`validated_tool_call` normalizes those to beacon's ``{"name", "arguments"}``
shape; :func:`parse_output` extracts and validates the final answer.

>>> from beacon.integrations.agno import validated_tool_call
>>> validated_tool_call({"tool_name": "search", "tool_args": {"q": "rust"}})
[{'name': 'search', 'arguments': {'q': 'rust'}}]
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Optional

from .._api import validate_schema
from ..errors import MalformedOutputError, SchemaValidationError
from ._common import parse_structured, validate_value

__all__ = ["validated_tool_call", "parse_output"]


def _get(obj: Any, name: str) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name)
    return getattr(obj, name, None)


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
                f"tool args for {name!r} are not valid JSON", code="agno.invalid_arguments"
            ) from exc
        if not isinstance(parsed, dict):
            raise MalformedOutputError(f"tool args for {name!r} are not an object", code="agno.invalid_arguments")
        return parsed
    raise MalformedOutputError(f"tool args for {name!r} are not an object", code="agno.invalid_arguments")


def _executions(source: Any) -> list[Any]:
    tools = _get(source, "tools")
    if tools is not None:
        return list(tools)
    return [source]


def validated_tool_call(
    source: Any,
    *,
    tool_schemas: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> list[dict[str, Any]]:
    """Tool calls from an Agno ``RunResponse`` or a single tool execution.

    Accepts a response with a ``tools`` list, or a single execution with
    ``tool_name`` and ``tool_args``. ``tool_schemas`` maps tool names to JSON
    Schemas; a call to an unknown tool raises (code ``agno.unknown_tool``).
    """
    calls: list[dict[str, Any]] = []
    for execution in _executions(source):
        name = _get(execution, "tool_name")
        if name is None:
            raise MalformedOutputError("Agno tool execution has no tool_name", code="agno.invalid_call")
        calls.append({"name": name, "arguments": _arguments(name, _get(execution, "tool_args"))})
    if tool_schemas is not None:
        for call in calls:
            schema = tool_schemas.get(call["name"])
            if schema is None:
                raise MalformedOutputError(f"model called unknown tool {call['name']!r}", code="agno.unknown_tool")
            try:
                validate_schema(call["arguments"], schema)
            except SchemaValidationError as exc:
                exc.raw = json.dumps(call["arguments"])
                raise
    return calls


def parse_output(
    response: Any,
    *,
    schema: Optional[Mapping[str, Any]] = None,
    output_model: Any = None,
    select: str = "first",
    kind: str = "auto",
) -> Any:
    """Structured, validated JSON from an Agno run response's ``content``.

    A string ``content`` is parsed with :func:`beacon.extract_json`; a structured
    ``content`` (``response_model`` set) is validated directly. Raises
    :class:`~beacon.MalformedOutputError` (code ``agno.no_content``) when there is
    no usable content.
    """
    content = response if isinstance(response, str) else _get(response, "content")
    if isinstance(content, str):
        return parse_structured(content, schema=schema, model=output_model, select=select, kind=kind)
    if isinstance(content, Mapping):
        return validate_value(dict(content), schema=schema, model=output_model)
    dump = getattr(content, "model_dump", None)
    if callable(dump):
        return validate_value(dump(mode="json"), schema=schema, model=output_model)
    raise MalformedOutputError("Agno response has no text or structured content", code="agno.no_content")
