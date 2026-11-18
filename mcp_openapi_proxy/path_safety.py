"""Fail-closed OpenAPI path argument validation and URL containment."""

import re
from urllib.parse import quote, unquote, urlsplit, urlunsplit


def _safe_segment(value):
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise ValueError("Invalid path parameter")
    value = str(value)
    if not value or len(value) > 4096 or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError("Invalid path parameter")
    decoded = value
    for _ in range(8):
        expanded = unquote(decoded)
        if expanded == decoded:
            break
        decoded = expanded
    if "%" in decoded or decoded in (".", "..") or any(ord(c) < 32 or ord(c) == 127 or c in ("/", "\\", "?", "#") for c in decoded):
        raise ValueError("Unsafe path parameter")
    # Encode the fully-decoded safe value; encoding the original input would
    # double-encode harmless percent-encoded unreserved characters.
    return quote(decoded, safe="")


def safe_path(template, parameters):
    """Encode only path parameters; never treat them as URL syntax."""
    if not isinstance(template, str) or not template.startswith("/") or not isinstance(parameters, dict):
        raise ValueError("Invalid operation route")
    # Reject ambiguous literal templates too: no dot segments or encoded routing syntax.
    for segment in template.split("/"):
        if not segment:
            continue
        if segment.startswith("{") and segment.endswith("}") and segment.count("{") == 1:
            continue
        if "%" in segment:
            raise ValueError("Encoded literal operation route")
        _safe_segment(segment)  # validation only, preserve the spec's literal segment
    used = []
    def replace(match):
        name = match.group(1)
        if name not in parameters:
            raise ValueError("Missing path parameter")
        used.append(name)
        return _safe_segment(parameters[name])
    result = re.sub(r"\{([^{}]+)\}", replace, template)
    if "{" in result or "}" in result:
        raise ValueError("Unresolved path parameter")
    return result, used


def _resolve_local_ref(reference, spec):
    """Resolve an in-document JSON Pointer without fetching external refs."""
    if not isinstance(reference, str) or not reference.startswith("#/"):
        raise ValueError("External or invalid OpenAPI reference")
    current = spec
    decoded_pointer = unquote(reference[2:])
    for raw_token in decoded_pointer.split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdecimal():
            index = int(token)
            if index >= len(current):
                raise ValueError("OpenAPI reference index out of range")
            current = current[index]
        else:
            raise ValueError("Unresolved OpenAPI reference")
    return current


def _resolve_ref_chain(value, spec):
    """Resolve bounded local Reference Object chains; reject cycles/siblings."""
    seen = set()
    for _ in range(16):
        if not isinstance(value, dict):
            raise ValueError("Invalid OpenAPI reference target")
        if "$ref" not in value:
            return value
        if set(value) - {"$ref", "summary", "description"}:
            raise ValueError("Ambiguous OpenAPI reference siblings")
        reference = value["$ref"]
        if reference in seen:
            raise ValueError("Cyclic OpenAPI reference")
        seen.add(reference)
        value = _resolve_local_ref(reference, spec)
    raise ValueError("OpenAPI reference depth exceeded")


def _simple_pattern_matches(pattern, value):
    """Match a restricted character-class grammar without regex backtracking."""
    match = re.fullmatch(
        r"^\^\[([A-Za-z0-9_-]{1,64})\](\+|\*|\?|\{[0-9]{1,3}(?:,[0-9]{1,3})?\})?\$$",
        pattern,
    )
    if match is None:
        raise ValueError("Unsupported path pattern")
    characters, quantifier = match.groups()
    ranges = []
    index = 0
    while index < len(characters):
        if index + 2 < len(characters) and characters[index + 1] == "-":
            first, last = ord(characters[index]), ord(characters[index + 2])
            if first > last:
                raise ValueError("Invalid path character range")
            ranges.append((first, last))
            index += 3
        else:
            codepoint = ord(characters[index])
            ranges.append((codepoint, codepoint))
            index += 1
    minimum, maximum = 1, 1
    if quantifier == "+":
        minimum, maximum = 1, None
    elif quantifier == "*":
        minimum, maximum = 0, None
    elif quantifier == "?":
        minimum, maximum = 0, 1
    elif quantifier:
        bounds = quantifier[1:-1].split(",")
        minimum = int(bounds[0])
        maximum = int(bounds[1]) if len(bounds) == 2 else minimum
        if maximum < minimum:
            raise ValueError("Invalid path pattern bounds")
    if len(value) < minimum or (maximum is not None and len(value) > maximum):
        return False
    return all(
        any(low <= ord(character) <= high for low, high in ranges)
        for character in value
    )


