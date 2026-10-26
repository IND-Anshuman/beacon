"""LlamaIndex: a strict output parser for query engines.

Runs offline: the synthesized response is canned. In a real app:

    index = VectorStoreIndex.from_documents(SimpleDirectoryReader("data").load_data())
    query_engine = index.as_query_engine(output_parser=parser)

Requires: pip install "llm-beacon[llamaindex]"
"""

from __future__ import annotations

from llama_index.core.output_parsers import PydanticOutputParser
from pydantic import BaseModel

from beacon import MalformedOutputError, SchemaValidationError
from beacon.integrations.llamaindex import BeaconOutputParser


class QueryResponse(BaseModel):
    answer: str
    sources: list[str]
    confidence: float


parser = BeaconOutputParser(PydanticOutputParser(QueryResponse))

# format() keeps LlamaIndex's own instructions for the model.
print(parser.format("What is the refund window?")[:120], "...")

synthesized = 'Based on the documents:\n```json\n{"answer": "30 days", "sources": ["refunds.md"], "confidence": 0.86}\n```'
print(parser.parse(synthesized))

for bad in ('{"answer": "30 days", "sources": "refunds.md", "confidence": 0.86}', '{"answer": "30 days", '):
    try:
        parser.parse(bad)
    except (SchemaValidationError, MalformedOutputError) as err:
        print(f"{type(err).__name__}: {err}")
