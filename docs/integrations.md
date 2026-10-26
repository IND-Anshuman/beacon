# Integrations

All integrations are optional. `import beacon` never imports a framework.

| Framework | Install | Module |
| --- | --- | --- |
| OpenAI SDK | none (duck-typed) | `beacon.integrations.openai_sdk` |
| LangChain | `pip install "llm-beacon[langchain]"` | `beacon.integrations.langchain` |
| LlamaIndex | `pip install "llm-beacon[llamaindex]"` | `beacon.integrations.llamaindex` |
| Pydantic AI | `pip install "llm-beacon[pydantic-ai]"` (optional) | `beacon.integrations.pydantic_ai` |
| DSPy | `pip install "llm-beacon[dspy]"` | `beacon.integrations.dspy` |

Tested against: openai 2.x, langchain-core 1.x, llama-index-core 0.14,
pydantic-ai 2.x, dspy 3.x.

## OpenAI SDK

```python
from openai import OpenAI, AsyncOpenAI
from beacon.integrations.openai_sdk import validated_completion, avalidated_completion, validated_tool_call

client = OpenAI()
result = validated_completion(
    client,
    model="gpt-4o",
    messages=[{"role": "user", "content": "Classify: I want to cancel"}],
    schema={"type": "object", "properties": {"intent": {"type": "string"}}, "required": ["intent"]},
)

result = await avalidated_completion(AsyncOpenAI(), model="gpt-4o", messages=[...], output_model=Intent)
```

* `schema` defaults to `output_model.model_json_schema()`. With
  `output_model`, a model instance is returned.
* Failures raise `MalformedOutputError` / `SchemaValidationError` with
  `.raw` set to the model text. Refusals and empty content raise
  `MalformedOutputError(code="openai.no_content")`.
* `create=client.responses.create` switches to the Responses API (reads
  `output_text`).
* `validated_tool_call(response, tool_schemas={...})` returns
  `[{"name", "arguments"}]` from native `tool_calls`, parsing their JSON-string
  arguments strictly. If there are none, it parses tool calls from the message
  text. Optionally validates each call's arguments per tool.

Any OpenAI-compatible client works (Azure, vLLM, LiteLLM, test fakes).

## LangChain

```python
from beacon.integrations.langchain import BeaconPromptTemplate, BeaconJsonOutputParser, BeaconCallbackHandler

prompt = BeaconPromptTemplate.from_template("Classify: <msg>{message}</msg>")
parser = BeaconJsonOutputParser(pydantic_object=Intent)        # or json_schema=..., pydantic_schema=...
chain = prompt | ChatOpenAI(model="gpt-4o") | parser
chain.invoke({"message": "I want to cancel"})                   # -> Intent(...)
```

* `BeaconPromptTemplate`: input variables are inferred, values are
  XML-escaped (`escape=`), missing variables raise `MissingVariableError`, and
  extra chain inputs are ignored, as LangChain expects.
* `BeaconJsonOutputParser`: strict extraction plus validation. Failures raise
  LangChain's `OutputParserException` (so `with_retry` and fixing parsers
  work), with the beacon error as `.beacon_error` and `__cause__`.
  `get_format_instructions()` is deterministic.
* Format instructions contain JSON braces, so don't concatenate them into
  the template. Pass them as a partial and insert them unescaped:

  ```python
  prompt = BeaconPromptTemplate(
      template="<q>{question}</q>\n\n{format_instructions!raw}",
      partial_variables={"format_instructions": parser.get_format_instructions()},
  )
  ```
* `BeaconCallbackHandler(schema=...)`: for every LLM response in a run,
  records `{run_id, text_hash, json_found, source, valid, errors, error_code}`
  in `.records` and logs it on `beacon.integrations.langchain`.

## LlamaIndex

```python
from llama_index.core.output_parsers import PydanticOutputParser
from beacon.integrations.llamaindex import BeaconOutputParser

parser = BeaconOutputParser(PydanticOutputParser(QueryResponse))
query_engine = index.as_query_engine(output_parser=parser)
```

The parser subclasses LlamaIndex's `BaseOutputParser`. `format()` delegates
to the wrapped parser, so its prompt instructions are kept, and `parse()`
uses beacon's strict extraction and validation and returns a
`QueryResponse`. You can also pass `output_cls=` or `json_schema=` directly.

## Pydantic AI

```python
from pydantic_ai import Agent
from beacon.integrations.pydantic_ai import BeaconValidator

agent = Agent("openai:gpt-4o", output_type=Intent)
agent.output_validator(BeaconValidator(Intent))
```

(Pydantic AI has no `result_validator=` keyword. Validators are registered
with the `output_validator` decorator/method.)

* Checks model outputs against the model's schema, or against a stricter
  JSON Schema you pass instead (e.g. with `enum`s or bounds the model class
  doesn't express).
* For `output_type=str` agents, it extracts and validates JSON from the text
  and returns the parsed value.
* On failure it raises `ModelRetry` with beacon's stable message, so the
  agent re-asks the model with precise feedback. Pass `retry=False` to get
  the beacon exception instead.

## DSPy

```python
import dspy
from beacon.integrations.dspy import BeaconJSONAdapter, BeaconValidateSchema

dspy.configure(lm=dspy.LM("openai/gpt-4o"), adapter=BeaconJSONAdapter())

class IntentModule(dspy.Module):
    def __init__(self):
        super().__init__()
        self.extract = dspy.ChainOfThought(IntentSignature)
        self.validate = BeaconValidateSchema(IntentSignature)

    def forward(self, message):
        return self.validate(self.extract(message=message))
```

* `BeaconJSONAdapter` subclasses `dspy.JSONAdapter`. It keeps DSPy's prompt
  formatting and replaces parsing with `extract_json(kind="object")`. Missing
  or malformed fields raise DSPy's `AdapterParseError`, which feeds DSPy's
  own retry and fallback. Values are then converted to the field annotations
  by DSPy's `parse_value`. That conversion is DSPy's behaviour, not
  beacon's.
* `BeaconValidateSchema(signature)` builds a JSON Schema from the
  signature's output fields (via Pydantic) and validates predictions against
  it. A JSON Schema mapping also works.

DSPy's adapter API is internal and changes between releases. The adapter is
tested against DSPy 3.x.