def resolve_parameter_reference(declaration, spec):
    """Resolve and validate a Parameter Object using local spec data only."""
    if not isinstance(declaration, dict):
        raise ValueError("Invalid path parameter declaration")
    if "$ref" in declaration:
        declaration = _resolve_ref_chain(declaration, spec)
    if (not isinstance(declaration, dict)
            or not isinstance(declaration.get("name"), str)
            or not declaration["name"]
            or declaration.get("in") not in (
                "path", "query", "header", "cookie", "body", "formData"
            )):
        raise ValueError("Invalid resolved OpenAPI parameter")
    return declaration


def resolve_parameter_schema(parameter, spec):
    """Return a scalar schema, supporting OpenAPI 2 and local OpenAPI 3 refs."""
    schema = parameter.get("schema")
    if schema is None:
        schema = {
            key: parameter[key]
            for key in (
                "type", "format", "enum", "const", "pattern",
                "minLength", "maxLength", "minimum", "maximum",
                "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
            )
            if key in parameter
        }
    if not isinstance(schema, dict):
        raise ValueError("Invalid path schema")
    if "$ref" in schema:
        return _resolve_ref_chain(schema, spec)
    return schema


def _json_scalar_equal(value, choice):
    # JSON has one numeric domain; booleans are distinct from numbers.
    if type(value) in (int, float) and type(choice) in (int, float):
        return value == choice
    return type(value) is type(choice) and value == choice


