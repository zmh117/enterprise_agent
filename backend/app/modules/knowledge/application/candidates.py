"""离线与在线共用候选快照；内部块文本与返回引用分离。"""

from dataclasses import dataclass
import math
from typing import Any

from app.modules.knowledge.domain.vector_contract import VectorError, fingerprint
from app.modules.knowledge.application.ports import QdrantPort, VectorRepository
from app.modules.knowledge.domain.vector_points import point_id, payload
from app.modules.knowledge.domain.hybrid import HYBRID_CONTRACT, hybrid_index
from app.modules.knowledge.domain.rerank_contract import MAX_CANDIDATE_POINTS, MAX_DOCUMENTS


@dataclass(repr=False)
class CandidatePool:
    documents: list[dict[str, Any]]
    rows: dict[str, dict[str, Any]]
    points: list[dict[str, Any]]

    @property
    def selected(self) -> list[dict[str, Any]]:
        return self.documents[:MAX_DOCUMENTS]

    @property
    def digest(self) -> str:
        return fingerprint(
            {
                "documents": self.documents,
                "texts": {key: row["embedding_hash"] for key, row in self.rows.items()},
            }
        )

    def recheck(self, repo: VectorRepository, index: dict[str, Any]) -> None:
        if candidate_pool(repo, index, self.points).digest != self.digest:
            raise VectorError("knowledge_vector_source_changed")


def retrieval_mode(index: dict[str, Any], mode: str = "auto") -> str:
    selected = (
        "hybrid" if mode == "auto" and hybrid_index(index) else "dense" if mode == "auto" else mode
    )
    if selected not in {"dense", "bm25", "hybrid"}:
        raise VectorError("knowledge_vector_query_invalid")
    if selected != "dense" and not hybrid_index(index):
        raise VectorError("knowledge_hybrid_index_required")
    return "hybrid_rrf" if selected == "hybrid" else selected


def retrieve_points(
    qdrant: QdrantPort, index: dict[str, Any], vector: list[float] | None, query: str, mode: str
) -> list[dict[str, Any]]:
    if hybrid_index(index):
        return qdrant.hybrid_search(
            index,
            vector,
            query,
            MAX_CANDIDATE_POINTS,
            mode="hybrid" if mode == "hybrid_rrf" else mode,
        )
    if vector is None or mode != "dense":
        raise VectorError("knowledge_hybrid_index_required")
    return qdrant.search(index, vector, MAX_CANDIDATE_POINTS)


def route_limit(mode: str) -> int:
    return HYBRID_CONTRACT["per_route_limit"] if mode == "hybrid_rrf" else MAX_CANDIDATE_POINTS


def current_documents(
    repo: VectorRepository, index: dict[str, Any], candidates: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    return candidate_pool(repo, index, candidates).documents


def candidate_pool(
    repo: VectorRepository, index: dict[str, Any], candidates: list[dict[str, Any]]
) -> CandidatePool:
    if not isinstance(candidates, list) or len(candidates) > MAX_CANDIDATE_POINTS:
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
        evidence.update({"chunk_id": row["id"], "retrieval_score": hit["score"]})
        doc = docs.setdefault(
            row["document_id"],
            {
                "document_id": row["document_id"],
                "revision_id": row["document_revision_id"],
                "retrieval_score": hit["score"],
                "evidence": [],
            },
        )
        doc["retrieval_score"] = max(doc["retrieval_score"], hit["score"])
        doc["evidence"].append(evidence)
    for doc in docs.values():
        doc["evidence"] = sorted(
            doc["evidence"], key=lambda e: (-e["retrieval_score"], e["chunk_id"])
        )[:3]
    documents = sorted(docs.values(), key=lambda d: (-d["retrieval_score"], d["document_id"]))
    return CandidatePool(documents, current, candidates)
