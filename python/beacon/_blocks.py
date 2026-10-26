"""Composing blocks into pipelines.

A :class:`Block` is a unit of pipeline logic with a ``run`` method. A
:class:`Pipeline` runs blocks in order, feeding each block's output to the
next, and can record a trace of content hashes for every step — a compact,
deterministic fingerprint you can snapshot-test.

>>> from beacon import Pipeline, Block
>>> class Upper(Block):
...     def run(self, text: str) -> str:
...         return text.upper()
>>> Pipeline([Upper(), str.strip]).run("  hi  ")
'HI'
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence, Union

from ._api import hash_content

__all__ = ["Block", "Pipeline", "PipelineResult", "StepRecord"]


class Block:
    """Base class for pipeline steps. Override :meth:`run`.

    Blocks should be deterministic: given the same input they return the same
    output. LLM calls are the exception — keep them in their own block so the
    rest of the pipeline can be tested with canned responses.
    """

    #: Name used in traces; defaults to the class name.
    name: str = ""

    def run(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover - abstract
        raise NotImplementedError(f"{type(self).__name__}.run() is not implemented")

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self.run(*args, **kwargs)

    @property
    def label(self) -> str:
        return self.name or type(self).__name__


class FunctionBlock(Block):
    """Wraps a plain callable as a block."""

    def __init__(self, fn: Callable[..., Any], name: str = "") -> None:
        self.fn = fn
        self.name = name or getattr(fn, "__qualname__", None) or getattr(fn, "__name__", "") or type(fn).__name__

    def run(self, *args: Any, **kwargs: Any) -> Any:
        return self.fn(*args, **kwargs)


@dataclass(frozen=True)
class StepRecord:
    """One step of a traced run. Hashes are :func:`hash_content` digests, or
    ``None`` when the value is not hashable JSON-like data."""

    index: int
    block: str
    input_hash: Union[str, None]
    output_hash: Union[str, None]


@dataclass(frozen=True)
class PipelineResult:
    output: Any
    steps: Sequence[StepRecord] = field(default_factory=tuple)

    def trace(self) -> list[dict[str, Any]]:
        """The steps as plain dicts (handy for :func:`assert_snapshot`)."""
        return [
            {"index": s.index, "block": s.block, "input_hash": s.input_hash, "output_hash": s.output_hash}
            for s in self.steps
        ]


def _safe_hash(value: Any) -> Union[str, None]:
    try:
        return hash_content(value)
    except (TypeError, ValueError):
        return None


class Pipeline(Block):
    """Runs blocks in sequence.

    The first block receives the arguments given to :meth:`run`; every later
    block receives the previous block's output as its single positional
    argument. Plain callables are accepted and wrapped in a block.
    """

    def __init__(self, blocks: Iterable[Union[Block, Callable[..., Any]]], name: str = "") -> None:
        self.blocks: list[Block] = [b if isinstance(b, Block) else FunctionBlock(b) for b in blocks]
        if not self.blocks:
            raise ValueError("a Pipeline needs at least one block")
        for b in self.blocks:
            if not callable(getattr(b, "run", None)):
                raise TypeError(f"{b!r} is not a Block or callable")
        self.name = name

    def run(self, *args: Any, **kwargs: Any) -> Any:
        value = self.blocks[0].run(*args, **kwargs)
        for block in self.blocks[1:]:
            value = block.run(value)
        return value

    def run_traced(self, *args: Any, **kwargs: Any) -> PipelineResult:
        """Run and record the content hash of every step's input and output."""
        first_input: Any = {"args": list(args), "kwargs": kwargs} if kwargs or len(args) != 1 else args[0]
        steps = []
        value = self.blocks[0].run(*args, **kwargs)
        steps.append(StepRecord(0, self.blocks[0].label, _safe_hash(first_input), _safe_hash(value)))
        for i, block in enumerate(self.blocks[1:], start=1):
            in_hash = steps[-1].output_hash
            value = block.run(value)
            steps.append(StepRecord(i, block.label, in_hash, _safe_hash(value)))
        return PipelineResult(value, tuple(steps))

    def __repr__(self) -> str:
        return f"Pipeline([{', '.join(b.label for b in self.blocks)}])"
