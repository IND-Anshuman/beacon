"""Cross-process determinism: every block gives byte-identical results in
fresh interpreters with different hash seeds (so nothing depends on dict/set
iteration order, object addresses, or one-time initialisation)."""

from __future__ import annotations

import os
import subprocess
import sys

SCRIPT = r'''
import json, beacon
from beacon import retry
from beacon.snapshots import to_snapshot_data

def run(fn, *a, **k):
    try:
        return {"ok": to_snapshot_data(fn(*a, **k))}
    except Exception as e:
        return {"error": to_snapshot_data(e)}

out = [
    run(beacon.template, "<u>{a}</u> {b!raw}", a="<x>", b="&"),
    run(beacon.template, "{z} {a} {m}"),
    run(beacon.extract_json_detailed, 'pre {"b": [1, 2.5, {"c": null}], "a": "é"} post [1]'),
    run(beacon.extract_json, '{"a": 1,, }'),
    run(beacon.parse_tool_calls, '<tool_call>{"name": "f", "arguments": {"y": 1, "x": 2}}</tool_call>', include_format=True),
    run(beacon.parse_tool_call, "search(q='x', n=2)"),
    run(beacon.schema_errors, {"b": "x", "a": -1, "z": 1}, {"properties": {"a": {"minimum": 0}, "b": {"type": "integer"}}, "required": ["c", "d"], "additionalProperties": False}),
    run(beacon.normalize, "  Ça​  va\tbien ﬁ ", lowercase=True, strip_accents=True),
    run(beacon.hash_content, {"z": [1, {"y": 2, "x": 3}], "a": None, "m": 1.5}),
    run(beacon.redact, "a@b.co 4111111111111111 555-123-4567 10.0.0.1", policy="strict", replacement="[{label}:{hash}]"),
    run(beacon.detect_pii, "a@b.co sk-proj-abcdefghijklmnopqrstuvwxyz", policy="strict"),
    run(lambda: [retry.classify(s, attempt=2, policy=retry.RetryPolicy(jitter_key="k")) for s in (429, 503, 401)]),
]
print(json.dumps(out, sort_keys=True, ensure_ascii=True))
'''


def _run(seed: str) -> str:
    env = {**os.environ, "PYTHONHASHSEED": seed}
    result = subprocess.run([sys.executable, "-c", SCRIPT], capture_output=True, text=True, env=env, check=True)
    return result.stdout


def test_identical_output_across_processes_and_hash_seeds() -> None:
    outputs = {_run(seed) for seed in ("0", "1", "12345", "random")}
    assert len(outputs) == 1, "block output depends on process state"
