"""Framework integrations. Each submodule is optional and imports its framework
lazily, so ``import beacon`` never pulls in LangChain, LlamaIndex, etc.

* :mod:`beacon.integrations.openai_sdk` — no extra dependency (duck-typed)
* :mod:`beacon.integrations.anthropic_sdk` — no extra dependency (duck-typed)
* :mod:`beacon.integrations.langchain` — ``pip install "llm-beacon[langchain]"``
* :mod:`beacon.integrations.llamaindex` — ``pip install "llm-beacon[llamaindex]"``
* :mod:`beacon.integrations.pydantic_ai` — works without Pydantic AI; uses
  ``ModelRetry`` when it is installed
* :mod:`beacon.integrations.dspy` — ``pip install "llm-beacon[dspy]"`` for the
  adapter; the validator works without DSPy
"""

from ._common import parse_structured, schema_for

__all__ = ["parse_structured", "schema_for"]
