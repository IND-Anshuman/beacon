"""Validated calls for the raw OpenAI Python client (sync and async).

No dependency on the ``openai`` package: the client is duck-typed, so any
OpenAI-compatible client (Azure, vLLM, LiteLLM proxies, test fakes) works.

>>> from beacon.integrations.openai_sdk import validated_completion
>>> result = validated_completion(  # doctest: +SKIP
...     client,
...     model="gpt-4o",
...     messages=[{"role": "user", "content": "Classify: I want to cancel"}],
...     schema={"type": "object", "properties": {"intent": {"type": "string"}}, "required": ["intent"]},
... )

If the model returns no JSON, malformed JSON, or JSON that violates the
schema, a :class:`~beacon.MalformedOutputError` or
:class:`~beacon.SchemaValidationError` is raised with ``.raw`` set to the
model's text.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Mapping, Optional

from .._api import parse_tool_calls, validate_schema
from ..errors import MalformedOutputError, SchemaValidationError
from ._common import parse_structured

__all__ = ["validated_completion", "avalidated_completion", "validated_tool_call", "response_text"]


def _get(obj: Any, name: str) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name)
    return getattr(obj, name, None)


def _message(response: Any) -> Any:
    choices = _get(response, "choices")
    if choices:
        return _get(choices[0], "message")
    return None


def response_text(response: Any) -> str:
    """The text of a Chat Completions or Responses API response.

    Raises :class:`~beacon.MalformedOutputError` (code ``openai.no_content``)
    when there is no text, e.g. for a refusal or a tool-call-only message.
    """
    message = _message(response)
    if message is not None:
        content = _get(message, "content")
        if isinstance(content, str):
            return content
        refusal = _get(message, "refusal")
        detail = f" (refusal: {refusal})" if refusal else ""
        raise MalformedOutputError(f"completion has no text content{detail}", code="openai.no_content")
    output_text = _get(response, "output_text")
    if isinstance(output_text, str):
        return output_text
    raise MalformedOutputError("response has no text content", code="openai.no_content")


def _create(client: Any, create: Optional[Callable[..., Any]]) -> Callable[..., Any]:
    if create is not None:
        return create
    return client.chat.completions.create


def validated_completion(
    client: Any,
    *,
    schema: Optional[Mapping[str, Any]] = None,
    output_model: Any = None,
    select: str = "first",
    kind: str = "auto",
    create: Optional[Callable[..., Any]] = None,
    **create_kwargs: Any,
) -> Any:
    """Call ``client.chat.completions.create(**create_kwargs)`` and return the
    validated JSON (or an ``output_model`` instance).

    Args:
        client: An OpenAI-compatible client.
        schema: JSON Schema to validate against. Defaults to
            ``output_model.model_json_schema()``.
        output_model: Optional Pydantic model class to build from the JSON.
        select, kind: Passed to :func:`beacon.extract_json`.
        create: Use this callable instead of ``client.chat.completions.create``
            (e.g. ``client.responses.create``).
    """
    response = _create(client, create)(**create_kwargs)
    text = response_text(response)
    return parse_structured(text, schema=schema, model=output_model, select=select, kind=kind)


async def avalidated_completion(
    client: Any,
    *,
    schema: Optional[Mapping[str, Any]] = None,
    output_model: Any = None,
    select: str = "first",
    kind: str = "auto",
    create: Optional[Callable[..., Any]] = None,
    **create_kwargs: Any,
) -> Any:
    """Async version of :func:`validated_completion` for ``AsyncOpenAI``."""
    response = await _create(client, create)(**create_kwargs)
    text = response_text(response)
    return parse_structured(text, schema=schema, model=output_model, select=select, kind=kind)


def validated_tool_call(
    response: Any,
    *,
    tool_schemas: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> list[dict[str, Any]]:
    """Tool calls from a Chat Completions response, as ``{"name", "arguments"}``.

    Native ``message.tool_calls`` are used when present (their JSON-string
    arguments are parsed strictly); otherwise the message text is parsed with
    :func:`beacon.parse_tool_calls`, which covers models that emit tool calls
    as text. ``tool_schemas`` maps tool names to JSON Schemas for their
    arguments; a call to an unknown tool raises when it is given.
    """
    message = _message(response)
    native = _get(message, "tool_calls") if message is not None else None
    if native:
        envelope = []
        for call in native:
            fn = _get(call, "function")
            envelope.append({"name": _get(fn, "name"), "arguments": _get(fn, "arguments")})
        text = json.dumps({"tool_calls": [{"function": e} for e in envelope]})
    else:
        text = response_text(response)
    calls = parse_tool_calls(text)
    if tool_schemas is not None:
        for call in calls:
            schema = tool_schemas.get(call["name"])
            if schema is None:
                raise MalformedOutputError(
                    f"model called unknown tool {call['name']!r}", code="openai.unknown_tool", raw=text
                )
            try:
                validate_schema(call["arguments"], schema)
            except SchemaValidationError as exc:
                exc.raw = text
                raise
    return calls
