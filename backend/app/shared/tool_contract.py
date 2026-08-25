from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


MAX_TOOL_CONTRACT_ITEMS = 128
MAX_TOOL_SCHEMA_BYTES = 65_536


class ToolContractValueError(ValueError):
    pass


def canonical_json(value: object) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ToolContractValueError("Tool contract value is not canonical JSON") from exc
    return encoded


def canonical_json_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def normalize_input_schema(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ToolContractValueError("Tool input schema must be an object")
    encoded = canonical_json(value)
    if len(encoded.encode("utf-8")) > MAX_TOOL_SCHEMA_BYTES:
        raise ToolContractValueError("Tool input schema exceeds its byte boundary")
    normalized = json.loads(encoded)
    if not isinstance(normalized, dict):
        raise ToolContractValueError("Tool input schema must be an object")
    return normalized


def tool_schema_hash(value: object) -> str:
    return canonical_json_sha256(normalize_input_schema(value))
