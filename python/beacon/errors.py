"""Exception hierarchy for beacon.

Every exception carries a stable ``code`` (e.g. ``"json.unexpected_end"``).
Codes, classes and message text are part of beacon's compatibility contract:
they do not change in patch releases. See ``docs/blocks_reference.md`` for the
full list.

::

    BeaconError
    ├── MalformedOutputError (ValueError)
    │   ├── NoJSONFoundError
    │   └── NoToolCallFoundError
    ├── SchemaValidationError (ValueError)
    ├── SchemaError (ValueError)
    ├── TemplateError (ValueError)
    │   ├── TemplateSyntaxError
    │   ├── MissingVariableError
    │   └── ExtraVariableError
    └── SnapshotMismatchError (AssertionError)
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

__all__ = [
    "BeaconError",
    "MalformedOutputError",
    "NoJSONFoundError",
    "NoToolCallFoundError",
    "SchemaValidationError",
    "SchemaError",
    "TemplateError",
    "TemplateSyntaxError",
    "MissingVariableError",
    "ExtraVariableError",
    "SnapshotMismatchError",
]


class BeaconError(Exception):
    """Base class for every error raised by beacon."""

    default_code = "beacon.error"

    def __init__(self, message: str, *, code: Optional[str] = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or self.default_code

    def _state(self) -> dict[str, Any]:
        return {"code": self.code}

    def __reduce__(self) -> Any:
        # Keep keyword-only attributes when pickled (e.g. across processes).
        return (_rebuild, (type(self), self.message, self._state()))

    def __str__(self) -> str:
        return self.message


def _rebuild(cls: type, message: str, state: dict[str, Any]) -> BeaconError:
    return cls(message, **state)


class MalformedOutputError(BeaconError, ValueError):
    """LLM output could not be parsed.

    Attributes:
        position: code-point offset of the problem in the input text, if known.
        line, column: 1-based line and column of ``position``.
        raw: the raw LLM output, attached by integrations for debugging.
    """

    default_code = "malformed_output"

    def __init__(
        self,
        message: str,
        *,
        code: Optional[str] = None,
        position: Optional[int] = None,
        line: Optional[int] = None,
        column: Optional[int] = None,
        raw: Optional[str] = None,
    ) -> None:
        super().__init__(message, code=code)
        self.position = position
        self.line = line
        self.column = column
        self.raw = raw

    def _state(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "position": self.position,
            "line": self.line,
            "column": self.column,
            "raw": self.raw,
        }


class NoJSONFoundError(MalformedOutputError):
    """The text contains no JSON object or array."""

    default_code = "json.not_found"


class NoToolCallFoundError(MalformedOutputError):
    """The text contains no tool call."""

    default_code = "tool_call.not_found"


class SchemaValidationError(BeaconError, ValueError):
    """A value does not satisfy a JSON Schema.

    Attributes:
        errors: list of ``{"path", "keyword", "message"}`` dicts in the
            documented, fixed order. ``path`` is a JSON Pointer into the value
            (``""`` is the root).
        raw: the raw LLM output, attached by integrations for debugging.
    """

    default_code = "schema.validation_failed"

    def __init__(
        self,
        message: str,
        *,
        code: Optional[str] = None,
        errors: Sequence[dict[str, str]] = (),
        raw: Optional[str] = None,
    ) -> None:
        super().__init__(message, code=code)
        self.errors = [dict(e) for e in errors]
        self.raw = raw

    def _state(self) -> dict[str, Any]:
        return {"code": self.code, "errors": self.errors, "raw": self.raw}


class SchemaError(BeaconError, ValueError):
    """The schema itself is invalid or uses an unsupported keyword."""

    default_code = "schema.invalid"


class TemplateError(BeaconError, ValueError):
    """Base class for template errors."""

    default_code = "template.error"


class TemplateSyntaxError(TemplateError):
    """The template string is malformed."""

    default_code = "template.syntax"

    def __init__(
        self,
        message: str,
        *,
        code: Optional[str] = None,
        position: Optional[int] = None,
        line: Optional[int] = None,
        column: Optional[int] = None,
    ) -> None:
        super().__init__(message, code=code)
        self.position = position
        self.line = line
        self.column = column

    def _state(self) -> dict[str, Any]:
        return {"code": self.code, "position": self.position, "line": self.line, "column": self.column}


class _NamesError(TemplateError):
    def __init__(self, message: str, *, code: Optional[str] = None, names: Sequence[str] = ()) -> None:
        super().__init__(message, code=code)
        self.names = tuple(names)

    def _state(self) -> dict[str, Any]:
        return {"code": self.code, "names": self.names}


class MissingVariableError(_NamesError):
    """The template uses variables that were not provided. ``names`` is sorted."""

    default_code = "template.missing_variable"


class ExtraVariableError(_NamesError):
    """Strict mode: variables were provided but not used. ``names`` is sorted."""

    default_code = "template.extra_variable"


class SnapshotMismatchError(BeaconError, AssertionError):
    """A snapshot differs from the stored one, or is missing in ``check`` mode."""

    default_code = "snapshot.mismatch"

    def __init__(self, message: str, *, code: Optional[str] = None, path: Optional[str] = None, diff: str = "") -> None:
        super().__init__(message, code=code)
        self.path = path
        self.diff = diff

    def _state(self) -> dict[str, Any]:
        return {"code": self.code, "path": self.path, "diff": self.diff}
