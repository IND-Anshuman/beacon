# Determinism guarantees

This document is the contract. If beacon behaves differently from what is
written here, that is a bug.

## 1. Pure functions

Every block exported from `beacon` (`template`, `extract_json`,
`extract_json_detailed`, `parse_tool_call`, `parse_tool_calls`,
`validate_schema`, `schema_errors`, `normalize`, `hash_content`, `redact`,
`detect_pii`, `retry.classify`, `retry.backoff_delay`) is a pure function:

* Same arguments → same return value (or the same exception, with the same
  message and attributes).
* No hidden state: no caches, no counters, no global configuration.
* No I/O: blocks never read files, the network, the clock, environment
  variables, or the system locale.
* No randomness. Retry jitter is derived from a hash of an explicit
  `jitter_key` and the attempt number.

The first call of a block produces the same output as its thousandth call.
Internally, built-in regular expressions are compiled once on first use; that
compilation cannot influence results.

## 2. Stable across runs and machines

For a given beacon version, the output of every block is byte-identical across
runs, processes, Python versions (3.10–3.14), operating systems (Linux, macOS,
Windows), CPU architectures, and locales.

How that is achieved:

* All logic runs in Rust. Python is only used to convert arguments.
* Text positions reported to Python (`position`, `start`, `end`) are counted in
  Unicode code points, matching Python `str` indexing — never bytes.
* JSON numbers are parsed with correctly rounded IEEE-754 conversion. Integers
  of any size become exact Python `int`s; they are never routed through floats.
* `hash_content` hashes a type-tagged canonical encoding (see below), never
  `repr()` or `json.dumps()` output.
* Retry delays are computed in integer milliseconds.
* Unicode tables (normalization, case mapping, whitespace) come from pinned
  crate versions. The Unicode version only changes in a minor release and is
  recorded in `CHANGELOG.md`.

## 3. Stable across versions

* **Patch releases** (0.1.x → 0.1.y) never change the output of any block for
  any input, including exception types, codes and messages.
* **Minor releases** (0.1 → 0.2) may add parameters, error codes, supported
  formats, or detectors, but a call that succeeded before returns the same
  value, and a snapshot written under 0.X matches under 0.(X+1). Any exception
  — e.g. a newly recognised tool-call format turning an error into a success —
  is listed in `CHANGELOG.md` under "Behaviour changes".
* **Major releases** may change anything, with a migration note.

beacon's own test suite enforces this with the snapshot files in `snapshots/`:
a change to any of them is a visible diff in review.

## 4. Stable error messages

Exception classes, `code` attributes and message text are part of the
contract (rules of section 3 apply). Messages never contain timestamps, memory
addresses, hash-randomised orderings, or absolute paths. When several problems
are reported at once (missing template variables, schema violations) they are
reported in a documented, fixed order.

## 5. Explicit configuration

Every option that affects output is a named parameter with a documented
default. There are no global flags and no environment variables that change
block behaviour.

The snapshot *test harness* reads `BEACON_SNAPSHOT_MODE` and `CI` to decide
whether a missing snapshot is written or fails the test. That changes what the
harness does with files, never what a block returns.

## 6. Fail loudly

Blocks never silently repair input:

* `extract_json` accepts strict RFC 8259 JSON only — no trailing commas,
  comments, single quotes, `NaN`, or unescaped control characters. Malformed
  JSON raises `MalformedOutputError` with a position.
* `validate_schema` never coerces types: `"42"` is not a number.
* `template` raises on missing variables (and, in strict mode, unused ones).
* `parse_tool_call` raises when it finds no call, or more than one.
* `validate_schema` raises `SchemaError` for keywords it does not implement,
  rather than ignoring them.

## Canonical encoding used by `hash_content`

`hash_content(value)` is `blake3(encode(value))` in lowercase hex, truncated to
`length` characters (default 16). `encode` is:

| Python value | Encoding |
| --- | --- |
| `None` | `n` |
| `True` / `False` | `t` / `f` |
| `int` | `i` + decimal digits (with `-` if negative) + `;` |
| `float` | `d` + 8 bytes, IEEE-754 big-endian; all NaNs are encoded as the canonical quiet NaN `0x7ff8000000000000` |
| `str` | `s` + byte length as 8-byte big-endian + UTF-8 bytes |
| `bytes` | `b` + byte length as 8-byte big-endian + raw bytes |
| `list` / `tuple` | `l` + item count as 8-byte big-endian + encoded items in order |
| `dict` (str keys) | `m` + entry count as 8-byte big-endian + (encoded key, encoded value) pairs sorted by the key's UTF-8 bytes |

Consequences: `{"a": 1, "b": 2}` and `{"b": 2, "a": 1}` hash equal; `[1, 2]`
and `[2, 1]` do not; `1`, `1.0`, `True` and `"1"` all hash differently;
`0.0` and `-0.0` hash differently; lists and tuples with the same items hash
equal. Other types raise `TypeError`. The encoding is versioned: changing it is
a major-version change.

## What is *not* guaranteed

* The LLM itself. beacon makes everything around the model call deterministic
  so the model is the only moving part — and so you can snapshot-test the rest.
* Pipelines built from user code (`Pipeline`, `Block`) are as deterministic as
  the code inside them.
* `retry.call` sleeps in real time; the *decisions* and *delays* are
  deterministic, the wall-clock is not.
