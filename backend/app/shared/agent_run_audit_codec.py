from __future__ import annotations

import base64
import hashlib
import json
from typing import Any


AUDIT_CHUNK_BYTES = 40 * 1024
MAX_AUDIT_CHUNKS = 1600


def encode_audit_chunks(audit: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    encoded = _canonical_json(audit).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    parts = [
        encoded[index : index + AUDIT_CHUNK_BYTES]
        for index in range(0, len(encoded), AUDIT_CHUNK_BYTES)
    ]
    if not parts:
        parts = [b"{}"]
    if len(parts) > MAX_AUDIT_CHUNKS:
        raise ValueError("Agent run audit exceeds the Runtime protocol chunk boundary")
    count = len(parts)
    return digest, [
        {
            "encoding": "base64+json",
            "chunk_index": index,
            "chunk_count": count,
            "sha256": digest,
            "content": base64.b64encode(part).decode("ascii"),
        }
        for index, part in enumerate(parts)
    ]


def decode_audit_chunks(
    chunks: list[dict[str, Any]],
    *,
    expected_sha256: str,
    expected_count: int,
) -> dict[str, Any]:
    if expected_count < 1 or len(chunks) != expected_count:
        raise ValueError("Agent run audit chunk count is incomplete")
    ordered = sorted(chunks, key=lambda item: int(item.get("chunk_index", -1)))
    for index, chunk in enumerate(ordered):
        if (
            chunk.get("encoding") != "base64+json"
            or int(chunk.get("chunk_index", -1)) != index
            or int(chunk.get("chunk_count", -1)) != expected_count
            or str(chunk.get("sha256") or "") != expected_sha256
        ):
            raise ValueError("Agent run audit chunk identity is invalid")
    try:
        encoded = b"".join(
            base64.b64decode(str(chunk["content"]), validate=True) for chunk in ordered
        )
    except (KeyError, ValueError) as exc:
        raise ValueError("Agent run audit chunk encoding is invalid") from exc
    if hashlib.sha256(encoded).hexdigest() != expected_sha256:
        raise ValueError("Agent run audit digest does not match")
    try:
        decoded = json.loads(encoded.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Agent run audit JSON is invalid") from exc
    if not isinstance(decoded, dict):
        raise ValueError("Agent run audit must be a JSON object")
    return decoded


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
