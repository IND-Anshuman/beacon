"""OpenTelemetry integration: trace a pipeline run as a span tree.

``Pipeline.run_traced`` already produces a deterministic :class:`StepRecord`
per step (block label, input and output content hashes). This emits that as
OpenTelemetry spans: one parent span for the run and one child span per block,
carrying the step data as ``beacon.*`` attributes. A block that itself calls a
model can create its own ``gen_ai.*`` span inside its step span, so beacon's
processing steps and your model calls appear in one trace.

>>> from beacon import Pipeline
>>> from beacon.integrations.otel import traced_run
>>> result = traced_run(Pipeline([str.strip, str.upper]), "  hi  ")  # doctest: +SKIP
>>> result.output
'HI'

``opentelemetry`` is imported lazily and only when you do not pass your own
``tracer`` (``pip install "llm-beacon[otel]"``). The returned
:class:`PipelineResult` is identical to ``run_traced``'s; span timing is
OpenTelemetry's and is the only non-deterministic part.
"""

from __future__ import annotations

import inspect
from typing import Any, Optional

from .._api import hash_content
from .._blocks import Pipeline, PipelineResult, StepRecord
from ._common import require

__all__ = ["traced_run", "atraced_run"]


def _safe_hash(value: Any) -> Optional[str]:
    try:
        return hash_content(value)
    except (TypeError, ValueError):
        return None


def _get_tracer(tracer: Any) -> Any:
    if tracer is not None:
        return tracer
    trace = require("opentelemetry.trace", "otel", "beacon.integrations.otel")
    return trace.get_tracer("beacon")


def _first_input(args: tuple, kwargs: dict) -> Any:
    return {"args": list(args), "kwargs": kwargs} if kwargs or len(args) != 1 else args[0]


def _step_attrs(span: Any, index: int, label: str, in_hash: Optional[str], out_hash: Optional[str]) -> None:
    span.set_attribute("beacon.step.index", index)
    span.set_attribute("beacon.step.block", label)
    if in_hash is not None:
        span.set_attribute("beacon.input_hash", in_hash)
    if out_hash is not None:
        span.set_attribute("beacon.output_hash", out_hash)


def traced_run(pipeline: Pipeline, *args: Any, tracer: Any = None, name: Optional[str] = None, **kwargs: Any) -> PipelineResult:
    """Run ``pipeline`` under OpenTelemetry spans and return its
    :class:`PipelineResult`.

    A parent span (named ``name`` or the pipeline's label) wraps a child span
    per block. Each child carries ``beacon.step.index``, ``beacon.step.block``,
    and the ``beacon.input_hash`` / ``beacon.output_hash`` content digests. Pass
    ``tracer`` to use your own OpenTelemetry tracer instead of the default.
    """
    tracer = _get_tracer(tracer)
    blocks = pipeline.blocks
    steps: list[StepRecord] = []
    value: Any = None
    with tracer.start_as_current_span(name or pipeline.label or "beacon.pipeline") as parent:
        parent.set_attribute("beacon.pipeline.blocks", len(blocks))
        in_hash = _safe_hash(_first_input(args, kwargs))
        for i, block in enumerate(blocks):
            with tracer.start_as_current_span(block.label) as span:
                value = block.run(*args, **kwargs) if i == 0 else block.run(value)
                out_hash = _safe_hash(value)
                _step_attrs(span, i, block.label, in_hash, out_hash)
                steps.append(StepRecord(i, block.label, in_hash, out_hash))
                in_hash = out_hash
    return PipelineResult(value, tuple(steps))


async def atraced_run(
    pipeline: Pipeline, *args: Any, tracer: Any = None, name: Optional[str] = None, **kwargs: Any
) -> PipelineResult:
    """Async :func:`traced_run`: a block whose output is awaitable is awaited
    inside its span, so a model-calling coroutine block is timed correctly."""
    tracer = _get_tracer(tracer)
    blocks = pipeline.blocks
    steps: list[StepRecord] = []
    value: Any = None
    with tracer.start_as_current_span(name or pipeline.label or "beacon.pipeline") as parent:
        parent.set_attribute("beacon.pipeline.blocks", len(blocks))
        in_hash = _safe_hash(_first_input(args, kwargs))
        for i, block in enumerate(blocks):
            with tracer.start_as_current_span(block.label) as span:
                value = block.run(*args, **kwargs) if i == 0 else block.run(value)
                if inspect.isawaitable(value):
                    value = await value
                out_hash = _safe_hash(value)
                _step_attrs(span, i, block.label, in_hash, out_hash)
                steps.append(StepRecord(i, block.label, in_hash, out_hash))
                in_hash = out_hash
    return PipelineResult(value, tuple(steps))
