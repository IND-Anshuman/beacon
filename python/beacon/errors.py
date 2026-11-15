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
    "guidance_for",
    "explain_code",
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

    def _context_lines(self) -> list[str]:
        """Deterministic, human context derived from this error's fields."""
        return []

    def details(self) -> dict[str, Any]:
        """A structured, JSON-friendly view of this error.

        Deterministic: the same error always yields the same dict. Handy for
        logging the error as data or returning it over an API, without parsing
        the message string.
        """
        out: dict[str, Any] = {"code": self.code, "message": self.message}
        for key, value in self._state().items():
            if key == "code" or value is None:
                continue
            out[key] = list(value) if isinstance(value, tuple) else value
        return out

    def explain(self) -> str:
        """A long-form, human explanation: what the error is, its likely cause,
        the fix, and any position/field context.

        Deterministic and side-effect-free — no colour, clock or environment.
        The short :attr:`message` and :attr:`code` are the stable contract; this
        is extra, opt-in detail that a patch release may improve.
        """
        lines = [f"[{self.code}] {self.message}"]
        guidance = guidance_for(self.code)
        if guidance is not None:
            cause, fix = guidance
            lines += ["", f"Cause: {cause}", f"Fix:   {fix}"]
        context = self._context_lines()
        if context:
            lines.append("")
            lines += context
        return "\n".join(lines)


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

    def _context_lines(self) -> list[str]:
        out: list[str] = []
        if self.position is not None:
            where = f"offset {self.position}"
            if self.line is not None and self.column is not None:
                where = f"line {self.line}, column {self.column} ({where})"
            out.append(f"Where: {where} in the input.")
        if self.raw is not None:
            out.append("The raw model output is on the .raw attribute.")
        return out


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

    def _context_lines(self) -> list[str]:
        if not self.errors:
            return []
        out = ["Violations:"]
        shown = self.errors[:10]
        for e in shown:
            where = e.get("path") or "(root)"
            out.append(f"  {where}: {e.get('keyword', '')}: {e.get('message', '')}")
        if len(self.errors) > len(shown):
            out.append(f"  ... and {len(self.errors) - len(shown)} more")
        if self.raw is not None:
            out.append("The raw model output is on the .raw attribute.")
        return out


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

    def _context_lines(self) -> list[str]:
        if self.position is None:
            return []
        where = f"offset {self.position}"
        if self.line is not None and self.column is not None:
            where = f"line {self.line}, column {self.column} ({where})"
        return [f"Where: {where} in the template."]


class _NamesError(TemplateError):
    def __init__(self, message: str, *, code: Optional[str] = None, names: Sequence[str] = ()) -> None:
        super().__init__(message, code=code)
        self.names = tuple(names)

    def _state(self) -> dict[str, Any]:
        return {"code": self.code, "names": self.names}

    def _context_lines(self) -> list[str]:
        if not self.names:
            return []
        return [f"Variables: {', '.join(self.names)}"]


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

    def _context_lines(self) -> list[str]:
        out: list[str] = []
        if self.path is not None:
            out.append(f"Snapshot: {self.path}")
        if self.diff:
            out.append("The full diff is on the .diff attribute.")
        return out


# ---------------------------------------------------------------------------
# Deterministic, human guidance per error code — the content behind
# ``BeaconError.explain()`` and ``beacon explain <code>``. Pure data: no clock,
# environment or I/O. ``code``s and messages stay stable; this text may improve.

