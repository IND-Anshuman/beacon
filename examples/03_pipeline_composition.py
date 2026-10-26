"""Compose blocks into a pipeline, with deterministic retries and a hash trace."""

from __future__ import annotations

from beacon import Block, Pipeline, RetryPolicy, extract_json, hash_content, normalize, redact, retry, template

INTENT = {
    "type": "object",
    "properties": {"intent": {"enum": ["cancel", "refund", "question"]}, "confidence": {"type": "number"}},
    "required": ["intent", "confidence"],
}


class RateLimitError(Exception):
    status_code = 429


class FlakyLLM:
    """Pretends to be an API: rate-limited once, then answers."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, prompt: str) -> str:
        self.calls += 1
        if self.calls == 1:
            raise RateLimitError("slow down")
        return '```json\n{"intent": "cancel", "confidence": 0.91}\n```'


class Clean(Block):
    def run(self, message: str) -> str:
        return redact(normalize(message))


class ExtractIntent(Block):
    def __init__(self, llm: FlakyLLM) -> None:
        self.llm = llm
        self.policy = RetryPolicy(max_attempts=3, jitter_key="example")

    def run(self, message: str) -> dict:
        prompt = template("Classify as JSON: <msg>{m}</msg>", m=message)
        raw = retry.call(
            self.llm,
            prompt,
            policy=self.policy,
            sleep=lambda s: print(f"  (would sleep {s:.3f}s)"),
            on_retry=lambda exc, d: print(f"  retry: {d.reason.value}, attempt {d.attempt}"),
        )
        return extract_json(raw, schema=INTENT)


def route(intent: dict) -> str:
    return {"cancel": "retention", "refund": "billing"}.get(intent["intent"], "support")


pipeline = Pipeline([Clean(), ExtractIntent(FlakyLLM()), route])
result = pipeline.run_traced("  I want to   CANCEL. Email: jane@example.com ")
print("output:", result.output)
for step in result.trace():
    print(step)

# The decision for a given failure is always the same:
print(retry.classify(RateLimitError(), attempt=1, policy=RetryPolicy(jitter_key="example")))
print(hash_content(result.trace()))
