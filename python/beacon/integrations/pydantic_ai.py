"""Pydantic AI integration: an output validator that applies beacon's checks.

Register it with the agent's ``output_validator`` decorator::

    from pydantic_ai import Agent
    from beacon.integrations.pydantic_ai import BeaconValidator

    agent = Agent("openai:gpt-4o", output_type=Intent)
    agent.output_validator(BeaconValidator(Intent))

When validation fails and Pydantic AI is installed, the validator raises
``ModelRetry`` with beacon's (stable) error message, so the agent asks the
model to try again with precise feedback. For ``output_type=str`` agents the
validator extracts and validates JSON from the text.
"""

from __future__ import annotations

from typing import Any, Optional

from .._api import validate_schema
from ..errors import BeaconError
from ._common import is_model_class, optional, parse_structured, schema_for

__all__ = ["BeaconValidator"]


class BeaconValidator:
    """Validate an agent's output against a JSON Schema with beacon.

    Args:
        model_or_schema: A Pydantic model class or a JSON Schema mapping.
        retry: Raise ``pydantic_ai.ModelRetry`` on failure (if Pydantic AI is
            installed) instead of the beacon error.
        select, kind: Used when the output is text.
    """

    def __init__(
        self,
        model_or_schema: Any,
        *,
        retry: bool = True,
        select: str = "first",
        kind: str = "auto",
    ) -> None:
        self.model = model_or_schema if is_model_class(model_or_schema) else None
        self.schema: Optional[dict[str, Any]] = schema_for(model_or_schema)
        self.retry = retry
        self.select = select
        self.kind = kind
        self.__name__ = f"BeaconValidator[{getattr(self.model, '__name__', 'schema')}]"

    def validate(self, output: Any) -> Any:
        """Validate without the ``ModelRetry`` translation."""
        if isinstance(output, str):
            return parse_structured(output, schema=self.schema, model=self.model, select=self.select, kind=self.kind)
        dump = getattr(output, "model_dump", None)
        data = dump(mode="json") if callable(dump) else output
        if self.schema is not None:
            validate_schema(data, self.schema)
        return output

    def __call__(self, output: Any) -> Any:
        try:
            return self.validate(output)
        except BeaconError as exc:
            pai = optional("pydantic_ai") if self.retry else None
            if pai is not None and hasattr(pai, "ModelRetry"):
                raise pai.ModelRetry(str(exc)) from exc
            raise

    def __repr__(self) -> str:
        return self.__name__

