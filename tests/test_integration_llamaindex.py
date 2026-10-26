from __future__ import annotations

import pytest
from pydantic import BaseModel

from beacon import MalformedOutputError, SchemaValidationError
from beacon.integrations.llamaindex import BeaconOutputParser


class QueryResponse(BaseModel):
    answer: str
    sources: list[str]
    confidence: float


GOOD = 'Answer below.\n```json\n{"answer": "42", "sources": ["doc1"], "confidence": 0.8}\n```'


def test_parse_with_output_cls() -> None:
    parser = BeaconOutputParser(output_cls=QueryResponse)
    assert parser.parse(GOOD) == QueryResponse(answer="42", sources=["doc1"], confidence=0.8)


def test_schema_violation() -> None:
    parser = BeaconOutputParser(output_cls=QueryResponse)
    with pytest.raises(SchemaValidationError) as exc:
        parser.parse('{"answer": "42", "sources": "doc1", "confidence": 2}')
    assert [e["path"] for e in exc.value.errors] == ["/sources"]
    assert exc.value.raw is not None


def test_malformed() -> None:
    with pytest.raises(MalformedOutputError):
        BeaconOutputParser(output_cls=QueryResponse).parse('{"answer": ')


def test_json_schema_only() -> None:
    parser = BeaconOutputParser(json_schema={"type": "object", "required": ["answer"]})
    assert parser.parse('{"answer": "x"}') == {"answer": "x"}
    assert parser.format("q") == "q"


def test_wraps_real_pydantic_output_parser() -> None:
    pytest.importorskip("llama_index.core")
    from llama_index.core.output_parsers import PydanticOutputParser
    from llama_index.core.types import BaseOutputParser

    inner = PydanticOutputParser(QueryResponse)
    parser = BeaconOutputParser(inner)
    assert isinstance(parser, BaseOutputParser)
    assert parser.output_cls is QueryResponse
    assert parser.format("What is it?") == inner.format("What is it?")
    assert parser.parse(GOOD).answer == "42"
