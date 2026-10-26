"""DSPy integration: a JSON adapter and an output validator.

::

    import dspy
    from beacon.integrations.dspy import BeaconJSONAdapter, BeaconValidateSchema

    dspy.configure(lm=..., adapter=BeaconJSONAdapter())

    class IntentModule(dspy.Module):
        def __init__(self):
            super().__init__()
            self.extract = dspy.ChainOfThought(IntentSignature)
            self.validate = BeaconValidateSchema(IntentSignature)

        def forward(self, message):
            return self.validate(self.extract(message=message))

:class:`BeaconJSONAdapter` keeps DSPy's JSON prompt formatting and replaces
the response parsing with :func:`beacon.extract_json` (strict, no repair).
DSPy's adapter API is internal and changes between releases; the adapter is
tested against DSPy 3.x.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from .._api import extract_json, validate_schema
from ..errors import MalformedOutputError
from ._common import optional

__all__ = ["BeaconJSONAdapter", "BeaconValidateSchema", "signature_schema"]

_dspy = optional("dspy")


def _output_fields(signature: Any) -> dict[str, Any]:
    fields = getattr(signature, "output_fields", None)
    if not isinstance(fields, Mapping):
        raise TypeError(f"expected a DSPy Signature class, got {signature!r}")
    return dict(fields)


def signature_schema(signature: Any) -> dict[str, Any]:
    """JSON Schema for a signature's output fields (via Pydantic)."""
    import pydantic

    definitions: dict[str, Any] = {}
    for name, field in _output_fields(signature).items():
        annotation = getattr(field, "annotation", Any)
        definitions[name] = (annotation, ...)
    model = pydantic.create_model(f"{getattr(signature, '__name__', 'Signature')}Outputs", **definitions)
    return model.model_json_schema()


if _dspy is not None:

    class BeaconJSONAdapter(_dspy.JSONAdapter):  # type: ignore[misc,name-defined]
        """``dspy.JSONAdapter`` with beacon's strict JSON extraction."""

        def parse(self, signature: Any, completion: str) -> dict[str, Any]:
            fields = _output_fields(signature)
            try:
                data = extract_json(completion, kind="object")
            except MalformedOutputError as exc:
                raise self._parse_error(signature, completion, str(exc)) from exc
            missing = [name for name in fields if name not in data]
            if missing:
                raise self._parse_error(
                    signature, completion, f"missing output fields: {', '.join(sorted(missing))}"
                )
            try:
                from dspy.adapters.utils import parse_value
            except ImportError:  # pragma: no cover - older/newer DSPy layout
                return {name: data[name] for name in fields}
            out = {}
            for name, field in fields.items():
                try:
                    out[name] = parse_value(data[name], field.annotation)
                except Exception as exc:  # DSPy raises various types here
                    raise self._parse_error(signature, completion, f"field {name!r}: {exc}") from exc
            return out

        def _parse_error(self, signature: Any, completion: str, message: str) -> Exception:
            try:
                from dspy.utils.exceptions import AdapterParseError

                return AdapterParseError(
                    adapter_name="BeaconJSONAdapter", signature=signature, lm_response=completion, message=message
                )
            except ImportError:  # pragma: no cover
                return ValueError(message)

else:  # pragma: no cover - exercised only without DSPy installed

    class BeaconJSONAdapter:  # type: ignore[no-redef]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise ImportError('BeaconJSONAdapter requires dspy: pip install "llm-beacon[dspy]"')


class BeaconValidateSchema:
    """Validate a prediction's output fields against a JSON Schema.

    Args:
        signature_or_schema: A DSPy Signature class (its output fields define
            the schema) or a JSON Schema mapping.

    Calling the validator returns the prediction unchanged, or raises
    :class:`~beacon.SchemaValidationError`.
    """

    def __init__(self, signature_or_schema: Any) -> None:
        if isinstance(signature_or_schema, Mapping):
            self.schema = dict(signature_or_schema)
            self.fields: Optional[list[str]] = list((self.schema.get("properties") or {}).keys())
        else:
            self.schema = signature_schema(signature_or_schema)
            self.fields = list(_output_fields(signature_or_schema).keys())

    def __call__(self, prediction: Any) -> Any:
        data = self._data(prediction)
        validate_schema(data, self.schema)
        return prediction

    forward = __call__

    def _data(self, prediction: Any) -> dict[str, Any]:
        if isinstance(prediction, Mapping):
            source: Mapping[str, Any] = prediction
        else:
            to_dict = getattr(prediction, "toDict", None)
            source = to_dict() if callable(to_dict) else vars(prediction)
        names = self.fields if self.fields else list(source.keys())
        data = {}
        for name in names:
            if name in source:
                value = source[name]
                dump = getattr(value, "model_dump", None)
                data[name] = dump(mode="json") if callable(dump) else value
        return data

