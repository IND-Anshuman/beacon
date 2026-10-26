from __future__ import annotations

from typing import Any

import pytest

from beacon import Block, NoJSONFoundError, Pipeline, extract_json, hash_content, template
from beacon.snapshots import assert_snapshot

SCHEMA = {
    "type": "object",
    "properties": {"intent": {"type": "string"}, "confidence": {"type": "number"}},
    "required": ["intent", "confidence"],
}


class FakeLLM:
    """Returns canned responses keyed by prompt hash: deterministic by design."""

    def __init__(self, responses: dict[str, str]) -> None:
        self.responses = responses
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.responses.get(hash_content(prompt), '{"intent": "unknown", "confidence": 0}')


class ExtractUserIntent(Block):
    def __init__(self, llm: FakeLLM) -> None:
        self.llm = llm

    def run(self, user_message: str) -> dict:
        prompt = template("Extract user intent from: <msg>{message}</msg>", message=user_message)
        return extract_json(self.llm(prompt), schema=SCHEMA)


class Route(Block):
    name = "route"

    def run(self, intent: dict) -> str:
        return {"cancel": "retention_team", "refund": "billing"}.get(intent["intent"], "support")


def format_output(team: str) -> dict:
    return {"route_to": team}


def make_llm() -> FakeLLM:
    prompt = template("Extract user intent from: <msg>{message}</msg>", message="I want to cancel")
    return FakeLLM({hash_content(prompt): 'Sure!\n```json\n{"intent": "cancel", "confidence": 0.93}\n```'})


def test_pipeline_runs_blocks_in_order() -> None:
    pipeline = Pipeline([ExtractUserIntent(make_llm()), Route(), format_output])
    assert pipeline.run("I want to cancel") == {"route_to": "retention_team"}
    assert pipeline.run(user_message="something else") == {"route_to": "support"}


def test_trace_is_deterministic_and_snapshottable() -> None:
    pipeline = Pipeline([ExtractUserIntent(make_llm()), Route(), format_output])
    first = pipeline.run_traced("I want to cancel")
    second = pipeline.run_traced("I want to cancel")
    assert first == second
    assert [s.block for s in first.steps] == ["ExtractUserIntent", "route", "format_output"]
    assert first.steps[1].input_hash == first.steps[0].output_hash
    assert_snapshot("pipeline/cancel_trace", {"output": first.output, "trace": first.trace()})


def test_unhashable_values_trace_as_none() -> None:
    result = Pipeline([lambda x: {1, 2}, len]).run_traced("x")
    assert result.steps[0].output_hash is None
    assert result.output == 2


def test_nested_pipelines() -> None:
    inner = Pipeline([str.strip, str.upper], name="clean")
    outer = Pipeline([inner, lambda s: s + "!"])
    assert outer.run("  hi ") == "HI!"
    assert outer.run_traced("  hi ").steps[0].block == "clean"


def test_validation() -> None:
    with pytest.raises(ValueError):
        Pipeline([])
    with pytest.raises(NotImplementedError):
        Block().run()


def test_blocks_are_callable() -> None:
    assert Route()({"intent": "refund"}) == "billing"
    assert repr(Pipeline([Route(), format_output])) == "Pipeline([route, format_output])"


def test_errors_propagate() -> None:
    class Broken(FakeLLM):
        def __call__(self, prompt: str) -> Any:
            return "no json here"

    with pytest.raises(NoJSONFoundError):
        Pipeline([ExtractUserIntent(Broken({}))]).run("x")
