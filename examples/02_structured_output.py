"""Structured output: extract JSON, validate it, parse tool calls, redact logs."""

from beacon import (
    MalformedOutputError,
    SchemaValidationError,
    extract_json,
    extract_json_detailed,
    parse_tool_calls,
    redact,
    validate_schema,
)

INTENT = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": ["cancel", "refund", "question"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["intent", "confidence"],
}

responses = [
    'Sure! Here is the result:\n```json\n{"intent": "cancel", "confidence": 0.93}\n```\nAnything else?',
    'Based on [1] and [2], the answer is {"intent": "refund", "confidence": 0.7}.',
    '{"intent": "cancel", "confidence": 0.9,}',  # trailing comma
    '{"intent": "explode", "confidence": 1.5}',  # schema violations
    '{"intent": "question", "confidence": 0.',  # truncated
]

for raw in responses:
    try:
        result = extract_json(raw, schema=INTENT)
        print("ok      ", result)
    except SchemaValidationError as err:
        print("invalid ", err.errors)
    except MalformedOutputError as err:
        print(f"malformed [{err.code}] at {err.position}: {err}")

found = extract_json_detailed(responses[0])
print(found.source, responses[0][found.start : found.end])

validate_schema({"intent": "question", "confidence": 0.2}, INTENT)  # returns None when valid

# Tool calls in whatever format the model prefers.
for text in (
    '<tool_call>{"name": "get_weather", "arguments": {"city": "Paris"}}</tool_call>',
    '[TOOL_CALLS]get_weather[ARGS]{"city": "Paris"}',
    'I will call get_weather(city="Paris", days=3)',
):
    print(parse_tool_calls(text, include_format=True))

# Redact before logging.
print(redact("User jane@example.com paid with 4242 4242 4242 4242, key sk-proj-abcdefghijklmnopqrstuv"))
