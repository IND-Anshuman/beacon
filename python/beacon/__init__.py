"""beacon â€” deterministic, tested building blocks for AI pipelines.

Every block is a pure function: same input â†’ same output, every time, on
every machine. See ``docs/determinism_guarantees.md`` for the contract.
"""

from __future__ import annotations

from . import _beacon_native, aio, retry
from ._api import (
    Extraction,
    PartialResult,
    PIIFinding,
    Repair,
    RepairResult,
    SchemaViolation,
    ToolCall,
    cache_key,
    detect_pii,
    extract_json,
    extract_json_detailed,
    hash_content,
    normalize,
    parse_partial,
    parse_tool_call,
    parse_tool_calls,
    redact,
    repair_json,
    schema_errors,
    template,
    template_variables,
    validate_schema,
)
from ._blocks import Block, Pipeline, PipelineResult, StepRecord
from ._schema import schema_from_model, schema_instructions, validate_model
from .errors import (
    BeaconError,
    ExtraVariableError,
    MalformedOutputError,
    MissingVariableError,
    NoJSONFoundError,
    NoToolCallFoundError,
    SchemaError,
    SchemaValidationError,
    SnapshotMismatchError,
    TemplateError,
    TemplateSyntaxError,
)
from .retry import RetryAction, RetryDecision, RetryPolicy, RetryReason

__version__: str = _beacon_native.VERSION

#: Unicode version of the normalization tables used by :func:`normalize`.
UNICODE_VERSION: str = _beacon_native.unicode_version()

__all__ = [
    # blocks
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
    "retry",
    "aio",
    # result types
    "Extraction",
    "RepairResult",
    "Repair",
    "PartialResult",
    "ToolCall",
    "SchemaViolation",
    "PIIFinding",
    "RetryAction",
    "RetryDecision",
    "RetryPolicy",
    "RetryReason",
    # composition
    "Block",
    "Pipeline",
    "PipelineResult",
    "StepRecord",
    # errors
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
    "__version__",
    "UNICODE_VERSION",
]
