# Type stubs for the Rust extension module. Use the wrappers in `beacon`
# instead of calling these directly; their signatures may change.
from typing import Any, Optional

VERSION: str

def unicode_version() -> str: ...
def template(source: str, variables: dict[str, Any], escape: str, strict: bool) -> str: ...
def template_variables(source: str) -> list[str]: ...
def extract_json(text: str, select: str, kind: str, required: bool) -> Any: ...
def extract_json_detailed(text: str, select: str, kind: str) -> dict[str, Any]: ...
def repair_json(text: str) -> dict[str, Any]: ...
def parse_tool_call(text: str, include_format: bool) -> dict[str, Any]: ...
def parse_tool_calls(text: str, include_format: bool) -> list[dict[str, Any]]: ...
def validate_schema(instance: Any, schema: Any) -> None: ...
def schema_errors(instance: Any, schema: Any) -> list[dict[str, str]]: ...
def normalize(
    text: str,
    form: Optional[str],
    strip_accents: bool,
    lowercase: bool,
    remove_control: bool,
    remove_zero_width: bool,
    collapse_whitespace: bool,
    preserve_newlines: bool,
    strip: bool,
) -> str: ...
def hash_content(value: Any, length: int) -> str: ...
def redact(
    text: str,
    policy: str,
    exclude: list[str],
    patterns: list[tuple[str, str]],
    terms: list[tuple[str, list[str]]],
    replacement: str,
) -> str: ...
def detect_pii(
    text: str,
    policy: str,
    exclude: list[str],
    patterns: list[tuple[str, str]],
    terms: list[tuple[str, list[str]]],
) -> list[dict[str, Any]]: ...
def retry_classify(
    type_names: list[str],
    status: Optional[int],
    retry_after: Optional[str],
    retry_after_ms: Optional[str],
    attempt: int,
    max_attempts: int,
    base_delay_ms: int,
    max_delay_ms: int,
    jitter_percent: int,
    jitter_key: str,
) -> tuple[bool, str, int, int]: ...
def retry_backoff_ms(
    attempt: int,
    max_attempts: int,
    base_delay_ms: int,
    max_delay_ms: int,
    jitter_percent: int,
    jitter_key: str,
) -> int: ...
