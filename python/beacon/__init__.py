"""beacon — deterministic, tested building blocks for AI pipelines.

Every block is a pure function: same input → same output, every time, on
every machine. See ``docs/determinism_guarantees.md`` for the contract.
"""

from __future__ import annotations

from . import _beacon_native, retry
from ._api import (
    Extraction,
    PIIFinding,
    Repair,
    RepairResult,
    SchemaViolation,
    ToolCall,
    detect_pii,
    extract_json,
    extract_json_detailed,
    hash_content,
    normalize,
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
    "parse_tool_call",
    "parse_tool_calls",
    "validate_schema",
    "schema_errors",
    "schema_instructions",
    "schema_from_model",
    "validate_model",
    "normalize",
    "hash_content",
    "redact",
    "detect_pii",
    "retry",
    # result types
    "Extraction",
    "RepairResult",
    "Repair",
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
