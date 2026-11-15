# Deterministic JSON output with beacon

[beacon](https://github.com/IND-Anshuman/beacon) is a small library of
deterministic building blocks for LLM pipelines — the same input always produces
byte-identical output, error messages included. Its LangChain integration gives
you a prompt template, a **strict** JSON output parser, and a callback handler,
all backed by a pure-Rust core.

Use it when lenient JSON scraping has bitten you: a model wraps JSON in prose, a
trailing comma slips through, or a parser silently returns half-parsed data.

## Install

```bash
pip install "llm-beacon[langchain]"
```

## Minimal example

```python
from langchain_openai import ChatOpenAI
from pydantic import BaseModel
from beacon.integrations.langchain import BeaconJsonOutputParser, BeaconPromptTemplate

class Intent(BaseModel):
    intent: str
    confidence: float

prompt = BeaconPromptTemplate.from_template("Classify: <msg>{message}</msg>")
parser = BeaconJsonOutputParser(pydantic_object=Intent)

chain = prompt | ChatOpenAI(model="gpt-4o") | parser
chain.invoke({"message": "I want to cancel"})
# -> Intent(intent='cancel', confidence=0.93)
```

`BeaconJsonOutputParser` extracts the JSON from fenced blocks or surrounding
prose with a fully specified algorithm, parses it strictly (RFC 8259), and
validates it against your Pydantic model or a JSON Schema.

## Failures are LangChain-native

A parse or validation failure raises LangChain's `OutputParserException`, so
`with_retry()` and `OutputFixingParser` keep working. The underlying beacon
error is attached for inspection:

```python
from langchain_core.exceptions import OutputParserException

try:
    chain.invoke({"message": "..."})
except OutputParserException as exc:
    exc.beacon_error.code   # e.g. 'json.trailing_comma'
    exc.llm_output          # the raw model text
```

## Why determinism helps

`BeaconPromptTemplate.get_format_instructions()` and the parser's output are
deterministic for a given schema, so you can snapshot-test a chain's parsing and
formatting. A diff in CI then means *your* change moved the output — never flaky
parsing.

Tested with `langchain-core` 1.x (including `FakeListChatModel`). Full
reference: <https://www.anshumanbuilds.dev/beacon/integrations/langchain/>.
