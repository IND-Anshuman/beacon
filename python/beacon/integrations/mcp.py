"""MCP (Model Context Protocol) integration.

Turns the three MCP boundaries into beacon's deterministic shapes:

* **tool definitions** → ``{name: JSON Schema}`` via :func:`tool_schemas`, for
  validation and for :func:`beacon.schema_instructions`;
* **``tools/call`` arguments** → a validated ``{"name", "arguments"}`` via
  :func:`validate_call`, with a call to an unknown tool rejected;
* **tool results** → structured JSON via :func:`result_json`, preferring the
  result's ``structuredContent`` and otherwise parsing its text content blocks.

Everything is duck-typed: the official ``mcp`` SDK's pydantic models, plain
dicts, and test fakes all work, so there is no dependency on the ``mcp``
package (``pip install "llm-beacon[mcp]"`` only if you want the SDK itself).
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Optional

from .._api import extract_json, validate_schema
from ..errors import MalformedOutputError, SchemaValidationError

__all__ = ["tool_schemas", "parse_call", "validate_call", "result_text", "result_json"]


def _get(obj: Any, name: str) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name)
    return getattr(obj, name, None)


def _first(obj: Any, *names: str) -> Any:
    for name in names:
        value = _get(obj, name)
        if value is not None:
            return value
    return None


def tool_schemas(tools: Any) -> dict[str, dict[str, Any]]:
    """Map each MCP tool definition to its argument JSON Schema.

    ``tools`` is an iterable of tool definitions (``mcp`` ``Tool`` objects or
    dicts). The result maps ``tool.name`` to ``tool.inputSchema`` — ready for
    :func:`validate_call`, :func:`beacon.validate_schema` or
    :func:`beacon.schema_instructions`. A tool with no schema maps to ``{}``
    (which accepts any arguments).
    """
    out: dict[str, dict[str, Any]] = {}
    for tool in tools:
        name = _get(tool, "name")
        if name is None:
            raise MalformedOutputError("MCP tool definition has no name", code="mcp.invalid_tool")
        schema = _first(tool, "inputSchema", "input_schema")
        out[str(name)] = dict(schema) if isinstance(schema, Mapping) else {}
    return out


def parse_call(request: Any) -> dict[str, Any]:
    """Normalize an MCP ``tools/call`` request to ``{"name", "arguments"}``.

    ``request`` is the call params (an ``mcp`` ``CallToolRequestParams`` or a
    dict). A missing ``arguments`` becomes ``{}`` (MCP allows omitting it).
    """
    name = _get(request, "name")
    if name is None:
        raise MalformedOutputError("MCP tool call has no name", code="mcp.invalid_call")
    arguments = _get(request, "arguments")
    if arguments is None:
        arguments = {}
    elif isinstance(arguments, Mapping):
        arguments = dict(arguments)
    else:
        raise MalformedOutputError(f"MCP tool call arguments for {name!r} are not an object", code="mcp.invalid_call")
    return {"name": str(name), "arguments": arguments}


def validate_call(request: Any, tools: Any) -> dict[str, Any]:
    """Parse a ``tools/call`` request and validate its arguments.

    ``tools`` is either a ``{name: schema}`` map (as from :func:`tool_schemas`)
    or an iterable of tool definitions. A call to a tool not in ``tools`` raises
    :class:`~beacon.MalformedOutputError` (code ``mcp.unknown_tool``); arguments
    that violate the tool's schema raise :class:`~beacon.SchemaValidationError`.
    Returns the normalized ``{"name", "arguments"}``.
    """
    call = parse_call(request)
    schemas = tools if isinstance(tools, Mapping) else tool_schemas(tools)
    schema = schemas.get(call["name"])
    if schema is None:
        raise MalformedOutputError(f"call to unknown tool {call['name']!r}", code="mcp.unknown_tool")
    try:
        validate_schema(call["arguments"], schema)
    except SchemaValidationError as exc:
        exc.raw = json.dumps(call["arguments"])
        raise
    return call


def _content_text(result: Any) -> str:
    content = _get(result, "content") or []
    return "".join(
        t for block in content if _get(block, "type") == "text" and isinstance(t := _get(block, "text"), str)
    )


def result_text(result: Any) -> str:
    """The concatenated text of a ``CallToolResult``'s text content blocks.

    Raises :class:`~beacon.MalformedOutputError` (code ``mcp.no_content``) when
    there is no text block.
    """
    text = _content_text(result)
    if not text:
        raise MalformedOutputError("MCP tool result has no text content", code="mcp.no_content")
    return text


def result_json(
    result: Any,
    *,
    schema: Optional[Mapping[str, Any]] = None,
    select: str = "first",
    kind: str = "auto",
) -> Any:
    """Structured JSON from a ``CallToolResult``.

    Uses the result's ``structuredContent`` when present, otherwise extracts
    JSON from its text content with :func:`beacon.extract_json`. A result
    flagged ``isError`` raises :class:`~beacon.MalformedOutputError` (code
    ``mcp.tool_error``) carrying the error text. ``schema=`` validates the
    value.
    """
    if _first(result, "isError", "is_error"):
        raise MalformedOutputError(
            f"MCP tool returned an error: {_content_text(result) or '(no detail)'}", code="mcp.tool_error"
        )
    structured = _first(result, "structuredContent", "structured_content")
    if structured is not None:
        value: Any = dict(structured) if isinstance(structured, Mapping) else structured
    else:
        value = extract_json(result_text(result), select=select, kind=kind)
    if schema is not None:
        validate_schema(value, schema)
    return value
