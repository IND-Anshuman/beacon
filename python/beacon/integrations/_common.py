"""Helpers shared by the integrations."""

from __future__ import annotations

import importlib
from typing import Any, Mapping, Optional

from .._api import extract_json, validate_schema
from ..errors import MalformedOutputError, SchemaValidationError


def require(module: str, extra: str, feature: str) -> Any:
    """Import ``module`` or raise an ``ImportError`` naming the pip extra."""
    try:
        return importlib.import_module(module)
    except ImportError as exc:
        raise ImportError(f"{feature} requires {module.split('.')[0]}: pip install \"llm-beacon[{extra}]\"") from exc


def optional(module: str) -> Optional[Any]:
    try:
        return importlib.import_module(module)
    except ImportError:
        return None


def schema_for(model_or_schema: Any) -> Optional[dict[str, Any]]:
    """A JSON Schema from a Pydantic model class, a mapping, or ``None``."""
    if model_or_schema is None:
        return None
    if isinstance(model_or_schema, Mapping):
        return dict(model_or_schema)
    to_schema = getattr(model_or_schema, "model_json_schema", None)
    if callable(to_schema):
        return to_schema()
    raise TypeError(f"expected a JSON Schema mapping or a Pydantic model class, got {model_or_schema!r}")


def is_model_class(obj: Any) -> bool:
    return isinstance(obj, type) and callable(getattr(obj, "model_validate", None))


def parse_structured(
    text: str,
    *,
    schema: Optional[Mapping[str, Any]] = None,
    model: Any = None,
    select: str = "first",
    kind: str = "auto",
) -> Any:
    """Extract JSON from ``text``, validate it, and optionally build ``model``.

    ``schema`` defaults to ``model.model_json_schema()``. beacon errors get the
    raw text attached as ``.raw`` for debugging.
    """
    if schema is None and model is not None:
        schema = schema_for(model)
    try:
        data = extract_json(text, select=select, kind=kind)  # type: ignore[arg-type]
        if schema is not None:
            validate_schema(data, schema)
    except (MalformedOutputError, SchemaValidationError) as exc:
        exc.raw = text
        raise
    if model is not None:
        return model.model_validate(data)
    return data
