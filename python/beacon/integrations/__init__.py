"""Framework integrations. Each submodule is optional and imports its framework
lazily, so ``import beacon`` never pulls in LangChain, LlamaIndex, etc.

* :mod:`beacon.integrations.openai_sdk` — no extra dependency (duck-typed)
* :mod:`beacon.integrations.anthropic_sdk` — no extra dependency (duck-typed)
* :mod:`beacon.integrations.gemini_sdk` — no extra dependency (duck-typed)
* :mod:`beacon.integrations.litellm` — ``pip install "llm-beacon[litellm]"``
  (only to make real calls; response parsing is duck-typed)
* :mod:`beacon.integrations.otel` — ``pip install "llm-beacon[otel]"`` (only
  when no tracer is injected)
* :mod:`beacon.integrations.mcp` — no extra dependency (duck-typed); the ``mcp``
  SDK is only needed to run a server/client (``pip install "llm-beacon[mcp]"``)
* :mod:`beacon.integrations.langchain` — ``pip install "llm-beacon[langchain]"``
* :mod:`beacon.integrations.llamaindex` — ``pip install "llm-beacon[llamaindex]"``
* :mod:`beacon.integrations.pydantic_ai` — works without Pydantic AI; uses
  ``ModelRetry`` when it is installed
* :mod:`beacon.integrations.dspy` — ``pip install "llm-beacon[dspy]"`` for the
  adapter; the validator works without DSPy
* :mod:`beacon.integrations.openai_agents` — no extra dependency (duck-typed);
  ``pip install "llm-beacon[openai-agents]"`` only to run the Agents SDK
* :mod:`beacon.integrations.smolagents` — no extra dependency (duck-typed);
  ``pip install "llm-beacon[smolagents]"`` only to run smolagents
* :mod:`beacon.integrations.haystack` — ``validate_replies`` is duck-typed; the
  pipeline component needs ``pip install "llm-beacon[haystack]"``
* :mod:`beacon.integrations.strands` — no extra dependency (duck-typed);
  ``pip install "llm-beacon[strands]"`` only to run Strands Agents
* :mod:`beacon.integrations.autogen` — no extra dependency (duck-typed);
  ``pip install "llm-beacon[autogen]"`` only to run AutoGen
* :mod:`beacon.integrations.crewai` — no extra dependency (duck-typed);
  ``pip install "llm-beacon[crewai]"`` only to run CrewAI
* :mod:`beacon.integrations.agno` — no extra dependency (duck-typed);
  ``pip install "llm-beacon[agno]"`` only to run Agno
* :mod:`beacon.integrations.semantic_kernel` — no extra dependency (duck-typed);
  ``pip install "llm-beacon[semantic-kernel]"`` only to run Semantic Kernel
"""

from ._common import parse_structured, schema_for

__all__ = ["parse_structured", "schema_for"]
