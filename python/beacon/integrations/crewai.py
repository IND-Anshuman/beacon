"""CrewAI integration: validate task/crew output as structured JSON.

No dependency on CrewAI: the output is duck-typed, so ``TaskOutput`` /
``CrewOutput`` objects, plain dicts and test fakes all work
(``pip install "llm-beacon[crewai]"`` only to run CrewAI itself).

A CrewAI result exposes up to three views of the same answer — ``raw`` text,
``json_dict``, and a ``pydantic`` model. :func:`parse_output` prefers an
already-structured view and otherwise extracts JSON from the raw text, then
validates against ``schema`` / ``output_model``.

>>> from beacon.integrations.crewai import parse_output
>>> parse_output({"raw": 'Result: {"ok": true}'})
{'ok': True}
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from ..errors import MalformedOutputError
from ._common import parse_structured, validate_value

__all__ = ["raw_text", "parse_output"]


def _get(obj: Any, name: str) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name)
    return getattr(obj, name, None)


def raw_text(output: Any) -> str:
    """The raw text of a CrewAI task/crew output (or a plain string).

    Raises :class:`~beacon.MalformedOutputError` (code ``crewai.no_content``)
    when there is no ``raw`` text.
    """
    if isinstance(output, str):
        return output
    raw = _get(output, "raw")
    if isinstance(raw, str):
        return raw
    raise MalformedOutputError("CrewAI output has no raw text", code="crewai.no_content")


def _structured(output: Any) -> Optional[Any]:
    json_dict = _get(output, "json_dict")
    if isinstance(json_dict, Mapping):
        return dict(json_dict)
    pydantic = _get(output, "pydantic")
    if pydantic is not None:
        dump = getattr(pydantic, "model_dump", None)
        if callable(dump):
            return dump(mode="json")
    return None


def parse_output(
    output: Any,
    *,
    schema: Optional[Mapping[str, Any]] = None,
    output_model: Any = None,
    select: str = "first",
    kind: str = "auto",
) -> Any:
    """Structured, validated JSON from a CrewAI task/crew output.

    Uses the output's ``json_dict`` or ``pydantic`` view when present, otherwise
    extracts JSON from its ``raw`` text with :func:`beacon.extract_json`.
    ``schema`` / ``output_model`` validate the value; a violation attaches the
    offending value as ``.raw``.
    """
    value = _structured(output)
    if value is None:
        return parse_structured(raw_text(output), schema=schema, model=output_model, select=select, kind=kind)
    return validate_value(value, schema=schema, model=output_model)
