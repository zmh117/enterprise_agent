"""Same-snapshot semantic retrieval; returned fragments never stand in for full guards."""

from collections.abc import Callable
import math
from typing import Any, Protocol

from app.modules.knowledge.application.content_access import CodeContentRepository
from app.modules.knowledge.application.ports import EmbeddingPort, QdrantPort, RerankPort
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.code_projection import fragments, PROJECTION_HASH


class CodeSearchQdrant(QdrantPort, Protocol):
    def code_search(
        self, index: dict[str, Any], snapshot_id: str, vector: list[float], limit: int
    ) -> list[dict[str, Any]]: ...


def search_code(
    *,
    store: CodeContentRepository,
    index: dict[str, Any],
    version: dict[str, Any] | None,
    query: str,
    top_k: int,
    resource_revision_id: str,
    embedding: EmbeddingPort,
    qdrant: CodeSearchQdrant,
    reranker: RerankPort,
    check: Callable[[], None],
) -> dict[str, Any]:
    if index["chunk_profile_hash"] != PROJECTION_HASH:
        raise CodeKnowledgeError("code_index_configuration_changed")
    check()
    selected = store.resolve(index["knowledge_base_id"], version)
    result: dict[str, Any] = {
        "source_kind": "code",
        "knowledge_base_id": index["knowledge_base_id"],
        "resource_revision_id": resource_revision_id,
        "index_id": index["id"],
        "version": selected,
        "documents": [],
        "content_scope": "matched_fragments",
        "content_mode": "ingested_snapshot",
        "access_mode": "source_permissions",
        "ranking_method": "cross_encoder",
        "ranking_profile_hash": reranker.profile_hash,
        "partial": selected["status"] != "READY",
        "partial_reason": "version_not_ready" if selected["status"] != "READY" else None,
    }
    if selected["status"] != "READY":
        check()
        return result
    embedding.check()
    check()
    qdrant.check(index)
    check()
    vector = embedding.call([query], encode=True)["vectors"][0]
    check()
    points = qdrant.code_search(index, selected["snapshot_id"], vector, 100)
    check()
    candidates = _candidates(store, index, selected["snapshot_id"], points, check)
    if candidates:
        ranked = reranker.rank(
            query, [[block["text"] for block in item["fragments"]] for item in candidates]
        )
        check()
        ordered = sorted(
            range(len(candidates)),
            key=lambda n: (-ranked["scores"][n], candidates[n]["knowledge_id"]),
        )
        result["documents"] = [
            {**candidates[n], "rank": rank + 1} for rank, n in enumerate(ordered[:top_k])
        ]
        result["partial"] = (
            len(points) == 100 or len(candidates) > top_k or any(ranked["truncated"])
        )
        result["partial_reason"] = "bounded_search" if result["partial"] else None
    store.snapshot(index["knowledge_base_id"], selected["snapshot_id"])
    check()
    return result


def _candidates(
    store: CodeContentRepository,
    index: dict[str, Any],
    snapshot_id: str,
    points: list[dict[str, Any]],
    check: Callable[[], None],
) -> list[dict[str, Any]]:
    members: dict[str, dict[str, Any]] = {}
    candidates: dict[str, dict[str, Any]] = {}
    seen = set()
    for point in points:
        check()
        payload = point.get("payload")
        score = point.get("score")
        if (
            not isinstance(payload, dict)
            or not isinstance(score, (int, float))
            or isinstance(score, bool)
            or not math.isfinite(score)
        ):
            raise CodeKnowledgeError("code_search_candidate_invalid")
        identifier, ordinal = payload.get("document_id"), payload.get("ordinal")
        if (
            not isinstance(identifier, str)
            or type(ordinal) is not int
            or ordinal < 0
            or point.get("id") in seen
        ):
            raise CodeKnowledgeError("code_search_candidate_invalid")
        seen.add(point.get("id"))
        if identifier not in members:
            members[identifier] = store.read_member(
                index["knowledge_base_id"], snapshot_id, identifier
            )
        member = members[identifier]
        definitions = fragments(index, snapshot_id, member)
        if (
            ordinal >= len(definitions)
            or payload != definitions[ordinal]["payload"]
            or point.get("id") != definitions[ordinal]["id"]
        ):
            raise CodeKnowledgeError("code_search_candidate_invalid")
        fragment = definitions[ordinal]
        if identifier not in candidates:
            if len(candidates) >= 50:
                continue
            candidates[identifier] = {
                "knowledge_id": identifier,
                "revision_id": member["revision_id"],
                "snapshot_id": snapshot_id,
                "title": member["knowledge"]["title"],
                "role": member["knowledge"]["role"],
                "coverage": member["knowledge"]["coverage"],
                "unknown_count": len(member["knowledge"]["unknowns"]),
                "evidence": member["evidence"][:3],
                "evidence_scope": "bounded_references",
                "retrieval_score": score,
                "fragments": [],
            }
        if len(candidates[identifier]["fragments"]) < 2:
            candidates[identifier]["fragments"].append(
                {
                    "text": fragment["text"],
                    "start": fragment["start"],
                    "end": fragment["end"],
                    "hash": payload["embedding_hash"],
                }
            )
    return list(candidates.values())
