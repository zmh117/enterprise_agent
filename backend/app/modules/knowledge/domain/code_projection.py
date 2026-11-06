"""Deterministic search fragments. The structured operation remains authoritative."""

from typing import Any

from app.modules.knowledge.domain.identity import stable_id
from app.modules.knowledge.domain.normalization import canonical_json, digest

SEGMENT_CHARS = 1000
PROJECTION = {"kind": "code-business-search/v1", "segment_chars": SEGMENT_CHARS}
PROJECTION_HASH = digest(PROJECTION)
MAX_POINTS = 20_000


def projection_text(record: dict[str, Any]) -> str:
    return "\n".join(
        [
            record["title"],
            record["summary"],
            "角色：" + record["role"],
            "条件：" + canonical_json(record["guard"]),
            *[
                fact["description"]
                for name in ("check_order", "effects", "outcomes", "configuration")
                for fact in record[name]
            ],
            "成功边界：" + record["success_boundary"]["description"],
            *["未知：" + item["description"] for item in record["unknowns"]],
        ]
    )


def fragments(index: dict[str, Any], snapshot_id: str, row: dict[str, Any]) -> list[dict[str, Any]]:
    text = projection_text(row["knowledge"])
    result = []
    for ordinal, start in enumerate(range(0, len(text), SEGMENT_CHARS)):
        value = text[start : start + SEGMENT_CHARS]
        payload = {
            "point_kind": "code_knowledge",
            "index_id": index["id"],
            "knowledge_base_id": index["knowledge_base_id"],
            "snapshot_id": snapshot_id,
            "document_id": row["knowledge_id"],
            "revision_id": row["revision_id"],
            "profile_hash": index["profile_hash"],
            "projection_hash": PROJECTION_HASH,
            "embedding_hash": digest(value),
            "ordinal": ordinal,
        }
        result.append(
            {
                "id": stable_id(
                    "code_point",
                    index["id"],
                    snapshot_id,
                    row["knowledge_id"],
                    row["revision_id"],
                    str(ordinal),
                ),
                "payload": payload,
                "text": value,
                "start": start,
                "end": start + len(value),
            }
        )
    return result


def cache_point(index: dict[str, Any], fragment: dict[str, Any]) -> dict[str, Any]:
    content_hash = fragment["payload"]["embedding_hash"]
    return {
        "id": stable_id("code_embedding_cache", index["id"], index["profile_hash"], content_hash),
        "payload": {
            "point_kind": "code_embedding_cache",
            "index_id": index["id"],
            "knowledge_base_id": index["knowledge_base_id"],
            "profile_hash": index["profile_hash"],
            "embedding_hash": content_hash,
        },
    }
