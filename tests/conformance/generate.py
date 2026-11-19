"""Regenerate the golden conformance corpus from the Python package.

    python tests/conformance/generate.py

Writes ``tests/conformance/corpus.json`` — the language-neutral golden that both
the Python and JavaScript runners assert byte-identical against. Run it after a
*deliberate* output change (and record that change in the CHANGELOG); the
``test_conformance`` suite fails until the golden is regenerated, exactly like a
snapshot update.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # make tests/ importable

import conformance_cases as cc  # noqa: E402


def main() -> int:
    corpus = cc.build_corpus()
    cc.CORPUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    cc.CORPUS_PATH.write_text(json.dumps(corpus, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(corpus['cases'])} cases to {cc.CORPUS_PATH} (core {corpus['core_version']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
