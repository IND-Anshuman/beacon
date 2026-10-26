"""A canonical YAML emitter for JSON-like data.

beacon writes snapshot files with this emitter and compares snapshots by
byte equality of its output, so no YAML *parser* is involved at test time and
the output cannot drift with a third-party library version. The output is
valid YAML 1.1 and 1.2 (it round-trips through PyYAML; see the tests).

Rules (all deterministic):

* Mappings are block style, two-space indent, keys in insertion order.
* Sequences are block style (``- item``), nested one level under their key.
* ``None`` → ``null``; booleans → ``true``/``false``; floats always contain a
  ``.`` (``1.0e+20``) and use ``.nan``/``.inf``/``-.inf``.
* Strings are plain only if they match ``[A-Za-z_][A-Za-z0-9_ ./-]*`` and are
  not a YAML keyword; multi-line strings use literal blocks (``|``, ``|-``,
  ``|+``) when that is lossless; everything else is double-quoted with
  escapes for every non-printable character.
"""

from __future__ import annotations

import math
import re
from typing import Any

__all__ = ["dump"]

_PLAIN = re.compile(r"[A-Za-z_][A-Za-z0-9_ ./\-]*")
_RESERVED = {"y", "n", "yes", "no", "on", "off", "true", "false", "null", "nan", "inf"}
_ESCAPES = {
    "\\": "\\\\",
    '"': '\\"',
    "\n": "\\n",
    "\t": "\\t",
    "\r": "\\r",
    "\0": "\\0",
}


def _quote(s: str) -> str:
    out = ['"']
    for ch in s:
        if ch in _ESCAPES:
            out.append(_ESCAPES[ch])
        elif ch == " " or ch.isprintable():
            out.append(ch)
        else:
            cp = ord(ch)
            if cp <= 0xFF:
                out.append(f"\\x{cp:02x}")
            elif cp <= 0xFFFF:
                out.append(f"\\u{cp:04x}")
            else:
                out.append(f"\\U{cp:08x}")
    out.append('"')
    return "".join(out)


def _plain_ok(s: str) -> bool:
    return bool(_PLAIN.fullmatch(s)) and not s.endswith(" ") and s.lower() not in _RESERVED


def _scalar_string(s: str) -> str:
    return s if _plain_ok(s) else _quote(s)


def _literal_ok(s: str) -> bool:
    if "\n" not in s or s.startswith(("\n", " ", "\t")) or not s.strip():
        return False
    for line in s.split("\n"):
        if line != line.rstrip(" \t"):
            return False
        if any(not (ch == "\t" or ch == " " or ch.isprintable()) for ch in line):
            return False
    return True


def _literal(s: str, indent: int) -> list[str]:
    if s.endswith("\n\n"):
        header, body = "|+", s[:-1]
    elif s.endswith("\n"):
        header, body = "|", s[:-1]
    else:
        header, body = "|-", s
    pad = " " * indent
    return [header] + [pad + line if line else "" for line in body.split("\n")]


def _float(f: float) -> str:
    if math.isnan(f):
        return ".nan"
    if math.isinf(f):
        return ".inf" if f > 0 else "-.inf"
    r = repr(f)
    if "e" in r and "." not in r:
        mantissa, exp = r.split("e")
        r = f"{mantissa}.0e{exp}"
    return r


def _inline(value: Any) -> str | None:
    """Single-line form of a scalar or empty container, else ``None``."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(int(value))
    if isinstance(value, float):
        return _float(value)
    if isinstance(value, str):
        return None if _literal_ok(value) else _scalar_string(value)
    if isinstance(value, (list, tuple)) and not value:
        return "[]"
    if isinstance(value, dict) and not value:
        return "{}"
    return None


def _key(k: Any) -> str:
    if not isinstance(k, str):
        raise TypeError(f"mapping keys must be str, got {type(k).__name__}")
    return _scalar_string(k)


def _lines(value: Any, indent: int) -> list[str]:
    """Lines for a block value (dict, list, or literal string) at ``indent``."""
    pad = " " * indent
    if isinstance(value, str):
        raise AssertionError("strings are emitted by their parent")
    if isinstance(value, dict):
        out: list[str] = []
        for k, v in value.items():
            key = _key(k)
            inline = _inline(v)
            if inline is not None:
                out.append(f"{pad}{key}: {inline}")
            elif isinstance(v, str):
                lit = _literal(v, indent + 2)
                out.append(f"{pad}{key}: {lit[0]}")
                out.extend(lit[1:])
            else:
                out.append(f"{pad}{key}:")
                out.extend(_lines(v, indent + 2))
        return out
    if isinstance(value, (list, tuple)):
        out = []
        for item in value:
            inline = _inline(item)
            if inline is not None:
                out.append(f"{pad}- {inline}")
            elif isinstance(item, str):
                lit = _literal(item, indent + 2)
                out.append(f"{pad}- {lit[0]}")
                out.extend(lit[1:])
            else:
                child = _lines(item, indent + 2)
                child[0] = f"{pad}- {child[0][indent + 2:]}"
                out.extend(child)
        return out
    raise TypeError(f"cannot emit type {type(value).__name__} as YAML")


def dump(value: Any) -> str:
    """Canonical YAML for ``value``; always ends with a newline."""
    inline = _inline(value)
    if inline is not None:
        return inline + "\n"
    if isinstance(value, str):
        return "\n".join(_literal(value, 2)) + "\n"
    return "\n".join(_lines(value, 0)) + "\n"
