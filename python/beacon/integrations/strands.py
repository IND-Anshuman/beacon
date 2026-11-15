"""Strands Agents (AWS) integration: tool schemas, tool-use calls, tool results.

No dependency on Strands: tool specs, tool-use blocks and tool results are
duck-typed, so real Strands objects, plain dicts and test fakes all work
(``pip install "llm-beacon[strands]"`` only to run Strands itself).

Strands uses the Bedrock Converse shapes: a tool is a ``toolSpec`` with an
``inputSchema.json``; a call is a ``toolUse`` block with ``name`` and ``input``;
a result is a ``toolResult`` with ``content`` blocks and a ``status``.

>>> from beacon.integrations.strands import validated_tool_call
>>> validated_tool_call({"toolUse": {"name": "search", "input": {"q": "rust"}}})
{'name': 'search', 'arguments': {'q': 'rust'}}
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Optional

from .._api import extract_json, validate_schema
from ..errors import MalformedOutputError, SchemaValidationError

__all__ = ["tool_schemas", "parse_tool_use", "validated_tool_call", "result_json"]


def _get(obj: Any, name: str) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name)
    return getattr(obj, name, None)


def _spec(tool: Any) -> Any:
    # Accept a bare toolSpec, a {"toolSpec": {...}} wrapper, or a @tool object.
    return _get(tool, "toolSpec") or _get(tool, "tool_spec") or tool


def tool_schemas(tools: Any) -> dict[str, dict[str, Any]]:
    """Map each Strands tool spec to the JSON Schema for its arguments.

    ``tools`` is an iterable of tool specs (dicts with ``name`` and
    ``inputSchema.json``, ``{"toolSpec": ...}`` wrappers, or ``@tool`` objects).
    A spec with no schema maps to ``{}`` (accepts any arguments).
    """
    out: dict[str, dict[str, Any]] = {}
    for tool in tools:
        spec = _spec(tool)
        name = _get(spec, "name")
        if name is None:
            raise MalformedOutputError("Strands tool spec has no name", code="strands.invalid_tool")
        input_schema = _get(spec, "inputSchema") or _get(spec, "input_schema")
        schema = _get(input_schema, "json") if input_schema is not None else None
        out[str(name)] = dict(schema) if isinstance(schema, Mapping) else {}
    return out


def parse_tool_use(block: Any) -> dict[str, Any]:
    """Normalize a Strands ``toolUse`` block to ``{"name", "arguments"}``.

    Accepts a ``{"toolUse": {...}}`` wrapper or a bare toolUse with ``name`` and
    ``input``. A missing ``input`` becomes ``{}``.
    """
    use = _get(block, "toolUse") or _get(block, "tool_use") or block
    name = _get(use, "name")
    if name is None:
        raise MalformedOutputError("Strands toolUse has no name", code="strands.invalid_call")
    arguments = _get(use, "input")
    if arguments is None:
        arguments = {}
    elif isinstance(arguments, Mapping):
        arguments = dict(arguments)
    else:
        raise MalformedOutputError(f"toolUse input for {name!r} is not an object", code="strands.invalid_call")
    return {"name": str(name), "arguments": arguments}


def validated_tool_call(block: Any, tools: Any = None) -> dict[str, Any]:
    """Parse a ``toolUse`` block and validate its arguments against ``tools``.

    ``tools`` is a ``{name: schema}`` map (as from :func:`tool_schemas`) or an
    iterable of tool specs. A call to a tool not in ``tools`` raises
    :class:`~beacon.MalformedOutputError` (code ``strands.unknown_tool``).
    """
    call = parse_tool_use(block)
    if tools is not None:
        schemas = tools if isinstance(tools, Mapping) else tool_schemas(tools)
        schema = schemas.get(call["name"])
        if schema is None:
            raise MalformedOutputError(f"call to unknown tool {call['name']!r}", code="strands.unknown_tool")
        try:
            validate_schema(call["arguments"], schema)
        except SchemaValidationError as exc:
            exc.raw = json.dumps(call["arguments"])
            raise
    return call


def result_json(
    result: Any,
    *,
    schema: Optional[Mapping[str, Any]] = None,
    select: str = "first",
    kind: str = "auto",
) -> Any:
    """Structured JSON from a Strands ``toolResult``.

    Prefers a ``json`` content block, otherwise extracts JSON from the text
    blocks with :func:`beacon.extract_json`. A result whose ``status`` is
    ``"error"`` raises :class:`~beacon.MalformedOutputError` (code
    ``strands.tool_error``). ``schema`` validates the value.
    """
    tr = _get(result, "toolResult") or _get(result, "tool_result") or result
    if _get(tr, "status") == "error":
        detail = _text(tr) or "(no detail)"
        raise MalformedOutputError(f"Strands tool returned an error: {detail}", code="strands.tool_error")
    content = _get(tr, "content") or []
    for block in content:
        structured = _get(block, "json")
        if structured is not None:
            value: Any = dict(structured) if isinstance(structured, Mapping) else structured
            if schema is not None:
                validate_schema(value, schema)
            return value
    text = _text(tr)
    if not text:
        raise MalformedOutputError("Strands tool result has no JSON or text content", code="strands.no_content")
    value = extract_json(text, select=select, kind=kind)
    if schema is not None:
        validate_schema(value, schema)
    return value


def _text(tool_result: Any) -> str:
    content = _get(tool_result, "content") or []
    return "".join(t for block in content if isinstance(t := _get(block, "text"), str))
