"""OpenAI Agents SDK integration: tool-argument validation and final output.

No dependency on the ``agents`` package: ``FunctionTool`` objects, tool-call
items and the run result are duck-typed, so real SDK objects, plain dicts and
test fakes all work (``pip install "llm-beacon[openai-agents]"`` only to run the
SDK itself).

The Agents SDK describes a function tool with a ``params_json_schema`` and emits
tool calls whose ``arguments`` are a JSON string. :func:`validated_tool_call`
validates those against the tools; :func:`validated_output` extracts and
validates a run's ``final_output``.

>>> from beacon.integrations.openai_agents import validated_tool_call
>>> tools = {"search": {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}}
>>> validated_tool_call({"name": "search", "arguments": '{"q": "rust"}'}, tools)
{'name': 'search', 'arguments': {'q': 'rust'}}
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Optional

from .._api import validate_schema
from ..errors import MalformedOutputError, SchemaValidationError
from ._common import parse_structured, validate_value

__all__ = ["tool_schemas", "validated_tool_call", "validated_output"]


def _get(obj: Any, name: str) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name)
    return getattr(obj, name, None)


def tool_schemas(tools: Any) -> dict[str, dict[str, Any]]:
    """Map each Agents SDK ``FunctionTool`` to its argument JSON Schema.

    ``tools`` is an iterable of function tools (objects with ``name`` and
    ``params_json_schema``, or dicts). A tool with no schema maps to ``{}``.
    """
    out: dict[str, dict[str, Any]] = {}
    for tool in tools:
        name = _get(tool, "name")
        if name is None:
            raise MalformedOutputError("Agents SDK tool has no name", code="openai_agents.invalid_tool")
        schema = _get(tool, "params_json_schema") or _get(tool, "params")
        out[str(name)] = dict(schema) if isinstance(schema, Mapping) else {}
    return out


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
                f"tool call arguments for {name!r} are not valid JSON", code="openai_agents.invalid_arguments"
            ) from exc
        if not isinstance(parsed, dict):
            raise MalformedOutputError(
                f"tool call arguments for {name!r} are not an object", code="openai_agents.invalid_arguments"
            )
        return parsed
    raise MalformedOutputError(
        f"tool call arguments for {name!r} are not an object", code="openai_agents.invalid_arguments"
    )


def validated_tool_call(call: Any, tools: Any = None) -> dict[str, Any]:
    """Normalize a tool call to ``{"name", "arguments"}`` and validate its args.

    ``call`` has ``name`` and ``arguments`` (a JSON string or a dict). ``tools``
    is a ``{name: schema}`` map (as from :func:`tool_schemas`) or an iterable of
    function tools. A call to a tool not in ``tools`` raises
    :class:`~beacon.MalformedOutputError` (code ``openai_agents.unknown_tool``).
    """
    name = _get(call, "name")
    if name is None:
        raise MalformedOutputError("tool call has no name", code="openai_agents.invalid_call")
    normalized = {"name": str(name), "arguments": _arguments(name, _get(call, "arguments"))}
    if tools is not None:
        schemas = tools if isinstance(tools, Mapping) else tool_schemas(tools)
        schema = schemas.get(normalized["name"])
        if schema is None:
            raise MalformedOutputError(
                f"call to unknown tool {normalized['name']!r}", code="openai_agents.unknown_tool"
            )
        try:
            validate_schema(normalized["arguments"], schema)
        except SchemaValidationError as exc:
            exc.raw = json.dumps(normalized["arguments"])
            raise
    return normalized


def validated_output(
    result: Any,
    *,
    schema: Optional[Mapping[str, Any]] = None,
    output_model: Any = None,
    select: str = "first",
    kind: str = "auto",
) -> Any:
    """Extract and validate a run's ``final_output`` (or a plain value).

    A string output is parsed with :func:`beacon.extract_json`; a structured
    output (``output_type`` set) is validated directly. ``schema`` /
    ``output_model`` validate the value.
    """
    output = _get(result, "final_output")
    if output is None:
        output = result
    if isinstance(output, str):
        return parse_structured(output, schema=schema, model=output_model, select=select, kind=kind)
    if isinstance(output, Mapping):
        return validate_value(dict(output), schema=schema, model=output_model)
    if isinstance(output, list):
        return validate_value(list(output), schema=schema, model=output_model)
    dump = getattr(output, "model_dump", None)
    if callable(dump):
        return validate_value(dump(mode="json"), schema=schema, model=output_model)
    raise MalformedOutputError("run result has no text or structured output", code="openai_agents.no_content")
