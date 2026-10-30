"""The ``beacon`` command line: deterministic blocks in shell pipelines.

Each subcommand reads from a file argument or, when it is omitted or ``-``,
from standard input. Output goes to stdout; a beacon error is printed to stderr
and exits with status 1. Usage errors exit with status 2 (argparse's default).

    beacon extract 'prose {"a": 1} prose'   # -> {"a": 1}
    beacon validate schema.json out.json     # exit 1, prints violations on failure
    beacon redact input.txt                  # redacted text to stdout
    beacon parse-tool response.json          # normalized tool calls as JSON
    beacon hash prompt.txt                   # BLAKE3 digest
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional, Sequence

from . import __version__
from ._api import extract_json, hash_content, parse_tool_calls, redact, repair_json, schema_errors
from .errors import BeaconError

EXIT_OK = 0
EXIT_ERROR = 1


def _read_text(source: Optional[str], *, inline: bool = False) -> str:
    """Text from ``source``: an inline string, a file, or stdin (``-``/omitted)."""
    if inline and source is not None:
        return source
    if source is None or source == "-":
        return sys.stdin.read()
    return Path(source).read_text(encoding="utf-8")


def _read_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _dump(value: Any, indent: Optional[int]) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=indent))


def _cmd_extract(args: argparse.Namespace) -> int:
    text = _read_text(args.input, inline=args.text)
    value = extract_json(text, select=args.select, kind=args.kind)
    _dump(value, args.indent)
    return EXIT_OK


def _cmd_repair(args: argparse.Namespace) -> int:
    text = _read_text(args.input, inline=args.text)
    result = repair_json(text)
    _dump(result.value, args.indent)
    for r in result.repairs:
        print(f"repair: {r.kind} at {r.at}: {r.detail}", file=sys.stderr)
    if args.strict and result.incomplete:
        print("beacon: repaired JSON is incomplete (truncated input)", file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK


def _cmd_validate(args: argparse.Namespace) -> int:
    schema = _read_json(args.schema)
    instance = _read_json(args.instance)
    errors = schema_errors(instance, schema)
    if not errors:
        return EXIT_OK
    for e in errors:
        where = e["path"] or "(root)"
        print(f"{where}: {e['keyword']}: {e['message']}", file=sys.stderr)
    return EXIT_ERROR


def _cmd_redact(args: argparse.Namespace) -> int:
    text = _read_text(args.input, inline=args.text)
    sys.stdout.write(redact(text, policy=args.policy))
    return EXIT_OK


def _cmd_parse_tool(args: argparse.Namespace) -> int:
    text = _read_text(args.input, inline=args.text)
    _dump(parse_tool_calls(text, include_format=args.format), args.indent)
    return EXIT_OK


def _cmd_hash(args: argparse.Namespace) -> int:
    text = _read_text(args.input, inline=args.text)
    print(hash_content(text, length=args.length))
    return EXIT_OK


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="beacon", description="Deterministic building blocks for AI pipelines.")
    parser.add_argument("--version", action="version", version=f"beacon {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    def add_input(p: argparse.ArgumentParser) -> None:
        p.add_argument("input", nargs="?", help="input file, or '-'/omitted for stdin")
        p.add_argument("-t", "--text", action="store_true", help="treat INPUT as the literal text, not a path")

    extract = sub.add_parser("extract", help="extract a JSON value from LLM output")
    add_input(extract)
    extract.add_argument("--select", choices=["first", "last", "largest", "only"], default="first")
    extract.add_argument("--kind", choices=["auto", "any", "object", "array"], default="auto")
    extract.add_argument("--indent", type=int, default=None, help="pretty-print with this indent")
    extract.set_defaults(func=_cmd_extract)

    repair = sub.add_parser("repair", help="repair malformed JSON, reporting every change on stderr")
    add_input(repair)
    repair.add_argument("--indent", type=int, default=None, help="pretty-print with this indent")
    repair.add_argument("--strict", action="store_true", help="exit 1 if the result is incomplete (truncated)")
    repair.set_defaults(func=_cmd_repair)

    validate = sub.add_parser("validate", help="validate a JSON file against a JSON Schema file")
    validate.add_argument("schema", help="JSON Schema file")
    validate.add_argument("instance", help="JSON file to validate")
    validate.set_defaults(func=_cmd_validate)

    red = sub.add_parser("redact", help="redact PII and secrets")
    add_input(red)
    red.add_argument(
        "--policy", choices=["default", "strict", "secrets", "pii", "none"], default="default"
    )
    red.set_defaults(func=_cmd_redact)

    parse_tool = sub.add_parser("parse-tool", help="parse tool calls from LLM output")
    add_input(parse_tool)
    parse_tool.add_argument("--format", action="store_true", help="include the detected format of each call")
    parse_tool.add_argument("--indent", type=int, default=None)
    parse_tool.set_defaults(func=_cmd_parse_tool)

    hash_ = sub.add_parser("hash", help="BLAKE3 digest of the input text")
    add_input(hash_)
    hash_.add_argument("--length", type=int, default=16, help="digest length in bytes (1-64)")
    hash_.set_defaults(func=_cmd_hash)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point for the ``beacon`` command. Returns the process exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except BeaconError as exc:
        print(f"beacon: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except FileNotFoundError as exc:
        print(f"beacon: {exc.strerror}: {exc.filename}", file=sys.stderr)
        return EXIT_ERROR
    except (ValueError, TypeError) as exc:
        print(f"beacon: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
