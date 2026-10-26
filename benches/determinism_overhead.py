"""Per-call overhead of every beacon block on typical LLM-sized inputs.

Target: < 0.5 ms per call (median) for each block. Exits non-zero if a block
misses the target, so it can run in CI.

    python benches/determinism_overhead.py [--budget-ms 0.5] [--number 2000]
"""

from __future__ import annotations

import argparse
import statistics
import sys
import timeit

import beacon
from beacon import retry

RESPONSE = (
    "Sure! Here is the structured result you asked for.\n\n"
    "```json\n"
    '{"intent": "cancel", "confidence": 0.93, "entities": [{"type": "plan", "value": "pro"}, '
    '{"type": "date", "value": "2026-11-01"}], "notes": "User mentioned billing twice."}\n'
    "```\n\nLet me know if you need anything else!"
)
SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": ["cancel", "refund", "question"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"type": {"type": "string"}, "value": {"type": "string"}},
                "required": ["type", "value"],
            },
        },
        "notes": {"type": "string", "maxLength": 500},
    },
    "required": ["intent", "confidence"],
}
DATA = beacon.extract_json(RESPONSE)
PROMPT = (
    "You are a support assistant for {company}.\n"
    "Classify the message below and reply with JSON.\n"
    "<message>{message}</message>\n"
    "<history>{history}</history>"
)
PII_TEXT = (
    "Hi, I'm Jane (jane.doe@example.com, +1 415-555-0132). My card 4242 4242 4242 4242 was charged "
    "twice on order 2026-10-01. Please call back. Thanks! " * 4
)
TOOL_TEXT = '<tool_call>\n{"name": "get_weather", "arguments": {"city": "Paris", "days": 3}}\n</tool_call>'
TIMEOUT = TimeoutError("read timed out")

BLOCKS = {
    "template": lambda: beacon.template(
        PROMPT, company="Acme", message="I want to cancel my subscription <now>", history="none"
    ),
    "extract_json": lambda: beacon.extract_json(RESPONSE),
    "parse_tool_call": lambda: beacon.parse_tool_call(TOOL_TEXT),
    "validate_schema": lambda: beacon.validate_schema(DATA, SCHEMA),
    "normalize": lambda: beacon.normalize(PII_TEXT),
    "hash_content": lambda: beacon.hash_content(DATA),
    "redact": lambda: beacon.redact(PII_TEXT),
    "retry.classify": lambda: retry.classify(TIMEOUT, attempt=2),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--budget-ms", type=float, default=0.5)
    parser.add_argument("--number", type=int, default=2000)
    parser.add_argument("--repeat", type=int, default=5)
    args = parser.parse_args()

    print(f"beacon {beacon.__version__} | Python {sys.version.split()[0]} | budget {args.budget_ms} ms/call\n")
    print(f"{'block':<18}{'median us':>12}{'best us':>12}  status")
    failed = []
    for name, fn in BLOCKS.items():
        first = fn()
        assert all(fn() == first for _ in range(50)), f"{name} is not deterministic"
        runs = timeit.repeat(fn, number=args.number, repeat=args.repeat)
        per_call = [r / args.number * 1e6 for r in runs]
        median, best = statistics.median(per_call), min(per_call)
        ok = median / 1000 < args.budget_ms
        if not ok:
            failed.append(name)
        print(f"{name:<18}{median:>12.1f}{best:>12.1f}  {'ok' if ok else 'OVER BUDGET'}")
    if failed:
        print(f"\nover budget: {', '.join(failed)}")
        return 1
    print("\nall blocks within budget")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
