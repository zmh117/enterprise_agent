"""Strict bounded-consumer JSON parsing; duplicate keys and non-finite values are rejected."""

import hashlib
import json
from typing import Any
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CodeKnowledgeError("code_duplicate_json_key")
        result[key] = value
    return result


def parse_json(text: str) -> Any:
    try:
        return json.loads(
            text,
            object_pairs_hook=_unique_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
    except (ValueError, RecursionError):
        raise CodeKnowledgeError("code_json_invalid") from None
