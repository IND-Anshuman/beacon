"""Cross-language conformance: every binding produces output byte-identical to a
single committed golden corpus.

The corpus (``conformance/corpus.json``) freezes the canonical output string for
each case. The **Python** runner asserts the Python package still matches it (a
regression in the wheels fails here, with no Node needed); the **JavaScript**
runner asserts the wasm package matches the *same* golden. Both matching the one
golden proves Python == JS and pins the exact bytes. Regenerate deliberately with
``python tests/conformance/generate.py``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import conformance_cases as cc
import pytest

_CORPUS = cc.load_corpus()
_CASES = _CORPUS["cases"]
_IDS = [c["id"] for c in _CASES]
_RUNNER = Path(__file__).resolve().parent / "js" / "parity_runner.mjs"


def test_corpus_is_up_to_date() -> None:
    """The committed golden equals what the Python package produces now, so no
    case was added or changed without regenerating it."""
    fresh = cc.build_corpus()
    assert fresh["cases"] == _CASES, "corpus.json is stale — run python tests/conformance/generate.py"
    assert {c["fn"] for c in _CASES} >= set(cc.DISPATCH), "every dispatched op must have at least one case"


@pytest.mark.parametrize("case", _CASES, ids=_IDS)
def test_python_matches_golden(case: dict) -> None:
    assert cc.run_case(case) == case["expected"]


@pytest.fixture(scope="module")
def js_results() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is not available")
    if not cc.WASM_PATH.exists():
        pytest.skip("beacon-js wasm not built; run `node crates/beacon-js/build.mjs`")
    calls = [{"id": c["id"], "fn": c["fn"], "args": c["args"]} for c in _CASES]
    proc = subprocess.run(
        ["node", str(_RUNNER)],
        input=json.dumps(calls),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        pytest.fail(f"parity runner failed:\n{proc.stderr}")
    return json.loads(proc.stdout)


@pytest.mark.parametrize("case", _CASES, ids=_IDS)
def test_javascript_matches_golden(case: dict, js_results: dict) -> None:
    got = js_results[case["id"]]
    assert "ok" in got, f"JS raised for {case['id']}: {got}"
    assert got["ok"] == case["expected"], f"{case['id']}: golden={case['expected']!r} js={got['ok']!r}"
