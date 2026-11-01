"""LiteLLM integration: validated completions across 100+ providers.

LiteLLM normalizes every provider to the OpenAI response schema, so beacon
reuses the OpenAI response helpers (:func:`response_text`,
:func:`validated_tool_call`) and only swaps the call: ``litellm.completion`` and
``litellm.acompletion``.

>>> from beacon.integrations.litellm import validated_completion
>>> data = validated_completion(  # doctest: +SKIP
...     model="anthropic/claude-3-5-sonnet",
...     messages=[{"role": "user", "content": "Classify: I want to cancel"}],
...     schema={"type": "object", "properties": {"intent": {"type": "string"}}, "required": ["intent"]},
... )

``litellm`` is imported lazily and only when you do not pass your own
``completion`` / ``acompletion`` callable, so the response-parsing helpers and
injected fakes work without the package installed
(``pip install "llm-beacon[litellm]"`` for the real thing).
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Mapping, Optional

from ._common import parse_structured, require
from .openai_sdk import response_text, validated_tool_call

__all__ = ["validated_completion", "avalidated_completion", "validated_tool_call", "response_text"]


def _completion() -> Callable[..., Any]:
    return require("litellm", "litellm", "beacon.integrations.litellm").completion


def _acompletion() -> Callable[..., Awaitable[Any]]:
    return require("litellm", "litellm", "beacon.integrations.litellm").acompletion


def validated_completion(
    *,
    schema: Optional[Mapping[str, Any]] = None,
    output_model: Any = None,
    select: str = "first",
    kind: str = "auto",
    completion: Optional[Callable[..., Any]] = None,
    **create_kwargs: Any,
) -> Any:
    """Call ``litellm.completion(**create_kwargs)`` and return the validated JSON
    (or an ``output_model`` instance).

    Args:
        schema: JSON Schema to validate against. Defaults to
            ``output_model.model_json_schema()``.
        output_model: Optional Pydantic model class to build from the JSON.
        select, kind: Passed to :func:`beacon.extract_json`.
        completion: Use this callable instead of ``litellm.completion`` (e.g. a
            test fake or a configured router's ``.completion``).
        **create_kwargs: Forwarded to the completion call (``model``,
            ``messages``, …).
    """
    fn = completion if completion is not None else _completion()
    response = fn(**create_kwargs)
    return parse_structured(response_text(response), schema=schema, model=output_model, select=select, kind=kind)


async def avalidated_completion(
    *,
    schema: Optional[Mapping[str, Any]] = None,
    output_model: Any = None,
    select: str = "first",
    kind: str = "auto",
    acompletion: Optional[Callable[..., Awaitable[Any]]] = None,
    **create_kwargs: Any,
) -> Any:
    """Async version of :func:`validated_completion`, calling
    ``litellm.acompletion`` (override with ``acompletion=``)."""
    fn = acompletion if acompletion is not None else _acompletion()
    response = await fn(**create_kwargs)
    return parse_structured(response_text(response), schema=schema, model=output_model, select=select, kind=kind)
