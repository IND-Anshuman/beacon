"""LangChain integration: prompt template, output parser, callback handler.

>>> from beacon.integrations.langchain import BeaconJsonOutputParser  # doctest: +SKIP
>>> parser = BeaconJsonOutputParser(pydantic_object=Intent)           # doctest: +SKIP
>>> chain = prompt | llm | parser                                     # doctest: +SKIP

Parsing failures raise LangChain's ``OutputParserException`` (so retry and
fixing parsers work), with the beacon error as ``__cause__`` and as
``.beacon_error``.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping, Optional
from uuid import UUID

from ._common import require

require("langchain_core", "langchain", "beacon.integrations.langchain")

from langchain_core.callbacks import BaseCallbackHandler  # noqa: E402
from langchain_core.exceptions import OutputParserException  # noqa: E402
from langchain_core.output_parsers import BaseOutputParser  # noqa: E402
from langchain_core.outputs import LLMResult  # noqa: E402
from langchain_core.prompts import StringPromptTemplate  # noqa: E402
from pydantic import model_validator  # noqa: E402

from .._api import extract_json_detailed, hash_content, schema_errors, template, template_variables  # noqa: E402
from .._schema import schema_instructions as _schema_instructions  # noqa: E402
from ..errors import BeaconError, MalformedOutputError, SchemaValidationError  # noqa: E402
from ._common import parse_structured, schema_for  # noqa: E402

__all__ = ["BeaconPromptTemplate", "BeaconJsonOutputParser", "BeaconCallbackHandler", "format_instructions"]

logger = logging.getLogger("beacon.integrations.langchain")


class BeaconPromptTemplate(StringPromptTemplate):
    """A LangChain prompt template rendered by :func:`beacon.template`.

    Missing variables raise :class:`~beacon.MissingVariableError`; values are
    escaped according to ``escape`` (``"xml"`` by default). Extra inputs are
    ignored, as LangChain chains routinely pass a shared input dict.
    """

    template: str
    escape: str = "xml"

    @model_validator(mode="before")
    @classmethod
    def _infer_input_variables(cls, values: Any) -> Any:
        if isinstance(values, dict) and "template" in values and "input_variables" not in values:
            partial = set((values.get("partial_variables") or {}).keys())
            values = {**values, "input_variables": [v for v in template_variables(values["template"]) if v not in partial]}
        return values

    @classmethod
    def from_template(cls, template: str, *, escape: str = "xml", **kwargs: Any) -> "BeaconPromptTemplate":  # type: ignore[override]
        return cls(template=template, escape=escape, **kwargs)

    def format(self, **kwargs: Any) -> str:
        merged = self._merge_partial_and_user_variables(**kwargs)
        used = set(template_variables(self.template))
        variables = {k: v for k, v in merged.items() if k in used}
        return template(self.template, variables, strict=True, escape=self.escape)  # type: ignore[arg-type]

    @property
    def _prompt_type(self) -> str:
        return "beacon"


def format_instructions(schema: Mapping[str, Any]) -> str:
    """Deterministic instructions asking the model for JSON matching ``schema``.

    Thin alias for :func:`beacon.schema_instructions`, kept for LangChain users.
    """
    return _schema_instructions(schema)


class BeaconJsonOutputParser(BaseOutputParser[Any]):
    """Parse LLM output with :func:`beacon.extract_json` and validate it.

    Args:
        json_schema: JSON Schema to validate against (alias:
            ``pydantic_schema``, as in ``Model.model_json_schema()``).
        pydantic_object: Optional Pydantic model class; the parser then returns
            a model instance and uses its schema by default.
        select, kind: Passed to :func:`beacon.extract_json`.
    """

    json_schema: Optional[dict[str, Any]] = None
    pydantic_object: Optional[Any] = None
    select: str = "first"
    kind: str = "auto"

    def __init__(self, json_schema: Optional[Mapping[str, Any]] = None, **kwargs: Any) -> None:
        if json_schema is None and "pydantic_schema" in kwargs:
            json_schema = kwargs.pop("pydantic_schema")
        if json_schema is None and kwargs.get("pydantic_object") is not None:
            json_schema = schema_for(kwargs["pydantic_object"])
        super().__init__(json_schema=dict(json_schema) if json_schema is not None else None, **kwargs)

    def parse(self, text: str) -> Any:
        try:
            return parse_structured(
                text, schema=self.json_schema, model=self.pydantic_object, select=self.select, kind=self.kind
            )
        except BeaconError as exc:
            err = OutputParserException(str(exc), llm_output=text)
            err.beacon_error = exc  # type: ignore[attr-defined]
            raise err from exc

    def get_format_instructions(self) -> str:
        if self.json_schema is None:
            return "Respond with a single JSON value."
        return format_instructions(self.json_schema)

    @property
    def _type(self) -> str:
        return "beacon_json"


class BeaconCallbackHandler(BaseCallbackHandler):
    """Records what beacon makes of every LLM response in a run.

    For each generation, a record is appended to :attr:`records` and logged
    at INFO level on the ``beacon.integrations.langchain`` logger::

        {"run_id", "text_hash", "json_found", "source", "valid", "errors", "error_code"}

    ``valid`` is ``None`` when no schema was given. Records contain only
    deterministic data (no timestamps), so they can be snapshot-tested.
    """

    def __init__(self, schema: Optional[Mapping[str, Any]] = None, *, log_level: int = logging.INFO) -> None:
        self.schema = dict(schema) if schema is not None else None
        self.log_level = log_level
        self.records: list[dict[str, Any]] = []

    def inspect_text(self, text: str, run_id: Optional[UUID] = None) -> dict[str, Any]:
        record: dict[str, Any] = {
            "run_id": str(run_id) if run_id is not None else None,
            "text_hash": hash_content(text),
            "json_found": False,
            "source": None,
            "valid": None,
            "errors": [],
            "error_code": None,
        }
        try:
            extraction = extract_json_detailed(text)
        except MalformedOutputError as exc:
            record["error_code"] = exc.code
        else:
            record["json_found"] = True
            record["source"] = extraction.source
            if self.schema is not None:
                try:
                    errors = schema_errors(extraction.value, self.schema)
                except (BeaconError, TypeError) as exc:
                    record["error_code"] = getattr(exc, "code", "schema.invalid")
                else:
                    record["valid"] = not errors
                    record["errors"] = [dict(e) for e in errors]
                    if errors:
                        record["error_code"] = SchemaValidationError.default_code
        return record

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        for generations in response.generations:
            for generation in generations:
                record = self.inspect_text(generation.text, run_id)
                self.records.append(record)
                logger.log(self.log_level, "beacon: %s", record)
