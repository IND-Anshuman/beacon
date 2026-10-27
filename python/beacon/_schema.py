"""Schema helpers: prompt instructions and Pydantic interop.

Pure Python and deterministic. The model helpers duck-type
``model_json_schema`` / ``model_validate`` rather than importing Pydantic, so
``import beacon`` never pulls Pydantic in. See
``docs/determinism_guarantees.md``.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

__all__ = ["schema_instructions"]


def _model_schema(model: Any) -> dict[str, Any]:
    """The JSON Schema of a Pydantic model class (or any object exposing
    ``model_json_schema``)."""
    to_schema = getattr(model, "model_json_schema", None)
    if not callable(to_schema):
        raise TypeError(
            f"expected a Pydantic model class with a model_json_schema() method, got {model!r}"
        )
    schema = to_schema()
    if not isinstance(schema, Mapping):
        raise TypeError(f"model_json_schema() must return a mapping, got {type(schema).__name__}")
    return dict(schema)


def _as_schema(schema_or_model: Any) -> dict[str, Any]:
    """A JSON Schema ``dict`` from a mapping or a Pydantic model class."""
    if isinstance(schema_or_model, Mapping):
        return dict(schema_or_model)
    return _model_schema(schema_or_model)


def schema_instructions(schema: Any) -> str:
    """Deterministic instructions asking a model for JSON matching ``schema``.

    ``schema`` is a JSON Schema mapping or a Pydantic model class. The wording
    is stable across releases, so it can be snapshot-tested.

    >>> schema_instructions({"type": "object", "properties": {"n": {"type": "integer"}}})
    'Respond with a single JSON value that conforms to this JSON Schema:\\n```json\\n{\\n  "type": "object",\\n  "properties": {\\n    "n": {\\n      "type": "integer"\\n    }\\n  }\\n}\\n```'
    """
    body = json.dumps(_as_schema(schema), indent=2, ensure_ascii=False)
    return f"Respond with a single JSON value that conforms to this JSON Schema:\n```json\n{body}\n```"
