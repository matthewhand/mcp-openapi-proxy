"""Numeric path contracts across the supported OpenAPI dialects."""
import pytest

from mcp_openapi_proxy.path_safety import safe_url, validate_path_arguments


def check(schema, value, version="3.1.0"):
    declaration = {"name": "id", "in": "path", "required": True}
    if version == "2.0":
        declaration.update(schema)
        spec = {"swagger": "2.0"}
    else:
        declaration["schema"] = schema
        spec = {"openapi": version}
    operation = {"parameters": [declaration]}
    return validate_path_arguments("/items/{id}", {"id": value}, operation, spec=spec)


@pytest.mark.parametrize("version", ["2.0", "3.0.3"])
@pytest.mark.parametrize("exclusive", [False, True])
@pytest.mark.parametrize("value", [-1, 0, 1, 2, 3])
def test_legacy_boolean_exclusive_bounds(version, exclusive, value):
    schema = {"type": "integer", "minimum": 0, "maximum": 2,
              "exclusiveMinimum": exclusive, "exclusiveMaximum": exclusive}
    valid = 0 < value < 2 if exclusive else 0 <= value <= 2
    if valid:
        assert check(schema, value, version)["id"] == value
    else:
        with pytest.raises(ValueError):
            check(schema, value, version)


@pytest.mark.parametrize("value,valid", [(0.5, False), (1, True), (2, True), (2.5, False)])
def test_modern_numeric_exclusive_bounds(value, valid):
    schema = {"type": "number", "exclusiveMinimum": 0.5, "exclusiveMaximum": 2.5}
    if valid:
        assert check(schema, value)["id"] == value
    else:
        with pytest.raises(ValueError):
            check(schema, value)


@pytest.mark.parametrize("keyword", ["enum", "const"])
@pytest.mark.parametrize("choice,value", [(1, 1.0), (1.0, 1)])
def test_numeric_enum_and_const_use_json_number_equality(keyword, choice, value):
    schema = {"type": "number", keyword: [choice] if keyword == "enum" else choice}
    assert check(schema, value)["id"] == value


@pytest.mark.parametrize("keyword", ["enum", "const"])
@pytest.mark.parametrize("choice,value,kind", [(True, 1, "number"), (1, True, "boolean")])
def test_boolean_is_distinct_from_json_numbers(keyword, choice, value, kind):
    with pytest.raises(ValueError):
        check({"type": kind, keyword: [choice] if keyword == "enum" else choice}, value)


@pytest.mark.parametrize("fmt", [None, "int32", "int64"])
def test_integral_float_is_integer_and_uses_canonical_path(fmt):
    schema = {"type": "integer", "enum": [1.0]}
    if fmt:
        schema["format"] = fmt
    result = check(schema, 1.0)
    assert type(result["id"]) is int
    assert safe_url("https://synthetic.invalid", "/items/{id}", result)[0].endswith("/items/1")


@pytest.mark.parametrize("value", [True, 1.5, float("inf"), float("nan"), "1"])
def test_integer_rejects_nonintegral_or_non_numeric_values(value):
    with pytest.raises(ValueError):
        check({"type": "integer"}, value)


def test_modern_boolean_exclusive_bound_is_invalid():
    with pytest.raises(ValueError):
        check({"type": "integer", "minimum": 0, "exclusiveMinimum": False}, 1)
