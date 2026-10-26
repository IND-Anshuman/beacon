"""Snapshot-test your own LLM app with recorded responses.

Run it with pytest:

    pytest examples/08_snapshot_testing_your_app.py

The first run writes examples/snapshots/app/*.yaml; later runs compare byte
for byte. Change `route()` below and re-run to see the diff, then accept it
with `python -m beacon.snapshots update examples/08_snapshot_testing_your_app.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from beacon import MalformedOutputError, Pipeline, extract_json, template
from beacon.snapshots import assert_snapshot

SNAPSHOTS = Path(__file__).parent / "snapshots"

INTENT = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": ["cancel", "refund", "question"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["intent", "confidence"],
}

# Responses recorded from real model runs (normally loaded from fixture files).
RECORDED = {
    "cancel": 'Sure!\n```json\n{"intent": "cancel", "confidence": 0.93}\n```',
    "refund_in_prose": 'Per policy [1], this is {"intent": "refund", "confidence": 0.71}.',
    "truncated": '{"intent": "question", "confid',
    "hallucinated_intent": '{"intent": "upgrade", "confidence": 0.5}',
}


# ---------------------------------------------------------------- the "app"


def build_pipeline(llm):
    def classify(message: str) -> dict:
        prompt = template("Classify as JSON: <msg>{m}</msg>", m=message)
        return extract_json(llm(prompt), schema=INTENT)

    def route(intent: dict) -> dict:
        team = {"cancel": "retention", "refund": "billing"}.get(intent["intent"], "support")
        return {"team": team, "priority": "high" if intent["confidence"] > 0.9 else "normal"}

    return Pipeline([classify, route])


# ---------------------------------------------------------------- the tests


@pytest.mark.parametrize("case", sorted(RECORDED))
def test_recorded_responses(case: str) -> None:
    raw = RECORDED[case]
    pipeline = build_pipeline(llm=lambda prompt: raw)
    try:
        result = pipeline.run_traced(f"message for {case}")
        outcome = {"output": result.output, "trace": result.trace()}
    except (MalformedOutputError, ValueError) as err:
        outcome = {"error": err}  # errors are snapshotted too: type, code, message, position
    assert_snapshot(f"app/{case}", outcome, input=raw, directory=SNAPSHOTS)


def test_prompt_is_stable() -> None:
    assert_snapshot("app/prompt", template("Classify as JSON: <msg>{m}</msg>", m="<b>hi</b>"), directory=SNAPSHOTS)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
