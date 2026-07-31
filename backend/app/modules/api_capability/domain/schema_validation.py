from __future__ import annotations

from typing import Any

from app.shared.exceptions import NonRetryableExecutionError


SYSTEM_OWNED_FIELDS = frozenset(
    {
        "authorization",
        "cookie",
        "default_team_id",
        "external_user_id",
        "graphql_document",
        "headers",
        "host",
        "origin",
        "password",
        "path",
        "team_id",
        "token",
        "user_id",
    }
)
SUPPORTED_TYPES = frozenset({"object", "array", "string", "integer", "number", "boolean"})
COMMON_KEYS = frozenset({"type", "title", "description", "default"})
TYPE_KEYS = {
    "object": frozenset({"properties", "required", "additionalProperties"}),
    "array": frozenset({"items", "minItems", "maxItems"}),
    "string": frozenset({"enum", "minLength", "maxLength"}),
    "integer": frozenset({"enum", "minimum", "maximum"}),
    "number": frozenset({"enum", "minimum", "maximum"}),
    "boolean": frozenset({"enum"}),
}


def validate_public_schema(
    schema: dict[str, Any],
    *,
    label: str,
    reject_system_fields: bool = True,
) -> dict[str, Any]:
    if not isinstance(schema, dict):
        raise _schema_error(label, "must be an object")
    normalized = _validate_schema_node(
        schema,
        path=label,
        depth=0,
        reject_system_fields=reject_system_fields,
    )
    if normalized.get("type") != "object":
        raise _schema_error(label, "root type must be object")
    return normalized


def validate_schema_instance(
    schema: dict[str, Any],
    value: Any,
    *,
    label: str,
) -> None:
    _validate_instance(schema, value, path=label)


def _validate_schema_node(
    schema: dict[str, Any],
    *,
    path: str,
    depth: int,
    reject_system_fields: bool,
) -> dict[str, Any]:
    if depth > 8:
        raise _schema_error(path, "schema nesting exceeds 8 levels")
    schema_type = schema.get("type")
    if schema_type not in SUPPORTED_TYPES:
        raise _schema_error(path, "contains an unsupported type")
    allowed = COMMON_KEYS | TYPE_KEYS[str(schema_type)]
    unknown = set(schema) - allowed
    if unknown:
        raise _schema_error(path, f"contains unknown fields: {sorted(unknown)}")
    normalized: dict[str, Any] = {"type": schema_type}
    for key in ("title", "description"):
        if key in schema:
            text = str(schema[key])
            if len(text) > 1000:
                raise _schema_error(path, f"{key} is too long")
            normalized[key] = text
    if schema_type == "object":
        properties = schema.get("properties")
        required = schema.get("required")
        if not isinstance(properties, dict) or len(properties) > 100:
            raise _schema_error(path, "properties must be an object with at most 100 fields")
        if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
            raise _schema_error(path, "required must be an array of field names")
        if len(required) != len(set(required)) or not set(required) <= set(properties):
            raise _schema_error(path, "required must uniquely reference properties")
        if schema.get("additionalProperties") is not False:
            raise _schema_error(path, "additionalProperties must be false")
        normalized_properties: dict[str, Any] = {}
        for field_name, child in properties.items():
            if not isinstance(field_name, str) or not field_name:
                raise _schema_error(path, "property name is invalid")
            if reject_system_fields and field_name.strip().lower() in SYSTEM_OWNED_FIELDS:
                raise _schema_error(
                    f"{path}.{field_name}",
                    "is owned by System Context and cannot be public",
                )
            if not isinstance(child, dict):
                raise _schema_error(f"{path}.{field_name}", "must be an object")
            normalized_properties[field_name] = _validate_schema_node(
                child,
                path=f"{path}.{field_name}",
                depth=depth + 1,
                reject_system_fields=reject_system_fields,
            )
        normalized.update(
            {
                "properties": normalized_properties,
                "required": list(required),
                "additionalProperties": False,
            }
        )
    elif schema_type == "array":
        items = schema.get("items")
        if not isinstance(items, dict):
            raise _schema_error(path, "items must be an object")
        minimum = _bounded_schema_int(
            schema.get("minItems", 0),
            path,
            "minItems",
            0,
            1000,
        )
        maximum = _bounded_schema_int(
            schema.get("maxItems", 100),
            path,
            "maxItems",
            0,
            1000,
        )
        if minimum > maximum:
            raise _schema_error(path, "minItems cannot exceed maxItems")
        normalized.update(
            {
                "items": _validate_schema_node(
                    items,
                    path=f"{path}[]",
                    depth=depth + 1,
                    reject_system_fields=reject_system_fields,
                ),
                "minItems": minimum,
                "maxItems": maximum,
            }
        )
    elif schema_type == "string":
        minimum = _bounded_schema_int(
            schema.get("minLength", 0),
            path,
            "minLength",
            0,
            100000,
        )
        maximum = _bounded_schema_int(
            schema.get("maxLength", 10000),
            path,
            "maxLength",
            0,
            100000,
        )
        if minimum > maximum:
            raise _schema_error(path, "minLength cannot exceed maxLength")
        normalized.update({"minLength": minimum, "maxLength": maximum})
        _normalize_enum(schema, normalized, path, str)
    elif schema_type in {"integer", "number"}:
        numeric_minimum = schema.get("minimum")
        numeric_maximum = schema.get("maximum")
        for key, item in (
            ("minimum", numeric_minimum),
            ("maximum", numeric_maximum),
        ):
            if item is not None and (isinstance(item, bool) or not isinstance(item, (int, float))):
                raise _schema_error(path, f"{key} must be numeric")
            if item is not None:
                normalized[key] = item
        if (
            numeric_minimum is not None
            and numeric_maximum is not None
            and numeric_minimum > numeric_maximum
        ):
            raise _schema_error(path, "minimum cannot exceed maximum")
        expected = int if schema_type == "integer" else (int, float)
        _normalize_enum(schema, normalized, path, expected)
    elif schema_type == "boolean":
        _normalize_enum(schema, normalized, path, bool)
    if "default" in schema:
        try:
            _validate_instance(normalized, schema["default"], path=f"{path}.default")
        except NonRetryableExecutionError as exc:
            raise _schema_error(path, f"default is invalid: {exc}") from None
        normalized["default"] = schema["default"]
    return normalized


