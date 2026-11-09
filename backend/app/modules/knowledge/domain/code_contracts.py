"""Data-only schemas for bounded versioned code tools."""

from typing import Any
from jsonschema import Draft202012Validator
from app.modules.knowledge.domain.normalization import canonical_json

CODE_SOURCE_GRANT_PATH = "/api/internal/code-knowledge/source-grant"
MAX_SOURCE_BYTES = 15 * 1024 * 1024
MAX_RESPONSE_BYTES = 512 * 1024


class CodeKnowledgeError(ValueError):
    """Only a stable code and JSON location; never include source content."""

    def __init__(self, code: str, location: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.location = location


def obj(properties: dict[str, Any], optional: tuple[str, ...] = ()) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": [key for key in properties if key not in optional],
    }


def array(item: dict[str, Any], maximum: int = 1000, minimum: int = 0) -> dict[str, Any]:
    return {"type": "array", "items": item, "maxItems": maximum, "minItems": minimum}


TEXT = {"type": "string", "minLength": 1, "maxLength": 8000}
ID = {"type": "string", "pattern": r"^[A-Za-z0-9_.:/-]{1,200}$"}
HASH = {"type": "string", "pattern": "^[a-f0-9]{64}$"}


def validate(value: Any, schema: dict[str, Any]) -> None:
    # Bound recursive JSON before recursive schema traversal; reject NaN and opaque objects.
    try:
        encoded = canonical_json(value).encode("utf-8")
        if len(encoded) > MAX_RESPONSE_BYTES:
            raise CodeKnowledgeError("code_contract_too_large")
        _depth(value)
        error = next(Draft202012Validator(schema).iter_errors(value), None)
    except (RecursionError, TypeError, ValueError) as exc:
        if isinstance(exc, CodeKnowledgeError):
            raise
        raise CodeKnowledgeError("code_contract_invalid") from None
    if error is not None:
        raise CodeKnowledgeError("code_contract_invalid", "/".join(map(str, error.absolute_path)))


def _depth(value: Any, level: int = 0) -> None:
    if level > 32:
        raise CodeKnowledgeError("code_contract_too_deep")
    if isinstance(value, dict):
        for item in value.values():
            _depth(item, level + 1)
    elif isinstance(value, list):
        for item in value:
            _depth(item, level + 1)
