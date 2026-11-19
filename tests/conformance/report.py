"""Produce the determinism report: run the golden corpus through every available
binding, record what matched and the environment, and write a JSON report.

    python tests/conformance/report.py

Writes ``tests/conformance/determinism-report.json`` and prints a short summary.
The report says what was tested (cases, blocks), across which languages and
platform, with the core version — the reproducible attestation behind the
cross-language determinism claim on the docs site.
"""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # make tests/ importable

import conformance_cases as cc  # noqa: E402

import beacon  # noqa: E402
from beacon import _beacon_native as _native  # noqa: E402

_RUNNER = Path(__file__).resolve().parent.parent / "js" / "parity_runner.mjs"
_REPORT_PATH = Path(__file__).resolve().parent / "determinism-report.json"


def _python_results(cases: list[dict]) -> dict[str, str]:
    return {c["id"]: cc.run_case(c) for c in cases}


def _js_results(cases: list[dict]) -> dict[str, str] | None:
    if shutil.which("node") is None or not cc.WASM_PATH.exists():
        return None
    calls = [{"id": c["id"], "fn": c["fn"], "args": c["args"]} for c in cases]
    proc = subprocess.run(
        ["node", str(_RUNNER)], input=json.dumps(calls), capture_output=True, text=True, encoding="utf-8"
    )
    if proc.returncode != 0:
        raise SystemExit(f"JS runner failed:\n{proc.stderr}")
    raw = json.loads(proc.stdout)
    return {cid: v.get("ok", f"<error:{v.get('err')}>") for cid, v in raw.items()}


def _node_version() -> str | None:
    if shutil.which("node") is None:
        return None
    return subprocess.run(["node", "--version"], capture_output=True, text=True).stdout.strip()


def build_report() -> dict:
    corpus = cc.load_corpus()
    cases = corpus["cases"]
    golden = {c["id"]: c["expected"] for c in cases}
    blocks = sorted({c["fn"] for c in cases})

    bindings = []

    py = _python_results(cases)
    py_match = sum(1 for cid in golden if py.get(cid) == golden[cid])
    bindings.append(
        {
            "language": "python",
            "package": "llm-beacon",
            "version": beacon.__version__,
            "matched": py_match,
            "total": len(golden),
            "byte_identical": py_match == len(golden),
        }
    )

    js = _js_results(cases)
    if js is not None:
        js_match = sum(1 for cid in golden if js.get(cid) == golden[cid])
        bindings.append(
            {
                "language": "javascript",
                "package": "llm-beacon (wasm)",
                "version": beacon.__version__,
                "runtime": _node_version(),
                "matched": js_match,
                "total": len(golden),
                "byte_identical": js_match == len(golden),
            }
        )

    return {
        "report": "beacon cross-language determinism",
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "core_version": _native.VERSION,
        "unicode_version": _native.unicode_version(),
        "corpus_format": corpus["format"],
        "cases": len(cases),
        "blocks_covered": blocks,
        "platform": platform.platform(),
        "python": f"{platform.python_version()} ({platform.python_implementation()})",
        "bindings": bindings,
        "all_byte_identical": all(b["byte_identical"] for b in bindings),
    }


def main() -> int:
    report = build_report()
    _REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    langs = ", ".join(f"{b['language']} {b['matched']}/{b['total']}" for b in report["bindings"])
    print(f"determinism report: {report['cases']} cases, {len(report['blocks_covered'])} ops — {langs}")
    print(f"all byte-identical: {report['all_byte_identical']} | core {report['core_version']}")
    print(f"wrote {_REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