_GUIDANCE: dict[str, tuple[str, str]] = {
    "beacon.error": (
        "A beacon block rejected its input.",
        "Read the message and .details() for the specifics of this error.",
    ),
    "malformed_output": (
        "The model output could not be parsed into the expected structure.",
        "Inspect the raw text around .position. repair_json handles common "
        "near-JSON breakage; parse_partial handles truncation.",
    ),
    "json.not_found": (
        "The text held no JSON object or array at all.",
        "Confirm the model actually returned JSON. extract_json already sees "
        "through surrounding prose and ```code fences```; if the JSON is only "
        "slightly broken (trailing comma, single quotes, truncation), use "
        "repair_json, which fixes it and logs every change.",
    ),
    "tool_call.not_found": (
        "No tool call was found in the output.",
        "Check the model chose to call a tool at all. parse_tool_calls accepts "
        "many formats (Hermes, OpenAI/Anthropic JSON, Mistral, Llama, XML, "
        "python call syntax); include_format=True shows which each matched.",
    ),
    "schema.validation_failed": (
        "The value is valid JSON but does not satisfy the schema.",
        "Read the per-field violations (on .errors, or via schema_errors) for "
        "the exact paths that failed. beacon never coerces types, so \"42\" is "
        "not an integer - fix the value or widen the schema.",
    ),
    "schema.invalid": (
        "The schema itself is malformed or uses a keyword beacon does not "
        "support.",
        "Fix the schema. See docs/blocks_reference.md for the supported "
        "JSON Schema (draft 2020-12) keyword set.",
    ),
    "template.missing_variable": (
        "The template referenced placeholders you did not supply.",
        "Pass the named variables, or call template(..., strict=False) to leave "
        "unknown placeholders untouched. The missing names are on .names.",
    ),
    "template.extra_variable": (
        "Strict mode: you supplied variables the template never uses.",
        "Remove the unused variables, or use strict=False to ignore extras. The "
        "unused names are on .names.",
    ),
    "template.syntax": (
        "The template string is malformed (an unbalanced or bad { } placeholder).",
        "Use {{ and }} for literal braces and {name} / {name!raw} for "
        "placeholders. The position of the problem is on .position.",
    ),
    "snapshot.mismatch": (
        "The output differs from the stored snapshot, or none exists yet in "
        "check mode.",
        "If the change is intended, update snapshots (pytest --beacon-snapshot "
        "update, or python -m beacon.snapshots update). Otherwise the diff on "
        ".diff shows what changed.",
    ),
}

_FAMILY_PREFIX: dict[str, tuple[str, str]] = {
    "json": (
        "The text could not be parsed as strict JSON.",
        "extract_json is strict by design. For near-JSON (trailing commas, "
        "single quotes, comments, truncation) use repair_json; for a value "
        "still streaming in, use parse_partial.",
    ),
    "tool_call": (
        "A tool call could not be read as expected.",
        "Inspect the raw output; parse_tool_calls lists every call it can find, "
        "and include_format=True shows which format each matched.",
    ),
    "schema": (
        "A schema check failed.",
        "Use schema_errors to see the violations without raising, and check the "
        "schema uses only supported keywords.",
    ),
    "template": (
        "A template could not be rendered.",
        "Check the placeholders and the variables you passed; strict=False "
        "relaxes the missing/extra-variable errors.",
    ),
    "snapshot": (
        "A snapshot assertion failed.",
        "Review the diff, then update snapshots deliberately once the change is "
        "intended.",
    ),
}

_FAMILY_SUFFIX: dict[str, tuple[str, str]] = {
    "unknown_tool": (
        "The model called a tool that is not in the set you defined.",
        "This is usually a hallucinated tool name. Compare the call's name "
        "against your tool list (the raw output is on .raw); reject the call or "
        "re-prompt - never execute an unknown tool.",
    ),
    "invalid_arguments": (
        "The tool call's arguments did not match that tool's schema.",
        "Read .errors for the exact field violations, then re-prompt the model "
        "or correct the arguments; the raw output is on .raw.",
    ),
}


def guidance_for(code: str) -> Optional[tuple[str, str]]:
    """Deterministic ``(cause, fix)`` guidance for a beacon error ``code``.

    Matches the exact ``code`` first, then a ``*.suffix`` family (so
    ``crewai.unknown_tool`` resolves), then a ``prefix.*`` family (so
    ``json.unexpected_end`` resolves). Returns ``None`` when nothing matches.
    """
    if code in _GUIDANCE:
        return _GUIDANCE[code]
    suffix = code.rpartition(".")[2]
    if suffix in _FAMILY_SUFFIX:
        return _FAMILY_SUFFIX[suffix]
    prefix = code.partition(".")[0]
    if prefix in _FAMILY_PREFIX:
        return _FAMILY_PREFIX[prefix]
    return None


def explain_code(code: str) -> str:
    """A human explanation for a beacon error ``code`` with no instance in hand.

    This is what ``beacon explain <code>`` prints. Deterministic.
    """
    guidance = guidance_for(code)
    if guidance is None:
        return (
            f"[{code}] No specific guidance for this code.\n"
            "Known families: json.*, schema.*, tool_call.*, template.*, "
            "snapshot.*, *.unknown_tool, *.invalid_arguments."
        )
    cause, fix = guidance
    return f"[{code}]\n\nCause: {cause}\nFix:   {fix}"
