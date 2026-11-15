"""smolagents integration: tool input schemas and final-answer parsing.

No dependency on smolagents: ``Tool`` objects and the agent's final answer are
duck-typed, so real ``Tool`` instances, plain dicts and test fakes all work
(``pip install "llm-beacon[smolagents]"`` only to run smolagents itself).

smolagents describes each tool with an ``inputs`` mapping rather than a JSON
Schema. :func:`tool_schemas` converts those to JSON Schemas for
:func:`beacon.validate_schema` / :func:`beacon.schema_instructions`, and
:func:`parse_final_answer` extracts and validates the agent's final answer.

>>> from beacon.integrations.smolagents import parse_final_answer
>>> parse_final_answer('{"city": "Paris"}')
{'city': 'Paris'}
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from ..errors import MalformedOutputError
from ._common import parse_structured, validate_value

__all__ = ["tool_schemas", "parse_final_answer"]

# smolagents authorized input types → JSON Schema types. Non-JSON types
# (image, audio, any) carry no `type` constraint.
_JSON_TYPES = {
    "string": "string",
    "boolean": "boolean",
    "integer": "integer",
    "number": "number",
    "object": "object",
    "array": "array",
    "null": "null",
}


def _get(obj: Any, name: str) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name)
    return getattr(obj, name, None)


def _schema_for_tool(inputs: Mapping[str, Any]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    for name, spec in inputs.items():
        prop: dict[str, Any] = {}
        json_type = _JSON_TYPES.get(_get(spec, "type"))
        if json_type is not None:
            prop["type"] = json_type
        description = _get(spec, "description")
        if isinstance(description, str):
            prop["description"] = description
        properties[name] = prop
        if not _get(spec, "nullable"):
            required.append(name)
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def tool_schemas(tools: Any) -> dict[str, dict[str, Any]]:
    """Map each smolagents tool to a JSON Schema for its arguments.

    ``tools`` is an iterable of ``Tool`` objects or dicts with ``name`` and an
    ``inputs`` mapping. An input marked ``nullable`` is optional; every other
    input is required.
    """
    out: dict[str, dict[str, Any]] = {}
    for tool in tools:
        name = _get(tool, "name")
        if name is None:
            raise MalformedOutputError("smolagents tool has no name", code="smolagents.invalid_tool")
        inputs = _get(tool, "inputs")
        out[str(name)] = _schema_for_tool(inputs if isinstance(inputs, Mapping) else {})
    return out


def parse_final_answer(
    answer: Any,
    *,
    schema: Optional[Mapping[str, Any]] = None,
    output_model: Any = None,
    select: str = "first",
    kind: str = "auto",
) -> Any:
    """Extract and validate the agent's final answer.

    A string answer is parsed with :func:`beacon.extract_json`; an answer that is
    already a dict or list is validated directly. ``schema`` / ``output_model``
    validate the value.
    """
    if isinstance(answer, str):
        return parse_structured(answer, schema=schema, model=output_model, select=select, kind=kind)
    if isinstance(answer, Mapping):
        return validate_value(dict(answer), schema=schema, model=output_model)
    if isinstance(answer, list):
        return validate_value(list(answer), schema=schema, model=output_model)
    raise MalformedOutputError(
        f"final answer is not text or JSON (got {type(answer).__name__})", code="smolagents.no_content"
    )
