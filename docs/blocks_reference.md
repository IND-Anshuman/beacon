# Blocks reference

Every block is a pure function (see
[determinism_guarantees.md](determinism_guarantees.md)). Positions in errors
and results are **code-point offsets** into the Python `str`, plus 1-based
`line`/`column`. Positional error messages end with `(line L, column C)`.

- [template](#template)
- [extract_json](#extract_json)
- [parse_tool_call](#parse_tool_call)
- [validate_schema](#validate_schema)
- [normalize](#normalize)
- [hash_content](#hash_content)
- [redact / detect_pii](#redact--detect_pii)
- [retry](#retry)
- [Pipeline / Block](#pipeline--block)
- [Error codes](#error-codes)

---

## template

```python
template(source, mapping=None, /, *, strict=True, escape="xml", **variables) -> str
template_variables(source) -> list[str]
```

| Syntax | Meaning |
| --- | --- |
| `{name}` | substitute `name` (`[A-Za-z_][A-Za-z0-9_]*`), escaped per `escape` |
| `{name!raw}` | substitute without escaping |
| `{{`, `}}` | literal `{`, `}` |

Anything else in braces is a `TemplateSyntaxError`: format specs
(`{x:.2f}`), attribute/index access (`{x.y}`, `{x[0]}`), positional fields
(`{}`, `{0}`), spaces (`{ x }`), other conversions (`{x!r}`).

* **Single pass.** Values are inserted literally; `{b}` inside a value is never
  expanded.
* **Values** must be `str`, `int`, `float` or `bool` (converted with `str()`).
  Other types raise `TypeError`, so serialize them explicitly.
* **`strict=True`** (default): missing variables → `MissingVariableError`;
  unused variables → `ExtraVariableError`. Missing is checked first. `names`
  is sorted.
* **`strict=False`**: missing placeholders stay as written (`{name}`); extras
  are ignored.
* **`escape`**:
  * `"xml"` (default): `&` → `&amp;`, `<` → `&lt;`, `>` → `&gt;`, so a value
    cannot close `</user_input>` and inject instructions outside the tag.
  * `"json"`: escaped for use inside a JSON string literal (quotes, backslash,
    control characters).
  * `"none"`: unchanged.

Escaping reduces structural prompt injection, but it does not make untrusted
text safe on its own. Keep untrusted input inside clearly delimited sections.

## extract_json

```python
extract_json(text, *, schema=None, select="first", kind="auto", required=True) -> Any
extract_json_detailed(text, *, select="first", kind="auto") -> Extraction
```

**Algorithm**

1. **Fences.** A line starting (≤ 3 spaces) with ```` ``` ```` or `~~~` opens a
   fence, closed by a line with the same character repeated at least as many
   times. An unclosed fence runs to the end of the text (a truncated
   response). *JSON fences* are fences labelled `json` (case-insensitive), or
   unlabelled fences whose content starts with `{` or `[`. If any JSON fence
   exists, **only** JSON fences are candidates, and each must contain exactly
   one JSON document.
2. **Inline scan.** Otherwise the text is scanned left to right; at each `{`
   or `[` a strict JSON value is parsed. Success → candidate, scanning resumes
   after it. A failure at a *JSON-like opener* (`{` followed by `"`, `'` or `}`;
   `[` followed by `{`, `[`, `"` or `]`; whitespace allowed in between) is a
   *malformed candidate*, and scanning resumes after the failure point.
   Values nested inside a failed value are never returned. Other failures
   (`{name}`, `[1-3]`, `[see below]`) are treated as prose.
3. **`kind`.** `"auto"` keeps objects if any exist, else arrays, which skips
   citation markers like `[1]`. `"object"`, `"array"` or `"any"` (text order).
4. **`select`.** `"first"`, `"last"`, `"largest"` (by length; ties → first;
   raises if any candidate is malformed) or `"only"` (more than one candidate
   raises `extract_json.multiple_candidates`). Selecting a malformed candidate
   raises its parse error.

**Parsing is strict RFC 8259:** no trailing commas, comments, single quotes,
unquoted keys, `NaN`/`Infinity`, leading zeros, unescaped control characters,
lone surrogates or duplicate keys. Nesting deeper than 512 levels raises
`json.too_deep`. Integers of any size become exact `int`s; numbers with a
fraction or exponent become `float`s (correctly rounded; overflow raises
`json.number_out_of_range`). Key order is preserved.

`required=False` returns `None` when there is no candidate at all. Malformed
JSON still raises. `schema=` validates the result with `validate_schema`.

`Extraction` fields: `value`, `start`, `end` (code points of the JSON text),
`source` (`"whole"`, `"fence"`, `"inline"`), `candidates` (count after the
kind filter).

## parse_tool_call

```python
parse_tool_call(text) -> {"name": str, "arguments": dict}
parse_tool_calls(text, *, include_format=False) -> list[dict]
```

Formats are tried in tiers; the first tier that finds anything wins:

| Tier | Format id | Example |
| --- | --- | --- |
| 1 tagged | `hermes` | `<tool_call>{"name": "f", "arguments": {...}}</tool_call>` |
| | `bracket` | `[TOOL_CALL]name=f;args={...}[/TOOL_CALL]` or `[TOOL_CALL]{json}[/TOOL_CALL]` |
| | `mistral` | `[TOOL_CALLS] [{"name": "f", "arguments": {...}}]`, `[TOOL_CALLS]f[ARGS]{...}` |
| | `llama` | `<\|python_tag\|>{"name": "f", "parameters": {...}}`, `<\|python_tag\|>tool.call(k=v)` |
| | `xml_invoke` | `<invoke name="f"><parameter name="k">v</parameter></invoke>` |
| 2 JSON | `json` | `{"name", "arguments"\|"parameters"\|"input"\|"args"}`, `{"type": "tool_use", ...}`, `{"function": {...}}`, `{"tool_calls": [...]}`, `{"function_call": {...}}`, or an array of calls |
| 3 call syntax | `python` | `search(query="rust", limit=5)` |

Details:

* Within tier 1, calls are returned in text order.
* JSON objects only count as calls when they have a call shape. For the plain
  `name` + arguments shape, only `name`, one arguments key, and `id`, `type`,
  `call_id`, `index` may be present. `{"name": "Alice", "age": 3}` is data,
  not a call.
* `arguments` given as a JSON **string** (OpenAI) is parsed strictly and must
  be an object.
* `<parameter>` values in `xml_invoke` that parse as strict JSON become JSON
  values; anything else is a string (XML entities decoded).
* Python call syntax supports keyword arguments only. Values may be Python or
  JSON literals: strings in either quote style, numbers,
  `True`/`False`/`None`/`true`/`false`/`null`, lists, tuples (→ lists),
  and dicts with string keys. A call is only recognised if its parentheses
  are empty or start with `name=`. So `f(x)` in prose is not a call, and
  `search('rust')` counts as *no tool call*.
* `parse_tool_call` raises `tool_call.multiple` if there is more than one.

## validate_schema

```python
validate_schema(instance, schema) -> None       # raises SchemaValidationError
schema_errors(instance, schema) -> list[{"path", "keyword", "message"}]
```

**Supported keywords** (JSON Schema 2020-12 subset): `$ref` (local `#...`
pointers only), `$defs`, `definitions`, `type`, `enum`, `const`, `minLength`,
`maxLength`, `pattern`, `minimum`, `maximum`, `exclusiveMinimum`,
`exclusiveMaximum`, `multipleOf`, `minItems`, `maxItems`, `uniqueItems`,
`prefixItems`, `items`, `contains`, `minContains`, `maxContains`, `required`,
`dependentRequired`, `minProperties`, `maxProperties`, `propertyNames`,
`properties`, `patternProperties`, `additionalProperties`, `allOf`, `anyOf`,
`oneOf`, `not`, `if`/`then`/`else`, boolean schemas.

**Ignored annotations:** `$schema`, `$id`, `$comment`, `$anchor`, `title`,
`description`, `default`, `examples`, `deprecated`, `readOnly`, `writeOnly`,
`format`, `contentEncoding`, `contentMediaType`, `contentSchema`,
`discriminator`, `$vocabulary`.

**Any other keyword raises `SchemaError`.** The schema is checked fully
before validation, so a bad schema fails for every instance.

Semantics:

* **No coercion.** `"42"` is not a number. `True` is not an integer. `1.0` *is*
  an integer (JSON Schema rule).
* String lengths count code points. `pattern` uses Rust regex syntax (no
  look-around or backreferences) and is unanchored, as in JSON Schema.
* `multipleOf` is exact for decimals (`0.3` is a multiple of `0.1`).
* `enum`/`const`/`uniqueItems` use JSON equality (`1 == 1.0`, key order
  ignored, `True != 1`).
* Combined depth of schema nesting, `$ref` hops and instance nesting is
  limited to 256 (a cyclic `$ref` raises `SchemaError`).

**Error order** at each node: `$ref` → `type` (on failure, nothing else is
checked at that node) → `enum`, `const` → string / number / array / object
keywords → `allOf`, `anyOf`, `oneOf`, `not`, `if`/`then`/`else`. Object
keywords run in the order `required` → `dependentRequired` →
`min/maxProperties` → `propertyNames`, then members in **instance key order**
(`properties`, `patternProperties`, `additionalProperties`). Array items go in
index order.

**Unions.** If an `anyOf`/`oneOf` fails and every branch but one failed only
on `type` at the value itself, that remaining branch's errors are reported.
This is the branch the value was evidently meant for, as with
`Optional[Model]`. Otherwise one summary error is reported.

`SchemaValidationError.errors` holds the list. `str(error)` is:

```
2 schema violations:
  - /intent: "explode" is not one of ["cancel", "refund", "question"]
  - /confidence: 1.5 is greater than the maximum of 1
```

## normalize

```python
normalize(text, *, form="NFKC", strip_accents=False, lowercase=False,
          remove_control=True, remove_zero_width=True,
          collapse_whitespace=True, preserve_newlines=False, strip=True) -> str
```

Steps, always in this order:

1. Unicode normalization: `form` = `"NFC"`, `"NFD"`, `"NFKC"`, `"NFKD"` or `None`.
2. `strip_accents`: decompose, drop combining marks (General Category M),
   re-apply `form`. Meant for Latin-script text: it also removes vowel signs
   in scripts such as Devanagari.
3. `lowercase`: full Unicode default case mapping (locale-independent; `İ` →
   `i̇`, final sigma handled).
4. `remove_control`: drop category Cc except whitespace.
5. `remove_zero_width`: drop U+200B, U+2060, U+FEFF. ZWJ/ZWNJ (emoji, Indic
   scripts) and bidi marks are kept.
6. `collapse_whitespace`: each run of Unicode whitespace becomes one space.
   With `preserve_newlines`, a run that contains a line break becomes `\n`.
7. `strip`: trim leading/trailing whitespace.

`beacon.UNICODE_VERSION` reports the Unicode version of the tables.

## hash_content

```python
hash_content(value, *, length=16) -> str
```

BLAKE3 over the canonical encoding documented in
[determinism_guarantees.md](determinism_guarantees.md#canonical-encoding-used-by-hash_content).
`length` is 1–64 hex characters. Dict keys are sorted, list order matters,
and types are distinguished. Supports `None`, `bool`, `int` (any size), `float`
(all NaNs equal), `str`, `bytes`, `list`, `tuple` (same as list), and `dict`
with `str` keys. Subclasses such as `str`-enums hash as their base type.

## redact / detect_pii

```python
redact(text, *, policy="default", exclude=(), patterns=None, terms=None,
       replacement="[REDACTED:{label}]") -> str
detect_pii(text, *, policy="default", exclude=(), patterns=None, terms=None)
    -> list[{"label", "start", "end", "text"}]
```

| Label | Detects | Validation |
| --- | --- | --- |
| `private_key` | PEM `-----BEGIN … PRIVATE KEY-----` blocks | |
| `jwt` | `eyJ….eyJ….sig` | |
| `bearer_token` | the token after `Bearer` | |
| `api_key` | OpenAI `sk-…`, Anthropic `sk-ant-…`, GitHub `ghp_…`/`github_pat_…`, Slack `xox?-…`, Google `AIza…`, Stripe `sk_live_…`, Hugging Face `hf_…` | |
| `aws_access_key` | `AKIA…`/`ASIA…` | |
| `email` | addresses, including internationalized local parts | |
| `credit_card` | 13–19 digits, optional spaces/dashes | Luhn checksum |
| `ssn` | `NNN-NN-NNNN` | not 000/666/9xx area, 00 group, 0000 serial |
| `phone` | `+CC …` international (9–15 digits), `(NNN) NNN-NNNN` / `NNN-NNN-NNNN` | digit count, no adjacent digits/letters |
| `ipv6` | IPv6 addresses | parsed by `std::net::Ipv6Addr` |
| `ipv4` | dotted quads 0–255 | |

Policies: `default` = all except `ipv4`/`ipv6`; `strict` = all; `secrets` =
`private_key`, `jwt`, `bearer_token`, `api_key`, `aws_access_key`; `pii` =
`email`, `credit_card`, `ssn`, `phone`; `none`.

* `exclude`: built-in labels to turn off.
* `patterns`: `{label: regex}` (Rust regex syntax, compiled per call).
* `terms`: `{label: [terms]}` matched as whole words, ASCII
  case-insensitive, leftmost-longest.
* Labels must match `[a-z][a-z0-9_]*`.
* `replacement` may contain `{label}` and `{hash}` (first 8 hex digits of
  BLAKE3 of the matched text, so the same value always gets the same token)
  and `{{`/`}}`.

**Overlaps:** all matches are sorted by start, then longer first, then
priority (the table order above, then `patterns` in the order given, then
`terms`). A match is kept only if it doesn't overlap one already kept.

## retry

```python
retry.classify(error, *, attempt=1, policy=RetryPolicy()) -> RetryDecision
retry.backoff_delay(attempt, *, policy=RetryPolicy()) -> float
retry.call(fn, *args, policy=..., sleep=time.sleep, on_retry=None, **kwargs)
```

`RetryDecision(action, reason, delay_seconds, attempt, retryable)`, where
`action` is a `RetryAction` and `reason` a `RetryReason` (both `str` enums).

Classification order:

1. **Status code** (`status_code`, `status`, `http_status`, or
   `response.status_code`; or a bare `int` passed as `error`):
   408 timeout · 409 conflict · 429 rate_limit · 503/529 overloaded ·
   other 5xx server_error · 401/403 auth_error · 404 not_found ·
   400/422 bad_request · 413 request_too_large · other 4xx client_error.
2. **Class names in the MRO** (most-derived first, any module), e.g.
   `RateLimitError`, `OverloadedError`, `APITimeoutError`, `ReadTimeout`,
   `TimeoutError`, `APIConnectionError`, `ConnectionError`,
   `AuthenticationError`, `BadRequestError`, `NotFoundError`,
   `ResourceExhausted`, `ServiceUnavailable`, `DeadlineExceeded`.
3. Otherwise `unknown_error`.

Retryable reasons: rate_limit, overloaded, server_error, timeout,
connection_error, conflict. `action` is `RETRY` only if the reason is
retryable and `attempt < policy.max_attempts`.

**Delay**: a numeric `retry-after-ms` or `retry-after` response header is
used if present, capped at `max_delay_ms`. HTTP-date values are ignored,
since using them would need the clock. Otherwise
`min(max_delay_ms, base_delay_ms · 2^(attempt-1))` minus jitter. Jitter is
`blake3(jitter_key ‖ 0x00 ‖ attempt) mod (span + 1)`, where `span =
delay · jitter_percent / 100`. All arithmetic is in integer milliseconds.

`RetryPolicy(max_attempts=5, base_delay_ms=1000, max_delay_ms=60000,
jitter_percent=20, jitter_key="")`.

## Pipeline / Block

```python
class Block:            # override run()
Pipeline(blocks, name="")
Pipeline.run(*args, **kwargs)
Pipeline.run_traced(*args, **kwargs) -> PipelineResult(output, steps)
```

The first block receives the arguments, and each later block receives the
previous output. Plain callables are wrapped automatically. `run_traced`
records `hash_content` of every step's input and output (`None` if not
hashable). `PipelineResult.trace()` returns plain dicts ready for
`assert_snapshot`.

## Error codes

Codes are stable (see the compatibility rules in
[determinism_guarantees.md](determinism_guarantees.md)).

| Code | Raised by | Exception |
| --- | --- | --- |
| `json.unexpected_end` | truncated JSON | `MalformedOutputError` |
| `json.unterminated_string` | string never closed | `MalformedOutputError` |
| `json.expected_value` | e.g. `NaN`, unquoted words, non-JSON fence | `MalformedOutputError` |
| `json.expected_key` | unquoted or single-quoted key | `MalformedOutputError` |
| `json.expected_colon` | missing `:` | `MalformedOutputError` |
| `json.expected_comma` | missing `,` | `MalformedOutputError` |
| `json.trailing_comma` | `[1,]`, `{"a":1,}` | `MalformedOutputError` |
| `json.invalid_literal` | `tru`, `True`, `None` | `MalformedOutputError` |
| `json.invalid_number` | `01`, `1.`, `.5` | `MalformedOutputError` |
| `json.number_out_of_range` | `1e999` | `MalformedOutputError` |
| `json.invalid_escape` | `"\q"` | `MalformedOutputError` |
| `json.invalid_unicode_escape` | bad `\u` digits | `MalformedOutputError` |
| `json.lone_surrogate` | unpaired `\ud800` | `MalformedOutputError` |
| `json.control_character` | raw newline in a string | `MalformedOutputError` |
| `json.duplicate_key` | `{"a":1,"a":2}` | `MalformedOutputError` |
| `json.too_deep` | > 512 levels | `MalformedOutputError` |
| `json.trailing_characters` | extra text in a JSON fence | `MalformedOutputError` |
| `json.not_found` | no JSON at all | `NoJSONFoundError` |
| `extract_json.multiple_candidates` | `select="only"` | `MalformedOutputError` |
| `tool_call.not_found` | no call | `NoToolCallFoundError` |
| `tool_call.multiple` | `parse_tool_call` with > 1 call | `MalformedOutputError` |
| `tool_call.invalid_name` | empty / non-string name | `MalformedOutputError` |
| `tool_call.invalid_arguments` | arguments not an object / bad JSON string | `MalformedOutputError` |
| `tool_call.ambiguous_arguments` | two arguments keys | `MalformedOutputError` |
| `tool_call.unrecognized` | tagged content that isn't a call | `MalformedOutputError` |
| `tool_call.positional_argument` | `f(q=1, 2)` | `MalformedOutputError` |
| `tool_call.duplicate_argument` | `f(q=1, q=2)` | `MalformedOutputError` |
| `tool_call.duplicate_key`, `tool_call.expected_key`, `tool_call.expected_colon`, `tool_call.expected_comma`, `tool_call.expected_value`, `tool_call.unterminated_string`, `tool_call.invalid_escape`, `tool_call.unexpected_end`, `tool_call.trailing_characters`, `tool_call.too_deep` | call-syntax literals | `MalformedOutputError` |
| `template.unmatched_close`, `template.unterminated`, `template.nested_brace`, `template.empty_name`, `template.format_spec`, `template.invalid_name`, `template.unknown_conversion` | template syntax | `TemplateSyntaxError` |
| `template.missing_variable` | strict mode | `MissingVariableError` |
| `template.extra_variable` | strict mode | `ExtraVariableError` |
| `schema.validation_failed` | instance invalid | `SchemaValidationError` |
| `schema.invalid` | schema invalid / unsupported | `SchemaError` |
| `snapshot.mismatch`, `snapshot.missing` | snapshot tests | `SnapshotMismatchError` |
| `openai.no_content`, `openai.unknown_tool` | OpenAI integration | `MalformedOutputError` |

Invalid arguments (`select`, `kind`, `escape`, `form`, `policy`, `length`,
`RetryPolicy` fields, custom labels and patterns) raise `ValueError`, and
unsupported value types raise `TypeError`.
