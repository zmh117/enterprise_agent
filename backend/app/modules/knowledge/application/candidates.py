"""离线检索与受治理读取共用 dense 候选验证/文档聚合，不返回缓存正文。"""

import math
from typing import Any

from app.modules.knowledge.domain.vector_contract import VectorError
from app.modules.knowledge.application.ports import VectorRepository
from app.modules.knowledge.domain.vector_points import point_id, payload


def current_documents(
    repo: VectorRepository, index: dict[str, Any], candidates: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if not isinstance(candidates, list) or len(candidates) > 200:
        raise VectorError("knowledge_vector_response_invalid")
    seen: set[str] = set()
    for hit in candidates:
        if (
            not isinstance(hit, dict)
            or not isinstance(hit.get("id"), str)
            or hit["id"] in seen
            or type(hit.get("score")) not in (float, int)
            or not math.isfinite(hit["score"])
            or not isinstance(hit.get("payload"), dict)
            or not isinstance(hit["payload"].get("chunk_id"), str)
        ):
            raise VectorError("knowledge_vector_response_invalid")
        seen.add(hit["id"])
    current = repo.evidence_many(index, [hit["payload"]["chunk_id"] for hit in candidates])
    docs: dict[str, dict[str, Any]] = {}
    for hit in candidates:
        row = current.get(hit["payload"]["chunk_id"])
        if row is None:
            continue
        if hit["id"] != point_id(index, row) or hit["payload"] != payload(index, row):
            raise VectorError("knowledge_vector_point_conflict")
        evidence = {
            key: row[key]
            for key in ("source_field", "source_start", "source_end", "chunk_kind", "evidence_hash")
        }
        evidence.update({"chunk_id": row["id"], "score": hit["score"]})
        doc = docs.setdefault(
            row["document_id"],
            {
                "document_id": row["document_id"],
                "revision_id": row["document_revision_id"],
                "score": hit["score"],
                "evidence": [],
            },
        )
        doc["score"] = max(doc["score"], hit["score"])
        doc["evidence"].append(evidence)
    for doc in docs.values():
        doc["evidence"] = sorted(doc["evidence"], key=lambda e: (-e["score"], e["chunk_id"]))[:3]
    return sorted(docs.values(), key=lambda d: (-d["score"], d["document_id"]))
