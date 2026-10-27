from __future__ import annotations

import pytest

from beacon import SchemaError, SchemaValidationError, schema_errors, validate_schema
from beacon.snapshots import assert_snapshot
from conftest import outcome

INTENT = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": ["cancel", "refund", "question"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["intent", "confidence"],
}


def msgs(instance: object, schema: dict) -> list[tuple[str, str, str]]:
    return [(e["path"], e["keyword"], e["message"]) for e in schema_errors(instance, schema)]


def test_valid_returns_none() -> None:
    assert validate_schema({"intent": "cancel", "confidence": 0.9}, INTENT) is None


def test_field_level_details() -> None:
    with pytest.raises(SchemaValidationError) as exc:
        validate_schema({"intent": "explode", "confidence": 1.5}, INTENT)
    assert exc.value.errors == [
        {"path": "/intent", "keyword": "enum", "message": '"explode" is not one of ["cancel", "refund", "question"]'},
        {"path": "/confidence", "keyword": "maximum", "message": "1.5 is greater than the maximum of 1"},
    ]
    assert str(exc.value) == (
        "2 schema violations:\n"
        '  - /intent: "explode" is not one of ["cancel", "refund", "question"]\n'
        "  - /confidence: 1.5 is greater than the maximum of 1"
    )
    assert exc.value.code == "schema.validation_failed"


@pytest.mark.parametrize(
    "instance,type_,ok",
    [
        ("42", "number", False),
        (42, "number", True),
        (4.2, "number", True),
        (True, "number", False),
        (True, "integer", False),
        (True, "boolean", True),
        (1.0, "integer", True),
        (1.5, "integer", False),
        (10**30, "integer", True),
        (None, "null", True),
        (0, "null", False),
        ([], "array", True),
        ((), "array", True),
        ({}, "object", True),
        ("", "string", True),
    ],
)
def test_types_are_strict(instance: object, type_: str, ok: bool) -> None:
    assert (schema_errors(instance, {"type": type_}) == []) is ok


def test_type_union() -> None:
    assert schema_errors(None, {"type": ["string", "null"]}) == []
    assert msgs(1, {"type": ["string", "null"]}) == [("", "type", 'expected one of types "string", "null", got "integer"')]


def test_type_failure_stops_further_checks_at_node() -> None:
    assert msgs("x", {"type": "integer", "minimum": 5, "enum": [1]}) == [("", "type", 'expected type "integer", got "string"')]


def test_required_and_additional_properties_order() -> None:
    schema = {
        "type": "object",
        "properties": {"a": {"type": "integer"}},
        "required": ["a", "b"],
        "additionalProperties": False,
    }
    assert msgs({"x": 1, "a": "s"}, schema) == [
        ("", "required", 'missing required property "b"'),
        ("", "additionalProperties", 'additional property "x" is not allowed'),
        ("/a", "type", 'expected type "integer", got "string"'),
    ]


def test_string_constraints() -> None:
    schema = {"type": "string", "minLength": 3, "maxLength": 5, "pattern": "^[a-z]+$"}
    assert schema_errors("abc", schema) == []
    assert [k for _, k, _ in msgs("AB", schema)] == ["minLength", "pattern"]
    assert msgs("日本語", {"minLength": 3}) == []  # code points, not bytes


def test_number_constraints() -> None:
    schema = {"exclusiveMinimum": 0, "exclusiveMaximum": 10, "multipleOf": 0.5}
    assert schema_errors(2.5, schema) == []
    assert [k for _, k, _ in msgs(0, schema)] == ["exclusiveMinimum"]
    assert [k for _, k, _ in msgs(10, schema)] == ["exclusiveMaximum"]
    assert [k for _, k, _ in msgs(0.3, schema)] == ["multipleOf"]


def test_multiple_of_uses_exact_decimals() -> None:
    assert schema_errors(0.3, {"multipleOf": 0.1}) == []
    assert schema_errors(19.99, {"multipleOf": 0.01}) == []
    assert schema_errors(10**30, {"multipleOf": 10}) == []


