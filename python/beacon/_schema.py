"""Schema helpers: prompt instructions and Pydantic interop.

Pure Python and deterministic. The model helpers duck-type
``model_json_schema`` / ``model_validate`` rather than importing Pydantic, so
``import beacon`` never pulls Pydantic in. See
``docs/determinism_guarantees.md``.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from ._api import schema_errors, validate_schema

__all__ = ["schema_instructions", "schema_from_model", "validate_model"]


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


def schema_from_model(model: Any) -> dict[str, Any]:
    """Return a Pydantic model's JSON Schema as a beacon-compatible ``dict``.

    The schema is ``model.model_json_schema()`` with its beacon compatibility
    checked eagerly: nested models become ``$defs`` + ``$ref`` and
    ``Optional[...]`` becomes ``anyOf`` with ``{"type": "null"}``, all of which
    beacon's validator supports. If the model produces a schema that uses a
    keyword beacon does not support, :class:`~beacon.SchemaError` is raised here
    rather than later at validation time.

    >>> from pydantic import BaseModel  # doctest: +SKIP
    >>> class Intent(BaseModel):        # doctest: +SKIP
    ...     intent: str
    ...     confidence: float
    >>> schema_from_model(Intent)       # doctest: +SKIP
    {'type': 'object', 'properties': {...}, 'required': [...], 'title': 'Intent'}
    """
    schema = _model_schema(model)
    # Pass 1 of the validator (the schema check) runs before the instance is
    # examined, so validating any value forces beacon to accept or reject the
    # schema. A bad schema raises SchemaError; the returned violations (for the
    # throwaway ``None`` instance) are discarded.
    schema_errors(None, schema)
    return schema


def validate_model(instance: Any, model: Any) -> Any:
    """Validate ``instance`` against ``model``'s schema, then build the model.

    Validation uses :func:`beacon.validate_schema`, so a failure raises
    :class:`~beacon.SchemaValidationError` with beacon's deterministic,
    fixed-order error list (not Pydantic's). On success the data is handed to
    ``model.model_validate`` and the resulting instance is returned.

    >>> from pydantic import BaseModel  # doctest: +SKIP
    >>> class Intent(BaseModel):        # doctest: +SKIP
    ...     intent: str
    ...     confidence: float
    >>> validate_model({"intent": "cancel", "confidence": 0.93}, Intent)  # doctest: +SKIP
    Intent(intent='cancel', confidence=0.93)
    """
    schema = schema_from_model(model)
    validate_schema(instance, schema)
    return model.model_validate(instance)


def schema_instructions(schema: Any) -> str:
    """Deterministic instructions asking a model for JSON matching ``schema``.

    ``schema`` is a JSON Schema mapping or a Pydantic model class. The wording
    is stable across releases, so it can be snapshot-tested.

    >>> schema_instructions({"type": "object", "properties": {"n": {"type": "integer"}}})
    'Respond with a single JSON value that conforms to this JSON Schema:\\n```json\\n{\\n  "type": "object",\\n  "properties": {\\n    "n": {\\n      "type": "integer"\\n    }\\n  }\\n}\\n```'
    """
    body = json.dumps(_as_schema(schema), indent=2, ensure_ascii=False)
    return f"Respond with a single JSON value that conforms to this JSON Schema:\n```json\n{body}\n```"