def _normalize_enum(
    schema: dict[str, Any],
    normalized: dict[str, Any],
    path: str,
    expected_type: type[Any] | tuple[type[Any], ...],
) -> None:
    if "enum" not in schema:
        return
    values = schema["enum"]
    if not isinstance(values, list) or not values or len(values) > 100:
        raise _schema_error(path, "enum must contain 1 to 100 values")
    if any(
        isinstance(value, bool)
        and expected_type is not bool
        or not isinstance(value, expected_type)
        for value in values
    ):
        raise _schema_error(path, "enum value type does not match schema type")
    if len({repr(value) for value in values}) != len(values):
        raise _schema_error(path, "enum values must be unique")
    normalized["enum"] = list(values)


def _validate_instance(
    schema: dict[str, Any],
    value: Any,
    *,
    path: str,
) -> None:
    schema_type = schema["type"]
    if schema_type == "object":
        if not isinstance(value, dict):
            raise _instance_error(path, "must be an object")
        properties = schema["properties"]
        unknown = set(value) - set(properties)
        if unknown:
            raise _instance_error(path, f"contains unknown fields: {sorted(unknown)}")
        missing = set(schema["required"]) - set(value)
        if missing:
            raise _instance_error(path, f"is missing fields: {sorted(missing)}")
        for key, item in value.items():
            _validate_instance(properties[key], item, path=f"{path}.{key}")
        return
    if schema_type == "array":
        if not isinstance(value, list):
            raise _instance_error(path, "must be an array")
        if len(value) < schema["minItems"] or len(value) > schema["maxItems"]:
            raise _instance_error(path, "array length is out of range")
        for index, item in enumerate(value):
            _validate_instance(schema["items"], item, path=f"{path}[{index}]")
        return
    valid = {
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
    }[str(schema_type)]
    if not valid:
        raise _instance_error(path, f"must be {schema_type}")
    if "enum" in schema and value not in schema["enum"]:
        raise _instance_error(path, "is not an allowed enum value")
    if schema_type == "string" and (
        len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", 10000)
    ):
        raise _instance_error(path, "string length is out of range")
    if schema_type in {"integer", "number"}:
        if "minimum" in schema and value < schema["minimum"]:
            raise _instance_error(path, "is below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise _instance_error(path, "is above maximum")


def _bounded_schema_int(
    value: Any,
    path: str,
    field_name: str,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _schema_error(path, f"{field_name} must be an integer")
    if value < minimum or value > maximum:
        raise _schema_error(path, f"{field_name} is out of range")
    return value


def _schema_error(path: str, reason: str) -> NonRetryableExecutionError:
    return NonRetryableExecutionError(
        f"Invalid public schema at {path}: {reason}",
        safe_message="Capability 公开 Schema 配置无效",
        error_code="capability_schema_invalid",
        field_errors=[{"field": path, "message": f"{path} 配置无效"}],
    )


def _instance_error(path: str, reason: str) -> NonRetryableExecutionError:
    return NonRetryableExecutionError(
        f"Schema validation failed at {path}: {reason}",
        safe_message="Capability 输入或输出不符合公开 Schema",
        error_code="capability_schema_validation_failed",
        field_errors=[{"field": path, "message": f"{path} 字段值无效"}],
    )