def test_array_constraints() -> None:
    schema = {"type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 3, "uniqueItems": True}
    assert schema_errors([1, 2], schema) == []
    assert msgs([1, 1, "x", 4], schema) == [
        ("", "maxItems", "array has 4 items, more than the maximum of 3"),
        ("", "uniqueItems", "array items 0 and 1 are equal"),
        ("/2", "type", 'expected type "integer", got "string"'),
    ]


def test_unique_items_uses_json_equality() -> None:
    assert [k for _, k, _ in msgs([1, 1.0], {"uniqueItems": True})] == ["uniqueItems"]
    assert [k for _, k, _ in msgs([{"a": 1, "b": 2}, {"b": 2, "a": 1}], {"uniqueItems": True})] == ["uniqueItems"]
    assert schema_errors([1, True], {"uniqueItems": True}) == []


def test_prefix_items_and_contains() -> None:
    schema = {"prefixItems": [{"type": "string"}, {"type": "integer"}], "items": False}
    assert schema_errors(["a", 1], schema) == []
    assert msgs(["a", 1, 2], schema) == [("", "items", "array has 3 items, but only 2 are allowed")]
    assert schema_errors([1, "x"], {"contains": {"type": "string"}}) == []
    assert msgs([1, 2], {"contains": {"type": "string"}}) == [("", "contains", "array has no item matching 'contains'")]


def test_enum_const_with_json_equality() -> None:
    assert schema_errors(1.0, {"enum": [1, 2]}) == []
    assert schema_errors({"b": 1, "a": 2}, {"const": {"a": 2, "b": 1}}) == []
    assert msgs(True, {"const": 1}) == [("", "const", "true is not equal to the constant 1")]


def test_refs_and_defs() -> None:
    schema = {
        "$defs": {"Pos": {"type": "integer", "minimum": 1}},
        "type": "object",
        "properties": {"a": {"$ref": "#/$defs/Pos"}, "b": {"$ref": "#/definitions/Neg"}},
        "definitions": {"Neg": {"type": "integer", "maximum": -1}},
    }
    assert msgs({"a": 0, "b": 0}, schema) == [
        ("/a", "minimum", "0 is less than the minimum of 1"),
        ("/b", "maximum", "0 is greater than the maximum of -1"),
    ]


def test_recursive_ref() -> None:
    tree = {
        "type": "object",
        "properties": {"value": {"type": "integer"}, "children": {"type": "array", "items": {"$ref": "#"}}},
        "required": ["value"],
    }
    assert schema_errors({"value": 1, "children": [{"value": 2, "children": [{"value": 3}]}]}, tree) == []
    assert msgs({"value": 1, "children": [{"children": []}]}, tree) == [("/children/0", "required", 'missing required property "value"')]


def test_optional_union_reports_the_intended_branch() -> None:
    schema = {"anyOf": [{"type": "object", "properties": {"n": {"type": "integer"}}}, {"type": "null"}]}
    assert msgs({"n": "x"}, schema) == [("/n", "type", 'expected type "integer", got "string"')]
    assert msgs("str", schema) == [("", "anyOf", "value does not match any of the 2 subschemas in anyOf")]


def test_one_of_and_not_and_all_of() -> None:
    one = {"oneOf": [{"type": "integer"}, {"type": "number"}]}
    assert msgs(1, one) == [("", "oneOf", "value matches more than one subschema in oneOf (indices 0 and 1)")]
    assert schema_errors(1.5, one) == []
    assert msgs("x", {"not": {"type": "string"}}) == [("", "not", "value must not match the 'not' schema")]
    assert [k for _, k, _ in msgs(5, {"allOf": [{"minimum": 6}, {"maximum": 4}]})] == ["minimum", "maximum"]


def test_if_then_else() -> None:
    schema = {
        "if": {"properties": {"kind": {"const": "card"}}},
        "then": {"required": ["number"]},
        "else": {"required": ["iban"]},
    }
    assert msgs({"kind": "card"}, schema) == [("", "required", 'missing required property "number"')]
    assert msgs({"kind": "bank"}, schema) == [("", "required", 'missing required property "iban"')]


def test_dependent_required_and_property_names() -> None:
    schema = {"dependentRequired": {"card": ["cvv"]}, "propertyNames": {"pattern": "^[a-z]+$"}}
    assert msgs({"card": 1, "Bad": 2}, schema) == [
        ("", "dependentRequired", 'property "card" requires property "cvv"'),
        ("", "propertyNames", 'property name "Bad" is invalid: string does not match the pattern "^[a-z]+$"'),
    ]


def test_dependent_schemas() -> None:
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "dependentSchemas": {"credit_card": {"required": ["billing_address"]}},
    }
    assert schema_errors({"name": "a"}, schema) == []
    assert schema_errors({"name": "a", "credit_card": "x", "billing_address": "y"}, schema) == []
    assert msgs({"name": "a", "credit_card": "x"}, schema) == [
        ("", "required", 'missing required property "billing_address"')
    ]


