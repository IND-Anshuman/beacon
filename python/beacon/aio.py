"""The async core: ``await``-able versions of every block.

Each function here runs its synchronous counterpart on a worker thread with
:func:`asyncio.to_thread`, so it is a true coroutine that yields to the event
loop — the loop keeps serving other tasks (your in-flight model HTTP calls, for
example) while beacon works, and no caller has to reach for ``run_in_executor``.

The result is identical to the synchronous API, which these delegate to:

    from beacon import aio
    data = await aio.extract_json(text, schema=schema)

The blocks are fast, CPU-bound and deterministic, so in *synchronous* code call
the sync functions in :mod:`beacon` directly — the thread hop here only earns
its keep when you are already on an event loop.
"""

from __future__ import annotations

import asyncio
from typing import Any, Iterable, Mapping, Optional

from . import _api, _schema
from ._api import (
    _ALL_CITATION_KINDS,
    Citation,
    CitationKind,
    Escape,
    Extraction,
    Form,
    InjectionFinding,
    InjectionPolicy,
    Kind,
    PartialResult,
    PIIFinding,
    Policy,
    RepairResult,
    SchemaViolation,
    Select,
    ToolCall,
)

__all__ = [
    "template",
    "template_variables",
    "extract_json",
    "extract_json_detailed",
    "repair_json",
    "parse_partial",
    "parse_tool_call",
    "parse_tool_calls",
    "validate_schema",
    "schema_errors",
    "schema_instructions",
    "schema_from_model",
    "validate_model",
    "normalize",
    "hash_content",
    "cache_key",
    "redact",
    "detect_pii",
    "extract_citations",
    "detect_injection",
    "scan_arguments",
]


async def template(
    source: str,
    mapping: Optional[Mapping[str, Any]] = None,
    /,
    *,
    strict: bool = True,
    escape: Escape = "xml",
    **variables: Any,
) -> str:
    """Async version of :func:`beacon.template`."""
    return await asyncio.to_thread(_api.template, source, mapping, strict=strict, escape=escape, **variables)


async def template_variables(source: str) -> list[str]:
    """Async version of :func:`beacon.template_variables`."""
    return await asyncio.to_thread(_api.template_variables, source)


async def extract_json(
    text: str,
    *,
    schema: Optional[Mapping[str, Any]] = None,
    select: Select = "first",
    kind: Kind = "auto",
    required: bool = True,
) -> Any:
    """Async version of :func:`beacon.extract_json`."""
    return await asyncio.to_thread(_api.extract_json, text, schema=schema, select=select, kind=kind, required=required)


async def extract_json_detailed(text: str, *, select: Select = "first", kind: Kind = "auto") -> Extraction:
    """Async version of :func:`beacon.extract_json_detailed`."""
    return await asyncio.to_thread(_api.extract_json_detailed, text, select=select, kind=kind)


async def repair_json(text: str, *, schema: Optional[Mapping[str, Any]] = None) -> RepairResult:
    """Async version of :func:`beacon.repair_json`."""
    return await asyncio.to_thread(_api.repair_json, text, schema=schema)


async def parse_partial(text: str) -> PartialResult:
    """Async version of :func:`beacon.parse_partial`."""
    return await asyncio.to_thread(_api.parse_partial, text)


async def parse_tool_call(text: str) -> ToolCall:
    """Async version of :func:`beacon.parse_tool_call`."""
    return await asyncio.to_thread(_api.parse_tool_call, text)


async def parse_tool_calls(text: str, *, include_format: bool = False) -> list[dict[str, Any]]:
    """Async version of :func:`beacon.parse_tool_calls`."""
    return await asyncio.to_thread(_api.parse_tool_calls, text, include_format=include_format)


async def validate_schema(instance: Any, schema: Mapping[str, Any]) -> None:
    """Async version of :func:`beacon.validate_schema`."""
    return await asyncio.to_thread(_api.validate_schema, instance, schema)


async def schema_errors(instance: Any, schema: Mapping[str, Any]) -> list[SchemaViolation]:
    """Async version of :func:`beacon.schema_errors`."""
    return await asyncio.to_thread(_api.schema_errors, instance, schema)


async def schema_instructions(schema: Any) -> str:
    """Async version of :func:`beacon.schema_instructions`."""
    return await asyncio.to_thread(_schema.schema_instructions, schema)


async def schema_from_model(model: Any) -> dict[str, Any]:
    """Async version of :func:`beacon.schema_from_model`."""
    return await asyncio.to_thread(_schema.schema_from_model, model)


async def validate_model(instance: Any, model: Any) -> Any:
    """Async version of :func:`beacon.validate_model`."""
    return await asyncio.to_thread(_schema.validate_model, instance, model)


async def normalize(
    text: str,
    *,
    form: Optional[Form] = "NFKC",
    strip_accents: bool = False,
    lowercase: bool = False,
    remove_control: bool = True,
    remove_zero_width: bool = True,
    collapse_whitespace: bool = True,
    preserve_newlines: bool = False,
    strip: bool = True,
) -> str:
    """Async version of :func:`beacon.normalize`."""
    return await asyncio.to_thread(
        _api.normalize,
        text,
        form=form,
        strip_accents=strip_accents,
        lowercase=lowercase,
        remove_control=remove_control,
        remove_zero_width=remove_zero_width,
        collapse_whitespace=collapse_whitespace,
        preserve_newlines=preserve_newlines,
        strip=strip,
    )


async def hash_content(value: Any, *, length: int = 16) -> str:
    """Async version of :func:`beacon.hash_content`."""
    return await asyncio.to_thread(_api.hash_content, value, length=length)


async def cache_key(*parts: Any, length: int = 32) -> str:
    """Async version of :func:`beacon.cache_key`."""
    return await asyncio.to_thread(lambda: _api.cache_key(*parts, length=length))


async def redact(
    text: str,
    *,
    policy: Policy = "default",
    exclude: Iterable[str] = (),
    patterns: Optional[Mapping[str, str]] = None,
    terms: Optional[Mapping[str, Iterable[str]]] = None,
    replacement: str = "[REDACTED:{label}]",
) -> str:
    """Async version of :func:`beacon.redact`."""
    return await asyncio.to_thread(
        _api.redact, text, policy=policy, exclude=exclude, patterns=patterns, terms=terms, replacement=replacement
    )


async def detect_pii(
    text: str,
    *,
    policy: Policy = "default",
    exclude: Iterable[str] = (),
    patterns: Optional[Mapping[str, str]] = None,
    terms: Optional[Mapping[str, Iterable[str]]] = None,
) -> list[PIIFinding]:
    """Async version of :func:`beacon.detect_pii`."""
    return await asyncio.to_thread(
        _api.detect_pii, text, policy=policy, exclude=exclude, patterns=patterns, terms=terms
    )


async def extract_citations(
    text: str,
    *,
    kinds: Iterable[CitationKind] = _ALL_CITATION_KINDS,
) -> list[Citation]:
    """Async version of :func:`beacon.extract_citations`."""
    return await asyncio.to_thread(_api.extract_citations, text, kinds=kinds)


async def detect_injection(text: str, *, policy: InjectionPolicy = "default") -> list[InjectionFinding]:
    """Async version of :func:`beacon.detect_injection`."""
    return await asyncio.to_thread(_api.detect_injection, text, policy=policy)


async def scan_arguments(arguments: Any, *, policy: InjectionPolicy = "default") -> list[InjectionFinding]:
    """Async version of :func:`beacon.scan_arguments`."""
    return await asyncio.to_thread(_api.scan_arguments, arguments, policy=policy)
