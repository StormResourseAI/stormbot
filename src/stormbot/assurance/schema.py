"""A small, dependency-free JSON Schema validator.

Only the keyword subset the assurance registries actually use is implemented.
That is a deliberate trade: the registries are validated in CI on every push, so
the validator has to be present and hermetic, and pulling a general-purpose
schema library into a zero-dependency package to check four documents is a worse
trade than owning ~240 lines.

Unsupported keywords are rejected loudly at load time rather than ignored
silently — a schema author who writes ``anyOf`` here should get an error, not a
document that quietly validates against nothing.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

__all__ = ["SchemaError", "UnsupportedSchemaKeyword", "validate"]

_SUPPORTED_KEYWORDS = frozenset(
    {
        "$schema",
        "$id",
        "$ref",
        "$defs",
        "title",
        "description",
        "type",
        "properties",
        "required",
        "additionalProperties",
        "enum",
        "const",
        "pattern",
        "format",
        "items",
        "minItems",
        "uniqueItems",
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
        "examples",
    }
)

_TYPE_MAP: Mapping[str, tuple[type, ...]] = {
    "object": (dict,),
    "array": (list,),
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "null": (type(None),),
}


class UnsupportedSchemaKeyword(Exception):
    """Raised when a schema uses a keyword this validator does not implement."""


@dataclass(frozen=True)
class SchemaError:
    """One validation failure, located by JSON pointer-ish path."""

    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path or '<root>'}: {self.message}"


def validate(instance: Any, schema: Mapping[str, Any]) -> list[SchemaError]:
    """Return every validation error. An empty list means the document is valid.

    All errors are collected rather than raising on the first one, because a
    registry author fixing one field at a time across four documents is a bad
    use of a CI cycle.
    """
    _assert_supported(schema, root=schema)
    errors: list[SchemaError] = []
    _validate(instance, schema, schema, "", errors)
    return errors


# --------------------------------------------------------------------- internals


def _assert_supported(schema: Any, *, root: Mapping[str, Any], path: str = "") -> None:
    if isinstance(schema, dict):
        unknown = set(schema) - _SUPPORTED_KEYWORDS
        if unknown:
            raise UnsupportedSchemaKeyword(
                f"{path or '<root>'}: unsupported schema keyword(s): {sorted(unknown)}"
            )
        for key in ("properties", "$defs"):
            for name, sub in schema.get(key, {}).items():
                _assert_supported(sub, root=root, path=f"{path}/{key}/{name}")
        if "items" in schema:
            _assert_supported(schema["items"], root=root, path=f"{path}/items")


def _resolve(schema: Mapping[str, Any], root: Mapping[str, Any]) -> Mapping[str, Any]:
    ref = schema.get("$ref")
    if not ref:
        return schema
    if not ref.startswith("#/"):
        raise UnsupportedSchemaKeyword(f"only local $ref is supported, got {ref!r}")
    node: Any = root
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def _validate(
    instance: Any,
    schema: Mapping[str, Any],
    root: Mapping[str, Any],
    path: str,
    errors: list[SchemaError],
) -> None:
    schema = _resolve(schema, root)

    expected_type = schema.get("type")
    if expected_type and not _type_matches(instance, expected_type):
        errors.append(SchemaError(path, f"expected type {expected_type}, got {type(instance).__name__}"))
        return

    if "const" in schema and instance != schema["const"]:
        errors.append(SchemaError(path, f"must equal {schema['const']!r}"))

    if "enum" in schema and instance not in schema["enum"]:
        errors.append(SchemaError(path, f"must be one of {schema['enum']}"))

    if isinstance(instance, str):
        _validate_string(instance, schema, path, errors)
    elif isinstance(instance, bool):
        pass  # bool is an int subclass; no numeric bounds apply
    elif isinstance(instance, (int, float)):
        _validate_number(instance, schema, path, errors)
    elif isinstance(instance, list):
        _validate_array(instance, schema, root, path, errors)
    elif isinstance(instance, dict):
        _validate_object(instance, schema, root, path, errors)


def _type_matches(instance: Any, expected: str | Sequence[str]) -> bool:
    names = [expected] if isinstance(expected, str) else list(expected)
    for name in names:
        allowed = _TYPE_MAP.get(name)
        if allowed is None:
            raise UnsupportedSchemaKeyword(f"unsupported type {name!r}")
        if name in ("integer", "number") and isinstance(instance, bool):
            continue
        if isinstance(instance, allowed):
            return True
    return False


def _validate_string(instance: str, schema: Mapping[str, Any], path: str, errors: list[SchemaError]) -> None:
    if "minLength" in schema and len(instance) < schema["minLength"]:
        errors.append(SchemaError(path, f"shorter than minLength {schema['minLength']}"))
    if "maxLength" in schema and len(instance) > schema["maxLength"]:
        errors.append(SchemaError(path, f"longer than maxLength {schema['maxLength']}"))
    if "pattern" in schema and not re.search(schema["pattern"], instance):
        errors.append(SchemaError(path, f"does not match pattern {schema['pattern']!r}"))
    fmt = schema.get("format")
    if fmt and not _format_ok(instance, fmt):
        errors.append(SchemaError(path, f"is not a valid {fmt}"))


def _format_ok(value: str, fmt: str) -> bool:
    if fmt == "date":
        try:
            date.fromisoformat(value)
        except ValueError:
            return False
        return True
    if fmt == "date-time":
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
        return True
    raise UnsupportedSchemaKeyword(f"unsupported format {fmt!r}")


def _validate_number(
    instance: float, schema: Mapping[str, Any], path: str, errors: list[SchemaError]
) -> None:
    if "minimum" in schema and instance < schema["minimum"]:
        errors.append(SchemaError(path, f"less than minimum {schema['minimum']}"))
    if "maximum" in schema and instance > schema["maximum"]:
        errors.append(SchemaError(path, f"greater than maximum {schema['maximum']}"))


def _validate_array(
    instance: list[Any],
    schema: Mapping[str, Any],
    root: Mapping[str, Any],
    path: str,
    errors: list[SchemaError],
) -> None:
    if "minItems" in schema and len(instance) < schema["minItems"]:
        errors.append(SchemaError(path, f"has {len(instance)} items, minItems is {schema['minItems']}"))
    if schema.get("uniqueItems"):
        seen: list[Any] = []
        for item in instance:
            if item in seen:
                errors.append(SchemaError(path, "contains duplicate items"))
                break
            seen.append(item)
    item_schema = schema.get("items")
    if item_schema:
        for index, item in enumerate(instance):
            _validate(item, item_schema, root, f"{path}[{index}]", errors)


def _validate_object(
    instance: dict[str, Any],
    schema: Mapping[str, Any],
    root: Mapping[str, Any],
    path: str,
    errors: list[SchemaError],
) -> None:
    properties: Mapping[str, Any] = schema.get("properties", {})
    for name in schema.get("required", []):
        if name not in instance:
            errors.append(SchemaError(path, f"missing required property {name!r}"))

    if schema.get("additionalProperties") is False:
        for name in instance:
            if name not in properties:
                errors.append(SchemaError(path, f"unexpected property {name!r}"))

    for name, sub_schema in properties.items():
        if name in instance:
            _validate(instance[name], sub_schema, root, f"{path}.{name}", errors)