def test_unevaluated_properties() -> None:
    schema = {"type": "object", "properties": {"a": {"type": "integer"}}, "unevaluatedProperties": False}
    assert schema_errors({"a": 1}, schema) == []
    assert msgs({"a": 1, "b": 2}, schema) == [("", "unevaluatedProperties", 'unevaluated property "b" is not allowed')]
    # Sees through in-place applicators: "b" is evaluated by the allOf branch, so
    # only the genuinely unevaluated "c" is rejected.
    through = {
        "type": "object",
        "properties": {"a": {"type": "integer"}},
        "allOf": [{"properties": {"b": {"type": "integer"}}}],
        "unevaluatedProperties": False,
    }
    assert schema_errors({"a": 1, "b": 2}, through) == []
    assert [k for _, k, _ in msgs({"a": 1, "b": 2, "c": 3}, through)] == ["unevaluatedProperties"]
    # As a schema, it validates each leftover property.
    typed = {"type": "object", "properties": {"a": {"type": "integer"}}, "unevaluatedProperties": {"type": "string"}}
    assert schema_errors({"a": 1, "b": "ok"}, typed) == []
    assert msgs({"a": 1, "b": 2}, typed) == [("/b", "type", 'expected type "string", got "integer"')]


def test_pattern_properties() -> None:
    schema = {"patternProperties": {"^x-": {"type": "string"}}, "additionalProperties": False}
    assert schema_errors({"x-a": "ok"}, schema) == []
    assert [k for _, k, _ in msgs({"x-a": 1, "y": 1}, schema)] == ["type", "additionalProperties"]


def test_boolean_schemas() -> None:
    assert schema_errors(1, True) == []  # type: ignore[arg-type]
    assert msgs(1, False) == [("", "false", "no value is allowed here")]  # type: ignore[arg-type]


def test_json_pointer_escaping() -> None:
    schema = {"properties": {"a/b": {"type": "string"}, "c~d": {"type": "string"}}}
    assert [p for p, _, _ in msgs({"a/b": 1, "c~d": 2}, schema)] == ["/a~1b", "/c~0d"]


def test_annotations_are_ignored() -> None:
    schema = {"title": "T", "description": "d", "default": 1, "examples": [1], "format": "email", "$schema": "x", "$comment": "c"}
    assert schema_errors("not-an-email", schema) == []


@pytest.mark.parametrize(
    "schema,fragment",
    [
        ({"typo": 1}, 'unsupported schema keyword "typo"'),
        ({"minimum": "0"}, 'invalid value for "minimum"'),
        ({"type": "float"}, 'invalid value for "type"'),
        ({"pattern": "(?=x)"}, "invalid or unsupported regular expression"),
        ({"$ref": "#/missing"}, 'unresolvable $ref "#/missing"'),
        ({"$ref": "https://example.com/schema.json"}, "only local references"),
        ({"items": [{"type": "string"}]}, 'array form of "items"'),
        ({"required": "a"}, 'invalid value for "required"'),
        ({"anyOf": []}, 'invalid value for "anyOf"'),
        ({"multipleOf": 0}, 'invalid value for "multipleOf"'),
        ({"unevaluatedItems": False}, "unsupported schema keyword"),
        ({"$ref": "#"}, "validation depth limit"),
        ("not a schema", "must be an object or a boolean"),
    ],
)
def test_schema_errors(schema: object, fragment: str) -> None:
    with pytest.raises(SchemaError) as exc:
        validate_schema(1, schema)  # type: ignore[arg-type]
    assert fragment in str(exc.value)


