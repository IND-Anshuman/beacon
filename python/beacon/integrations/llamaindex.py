"""LlamaIndex integration: an output parser backed by beacon.

>>> from llama_index.core.output_parsers import PydanticOutputParser  # doctest: +SKIP
>>> from beacon.integrations.llamaindex import BeaconOutputParser    # doctest: +SKIP
>>> parser = BeaconOutputParser(PydanticOutputParser(QueryResponse)) # doctest: +SKIP
>>> query_engine = index.as_query_engine(output_parser=parser)       # doctest: +SKIP

The parser sits between LlamaIndex's response synthesizer and your code:
``format()`` delegates to the wrapped parser (so its format instructions are
kept), and ``parse()`` uses :func:`beacon.extract_json` plus schema
validation instead of LlamaIndex's lenient JSON scraping.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from ._common import is_model_class, optional, parse_structured, schema_for

_types = optional("llama_index.core.types")
_Base: Any = _types.BaseOutputParser if _types is not None else object

__all__ = ["BeaconOutputParser"]


class BeaconOutputParser(_Base):  # type: ignore[misc,valid-type]
    """Strict, deterministic output parser for LlamaIndex.

    Args:
        inner: Optional parser to wrap, typically a ``PydanticOutputParser``;
            its ``output_cls`` and ``format()`` are reused.
        output_cls: Pydantic model class to build (overrides ``inner``'s).
        json_schema: JSON Schema to validate against (defaults to the model's).
        select, kind: Passed to :func:`beacon.extract_json`.
    """

    def __init__(
        self,
        inner: Any = None,
        *,
        output_cls: Any = None,
        json_schema: Optional[Mapping[str, Any]] = None,
        select: str = "first",
        kind: str = "auto",
    ) -> None:
        self.inner = inner
        if output_cls is None and inner is not None:
            candidate = getattr(inner, "output_cls", None)
            output_cls = candidate if is_model_class(candidate) else None
        self.output_cls = output_cls
        self.json_schema = dict(json_schema) if json_schema is not None else schema_for(output_cls)
        self.select = select
        self.kind = kind

    def parse(self, output: str) -> Any:
        return parse_structured(output, schema=self.json_schema, model=self.output_cls, select=self.select, kind=self.kind)

    def format(self, query: str) -> str:
        if self.inner is not None and hasattr(self.inner, "format"):
            return self.inner.format(query)
        return query