def validate_path_arguments(template, parameters, operation, path_item=None, spec=None):
    """Enforce scalar path-schema contracts before URL encoding or HTTP dispatch.

    Operation-level parameter declarations override path-item declarations.
    Unsupported complex schemas fail closed rather than silently bypassing an
    OpenAPI contract. Query/body arguments are left unchanged.
    """
    import math
    from decimal import Decimal, InvalidOperation
    from uuid import UUID
    from datetime import date, datetime

    if not isinstance(template, str) or not isinstance(parameters, dict):
        raise ValueError("Invalid path arguments")
    names = set(re.findall(r"\{([^{}]+)\}", template))
    contracts = {}
    for container in (path_item, operation):
        if not isinstance(container, dict):
            continue
        declarations = container.get("parameters", [])
        if not isinstance(declarations, list):
            raise ValueError("Invalid path schema")
        for declaration in declarations:
            declaration = resolve_parameter_reference(declaration, spec)
            if declaration.get("in") == "path" and declaration.get("name") in names:
                # Only the default simple scalar path serialization is
                # implemented. Matrix/label/exploded/content parameters need
                # an explicit reviewed serializer before they can be enabled.
                if (declaration.get("style", "simple") != "simple"
                        or declaration.get("explode", False) is True
                        or declaration.get("allowReserved", False) is True
                        or declaration.get("content")):
                    raise ValueError("Unsupported path parameter serialization")
                schema = resolve_parameter_schema(declaration, spec)
                contracts[declaration["name"]] = schema
    validated = dict(parameters)
    for name in names:
        if name not in validated:
            raise ValueError("Missing path parameter")
        value = validated[name]
        schema = contracts.get(name, {})
        if any(key in schema for key in (
                "$ref", "$dynamicRef", "oneOf", "anyOf", "allOf", "not",
                "items", "additionalItems", "properties", "patternProperties",
                "additionalProperties", "contains", "minContains", "maxContains",
                "if", "then", "else", "dependentSchemas", "dependentRequired",
                "dependencies", "propertyNames", "required", "minItems", "maxItems",
                "uniqueItems", "minProperties", "maxProperties",
                "unevaluatedProperties", "unevaluatedItems", "prefixItems",
                "contentSchema")):
            # Unresolved and computationally unbounded schemas must not be
            # treated as authorization to accept arbitrary path values.
            raise ValueError("Unsupported path schema")
        declared_type = schema.get("type")
        if (declared_type == "integer" and type(value) is float
                and math.isfinite(value) and value.is_integer()):
            value = validated[name] = int(value)
        if declared_type is not None:
            supported = {
                "string": type(value) is str,
                "integer": type(value) is int,
                "number": type(value) in (int, float) and
                          (type(value) is int or math.isfinite(value)),
                "boolean": type(value) is bool,
            }
            if declared_type not in supported or not supported[declared_type]:
                raise ValueError("Path parameter violates schema type")
        if "enum" in schema:
            options = schema["enum"]
            if not isinstance(options, list) or not any(
                    _json_scalar_equal(value, choice)
                    for choice in options):
                raise ValueError("Path parameter violates enum")
        if "const" in schema and not _json_scalar_equal(value, schema["const"]):
            raise ValueError("Path parameter violates const")
        if "pattern" in schema:
            pattern = schema["pattern"]
            if type(value) is not str or not isinstance(pattern, str) or len(pattern) > 96:
                raise ValueError("Invalid path pattern")
            if not _simple_pattern_matches(pattern, value):
                raise ValueError("Path parameter violates pattern")
        if "format" in schema:
            fmt = schema["format"]
            if not isinstance(fmt, str):
                raise ValueError("Invalid path format")
            if fmt == "uuid":
                if type(value) is not str:
                    raise ValueError("Invalid path UUID")
                try:
                    parsed = UUID(value)
                except (ValueError, AttributeError):
                    raise ValueError("Invalid path UUID") from None
                if len(value) != 36 or str(parsed) != value.lower():
                    raise ValueError("Noncanonical path UUID")
            elif fmt == "date":
                if type(value) is not str:
                    raise ValueError("Invalid path date")
                try:
                    if date.fromisoformat(value).isoformat() != value:
                        raise ValueError("Invalid path date")
                except ValueError:
                    raise ValueError("Invalid path date") from None
            elif fmt == "date-time":
                if type(value) is not str:
                    raise ValueError("Invalid path date-time")
                try:
                    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    if parsed.tzinfo is None:
                        raise ValueError("Timezone required")
                except ValueError:
                    raise ValueError("Invalid path date-time") from None
            elif fmt in ("int32", "int64"):
                if type(value) is not int:
                    raise ValueError("Invalid integer path format")
                limit = (1 << (31 if fmt == "int32" else 63))
                if not -limit <= value < limit:
                    raise ValueError("Integer format out of bounds")
            elif fmt in ("float", "double"):
                if type(value) not in (float, int):
                    raise ValueError("Invalid floating-point format")
                if type(value) is float and not math.isfinite(value):
                    raise ValueError("Invalid floating-point format")
            # OpenAPI format is an annotation. Unknown format names are
            # permitted; generic scalar/path-component checks still apply.

        if "multipleOf" in schema:
            divisor = schema["multipleOf"]
            if type(value) not in (int, float) or type(divisor) not in (int, float):
                raise ValueError("Invalid multipleOf")
            try:
                v = Decimal(str(value))
                d = Decimal(str(divisor))
                if not (v.is_finite() and d.is_finite()) or d <= 0 or v % d != 0:
                    raise ValueError("Path parameter violates multipleOf")
            except (InvalidOperation, ZeroDivisionError):
                raise ValueError("Invalid multipleOf") from None
        for key in ("minLength", "maxLength"):
            if key in schema:
                bound = schema[key]
                if (type(value) is not str or type(bound) is not int
                        or bound < 0 or (len(value) < bound if key == "minLength"
                                         else len(value) > bound)):
                    raise ValueError("Path parameter violates length")
        numeric_bounds = [
            ("minimum", lambda x, b: x < b),
            ("maximum", lambda x, b: x > b),
        ]
        legacy_bounds = isinstance(spec, dict) and (
            spec.get("swagger") == "2.0"
            or str(spec.get("openapi", "")).startswith("3.0."))
        for exclusive, inclusive, compare in (
                ("exclusiveMinimum", "minimum", lambda x, b: x <= b),
                ("exclusiveMaximum", "maximum", lambda x, b: x >= b)):
            if exclusive not in schema:
                continue
            if legacy_bounds:
                flag = schema[exclusive]
                if type(flag) is not bool:
                    raise ValueError("Invalid exclusive numeric bound")
                if flag and inclusive in schema:
                    numeric_bounds.append((inclusive, compare))
            else:
                numeric_bounds.append((exclusive, compare))
        if any(key in schema for key, _ in numeric_bounds):
            if type(value) not in (int, float) or (
                    type(value) is float and not math.isfinite(value)):
                raise ValueError("Path parameter violates numeric bounds")
            for key, compare in numeric_bounds:
                if key in schema:
                    boundary = schema[key]
                    if (type(boundary) not in (int, float) or
                            (type(boundary) is float and not math.isfinite(boundary)) or
                            compare(value, boundary)):
                        raise ValueError("Path parameter violates numeric bounds")
        if type(value) is bool:
            validated[name] = "true" if value else "false"
    return validated


def safe_url(base_url, template, parameters):
    if not isinstance(base_url, str):
        raise ValueError("Invalid base URL")
    base = urlsplit(base_url)
    try:
        _ = base.port
    except ValueError:
        raise ValueError("Invalid base URL") from None
    if (base.scheme not in ("http", "https") or not base.hostname or
            base.username is not None or base.password is not None or
            base.query or base.fragment or any(c.isspace() for c in base_url)):
        raise ValueError("Invalid base URL")
    if any(segment in (".", "..") or "%" in segment for segment in base.path.split("/")):
        raise ValueError("Ambiguous base path")
    path, used = safe_path(template, parameters)
    final_path = base.path.rstrip("/") + "/" + path.lstrip("/")
    url = urlunsplit((base.scheme, base.netloc, final_path, "", ""))
    final = urlsplit(url)
    if final.netloc != base.netloc or final.path != final_path or final.query or final.fragment:
        raise ValueError("Operation escaped origin or base path")
    return url, used
