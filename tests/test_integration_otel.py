from __future__ import annotations

import asyncio
from contextlib import contextmanager
from typing import Any, Iterator

import pytest

from beacon import Pipeline
from beacon.integrations.otel import atraced_run, traced_run


class FakeSpan:
    def __init__(self, name: str) -> None:
        self.name = name
        self.attributes: dict[str, Any] = {}

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value


class FakeTracer:
    def __init__(self) -> None:
        self.spans: list[FakeSpan] = []

    @contextmanager
    def start_as_current_span(self, name: str) -> Iterator[FakeSpan]:
        span = FakeSpan(name)
        self.spans.append(span)
        yield span


def strip_it(s: str) -> str:
    return s.strip()


def shout(s: str) -> str:
    return s.upper()


async def afetch(x: int) -> int:
    await asyncio.sleep(0)
    return x + 1


def test_traced_run_emits_parent_and_child_spans() -> None:
    tracer = FakeTracer()
    pipeline = Pipeline([strip_it, shout])
    result = traced_run(pipeline, "  hi  ", tracer=tracer)

    assert result.output == "HI"
    # parent + one span per block
    assert [s.name for s in tracer.spans] == ["Pipeline", "strip_it", "shout"]
    parent, first, second = tracer.spans
    assert parent.attributes["beacon.pipeline.blocks"] == 2
    assert first.attributes["beacon.step.index"] == 0
    assert first.attributes["beacon.step.block"] == "strip_it"
    # output of step 0 is the input of step 1 (hash chaining)
    assert first.attributes["beacon.output_hash"] == second.attributes["beacon.input_hash"]


def test_traced_run_matches_run_traced() -> None:
    pipeline = Pipeline([strip_it, shout])
    traced = traced_run(pipeline, "  hi  ", tracer=FakeTracer())
    plain = pipeline.run_traced("  hi  ")
    assert traced.output == plain.output
    assert traced.trace() == plain.trace()


def test_custom_span_name() -> None:
    tracer = FakeTracer()
    traced_run(Pipeline([shout]), "x", tracer=tracer, name="classify-intent")
    assert tracer.spans[0].name == "classify-intent"


def test_block_exception_propagates() -> None:
    def boom(_: Any) -> Any:
        raise ValueError("nope")

    with pytest.raises(ValueError, match="nope"):
        traced_run(Pipeline([boom]), "x", tracer=FakeTracer())


def test_atraced_run_awaits_async_block() -> None:
    tracer = FakeTracer()
    result = asyncio.run(atraced_run(Pipeline([afetch, lambda n: n * 2]), 10, tracer=tracer))
    assert result.output == 22
    assert tracer.spans[1].attributes["beacon.step.block"] == "afetch"


def test_missing_opentelemetry_is_a_clear_error() -> None:
    import importlib.util

    if importlib.util.find_spec("opentelemetry") is not None:
        pytest.skip("opentelemetry is installed; the ImportError path cannot be exercised")
    with pytest.raises(ImportError, match=r"llm-beacon\[otel\]"):
        traced_run(Pipeline([shout]), "x")
