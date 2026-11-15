# Strict structured outputs with beacon

[beacon](https://github.com/IND-Anshuman/beacon) is a library of deterministic
building blocks for LLM pipelines: the same input always yields byte-identical
output. Its LlamaIndex integration is a drop-in `BaseOutputParser` that replaces
lenient JSON scraping with strict extraction and schema validation, backed by a
pure-Rust core.

## Install

```bash
pip install "llm-beacon[llamaindex]"
```

## Minimal example

```python
from llama_index.core import SimpleDirectoryReader, VectorStoreIndex
from llama_index.core.output_parsers import PydanticOutputParser
from pydantic import BaseModel
from beacon.integrations.llamaindex import BeaconOutputParser

class QueryResponse(BaseModel):
    answer: str
    sources: list[str]
    confidence: float

index = VectorStoreIndex.from_documents(SimpleDirectoryReader("data").load_data())
parser = BeaconOutputParser(PydanticOutputParser(QueryResponse))
query_engine = index.as_query_engine(output_parser=parser)
```

The parser sits between the response synthesizer and your code:

- **`format()`** delegates to the wrapped parser, so LlamaIndex's format
  instructions still reach the model.
- **`parse()`** uses beacon's strict extraction and validation, and returns a
  `QueryResponse`.

## Construct it your way

```python
BeaconOutputParser(PydanticOutputParser(QueryResponse))   # reuse output_cls + format()
BeaconOutputParser(output_cls=QueryResponse)
BeaconOutputParser(json_schema={"type": "object", "required": ["answer"]})  # returns dicts
```

## Failures are precise

```python
>>> parser.parse('{"answer": "30 days", "sources": "refunds.md", "confidence": 0.86}')
SchemaValidationError: 1 schema violation:
  - /sources: expected type "array", got "string"
```

The error carries a JSON-pointer path and the raw synthesized text as `.raw`, so
a malformed response fails loudly and locatably instead of flowing downstream.

Full reference: <https://www.anshumanbuilds.dev/beacon/integrations/llamaindex/>.
