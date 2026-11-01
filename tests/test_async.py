from __future__ import annotations

import asyncio
import inspect
from typing import Any, Callable

import pytest

import beacon
from beacon import Pipeline, aio


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_every_async_block_matches_its_sync_result() -> None:
    schema = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}
    cases: list[tuple[Callable[..., Any], Callable[..., Any], tuple, dict]] = [
        (aio.template, beacon.template, ("Hi {name}",), {"name": "Al"}),
        (aio.template_variables, beacon.template_variables, ("{a} {b}",), {}),
        (aio.extract_json, beacon.extract_json, ('x {"a": 1}',), {}),
        (aio.parse_tool_calls, beacon.parse_tool_calls, ('search(q="x")',), {}),
        (aio.schema_errors, beacon.schema_errors, ({"n": "x"}, schema), {}),
        (aio.schema_instructions, beacon.schema_instructions, (schema,), {}),
        (aio.normalize, beacon.normalize, ("  A  B ",), {}),
        (aio.hash_content, beacon.hash_content, ({"a": 1},), {}),
        (aio.cache_key, beacon.cache_key, ("sys", ["t"]), {}),
        (aio.redact, beacon.redact, ("mail me a@b.com",), {}),
        (aio.detect_pii, beacon.detect_pii, ("a@b.com",), {}),
    ]
    for afn, sfn, args, kwargs in cases:
        assert inspect.iscoroutinefunction(afn), afn
        assert run(afn(*args, **kwargs)) == sfn(*args, **kwargs), afn.__name__


def test_async_detailed_and_repair_and_model() -> None:
    pydantic = pytest.importorskip("pydantic")

    class Intent(pydantic.BaseModel):
        n: int

    assert run(aio.extract_json_detailed('{"a": 1}')).value == {"a": 1}
    assert run(aio.repair_json('{"a": 1,}')).value == {"a": 1}
    assert run(aio.schema_from_model(Intent)) == beacon.schema_from_model(Intent)
    assert run(aio.validate_model({"n": 1}, Intent)).n == 1
    assert run(aio.parse_tool_call('f(x=1)')) == {"name": "f", "arguments": {"x": 1}}


def test_async_errors_propagate() -> None:
    with pytest.raises(beacon.MalformedOutputError):
        run(aio.extract_json("{bad"))
    with pytest.raises(beacon.SchemaValidationError):
        run(aio.validate_schema({"n": "x"}, {"type": "object", "properties": {"n": {"type": "integer"}}}))
    with pytest.raises(beacon.NoJSONFoundError):
        run(aio.repair_json("just prose"))


def test_async_surface_covers_every_sync_block() -> None:
    # Every data-processing block in beacon has an aio counterpart (retry and
    # the result/error types are not blocks).
    sync_blocks = {
        name
        for name in beacon.__all__
        if callable(getattr(beacon, name)) and name[0].islower() and name not in {"retry"}
    }
    assert sync_blocks <= set(aio.__all__), sync_blocks - set(aio.__all__)


def test_pipeline_arun_awaits_async_blocks() -> None:
    async def fetch(x: int) -> int:
        await asyncio.sleep(0)
        return x + 1

    def double(x: int) -> int:
        return x * 2

    assert run(Pipeline([fetch, double]).arun(10)) == 22
    # A fully-synchronous pipeline still works through arun.
    assert run(Pipeline([double, double]).arun(3)) == 12


def test_pipeline_arun_traced_records_steps() -> None:
    async def fetch(x: int) -> dict:
        return {"v": x}

    result = run(Pipeline([fetch, lambda d: d["v"]]).arun_traced(5))
    assert result.output == 5
    assert [s.index for s in result.steps] == [0, 1]
    assert result.steps[0].output_hash == result.steps[1].input_hash