def test_bad_schema_fails_regardless_of_instance() -> None:
    schema = {"properties": {"a": {"minimum": "zero"}}}
    for instance in (1, {}, {"a": 1}, "x"):
        with pytest.raises(SchemaError):
            validate_schema(instance, schema)


def test_unsupported_instance_types() -> None:
    with pytest.raises(TypeError, match="unsupported type 'set' at '/a'"):
        validate_schema({"a": {1}}, {})
    with pytest.raises(TypeError, match="dict keys must be str"):
        validate_schema({1: 2}, {})


def test_pydantic_generated_schema() -> None:
    pydantic = pytest.importorskip("pydantic")
    from typing import Literal, Optional

    class Address(pydantic.BaseModel):
        city: str
        zip_code: str = pydantic.Field(pattern=r"^\d{5}$")

    class User(pydantic.BaseModel):
        name: str = pydantic.Field(min_length=1)
        age: int = pydantic.Field(ge=0)
        role: Literal["admin", "user"] = "user"
        address: Optional[Address] = None
        tags: list[str] = []

    schema = User.model_json_schema()
    assert schema_errors({"name": "A", "age": 3, "address": {"city": "X", "zip_code": "12345"}}, schema) == []
    assert msgs({"name": "", "age": -1, "role": "root", "address": {"city": "X", "zip_code": "abc"}}, schema) == [
        ("/name", "minLength", "string has 0 characters, fewer than the minimum of 1"),
        ("/age", "minimum", "-1 is less than the minimum of 0"),
        ("/role", "enum", '"root" is not one of ["admin", "user"]'),
        ("/address/zip_code", "pattern", 'string does not match the pattern "^\\\\d{5}$"'),
    ]


CORPUS = {
    "intent_valid": ({"intent": "cancel", "confidence": 0.9}, INTENT),
    "intent_invalid": ({"intent": "explode", "confidence": 1.5}, INTENT),
    "intent_missing_fields": ({}, INTENT),
    "intent_wrong_types": ({"intent": 1, "confidence": "high"}, INTENT),
    "nested_array_errors": (
        {"items": [{"sku": "A1", "qty": 0}, {"sku": 5, "qty": 2}]},
        {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"sku": {"type": "string"}, "qty": {"type": "integer", "minimum": 1}},
                        "required": ["sku", "qty"],
                    },
                }
            },
        },
    ),
    "strict_object": ({"a": 1, "extra": True}, {"type": "object", "properties": {"a": {}}, "additionalProperties": False}),
    "string_limits": ("toolongvalue", {"type": "string", "maxLength": 5, "pattern": "^[0-9]+$"}),
    "optional_nested": ({"user": {"age": "x"}}, {"properties": {"user": {"anyOf": [{"$ref": "#/$defs/U"}, {"type": "null"}]}}, "$defs": {"U": {"properties": {"age": {"type": "integer"}}}}}),
    "one_of_ambiguous": (3, {"oneOf": [{"minimum": 0}, {"maximum": 10}]}),
    "unsupported_keyword": (1, {"nullable": True}),
    "dependent_schemas": (
        {"credit_card": "4111"},
        {"type": "object", "dependentSchemas": {"credit_card": {"required": ["billing_address"]}}},
    ),
    "unevaluated_properties": (
        {"a": 1, "b": 2, "c": 3},
        {
            "type": "object",
            "properties": {"a": {"type": "integer"}},
            "allOf": [{"properties": {"b": {"type": "integer"}}}],
            "unevaluatedProperties": False,
        },
    ),
}


@pytest.mark.parametrize("case", sorted(CORPUS))
def test_snapshot_corpus(case: str) -> None:
    instance, schema = CORPUS[case]
    assert_snapshot(f"validate_schema/{case}", outcome(schema_errors, instance, schema), input={"instance": instance, "schema": schema})
