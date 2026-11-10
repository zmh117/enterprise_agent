"""Exact-version retrieval, then one nearest authorized higher-version hint."""

from collections.abc import Callable
import json
import math
from typing import Any, Protocol

from app.modules.knowledge.application.ports import EmbeddingPort, QdrantPort, RerankPort
from app.modules.knowledge.domain.code_configuration import CODE_CHUNK_PROFILE
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.models import KnowledgeJobAccess, PinnedKnowledgeResource


class CodeAnswerContent(Protocol):
    def select_version(
        self,
        *,
        base_id: str,
        environment_id: str,
        source_id: str,
        index_id: str,
        revision: int,
        mode: str,
        allowed_paths: list[str],
    ) -> dict[str, Any]: ...
    def get(
        self,
        *,
        base_id: str,
        environment_id: str,
        source_id: str,
        index_id: str,
        document_id: str,
        revision_id: str,
        allowed_paths: list[str],
    ) -> dict[str, Any]: ...
    def chunk(
        self,
        *,
        index: dict[str, Any],
        point: dict[str, Any],
        allowed_paths: list[str],
        environment_id: str,
    ) -> dict[str, Any] | None: ...


class CodeSearchReceiptPort(Protocol):
    def read(
        self,
        identifier: str,
        *,
        access: KnowledgeJobAccess,
        pin: PinnedKnowledgeResource,
        environment_id: str,
    ) -> dict[str, Any]: ...


class CodeAnswerQdrant(QdrantPort, Protocol):
    def code_answer_search(
        self,
        index: dict[str, Any],
        revision: int,
        document_ids: list[str],
        generation_keys: list[str],
        vector: list[float],
        limit: int,
    ) -> list[dict[str, Any]]: ...


class CodeAnswerReranker(RerankPort, Protocol):
    def check(self) -> None: ...


def search_code_answers(
    *,
    store: CodeAnswerContent,
    index: dict[str, Any],
    revision: int,
    mode: str,
    allowed_paths: list[str],
    query: str,
    top_k: int,
    resource_revision_id: str,
    environment_id: str,
    embedding: EmbeddingPort,
    qdrant: CodeAnswerQdrant,
    reranker: CodeAnswerReranker,
    check: Callable[[], None],
) -> dict[str, Any]:
    if index["chunk_profile_hash"] != CODE_CHUNK_PROFILE.fingerprint:
        raise CodeKnowledgeError("CODE_INDEX_CONFIGURATION_CHANGED")
    check()
    selected = store.select_version(
        base_id=index["knowledge_base_id"],
        environment_id=environment_id,
        source_id=index["source_id"],
        index_id=index["id"],
        revision=revision,
        mode=mode,
        allowed_paths=allowed_paths,
    )
    result: dict[str, Any] = {
        "source_kind": "code",
        "knowledge_base_id": index["knowledge_base_id"],
        "resource_revision_id": resource_revision_id,
        "index_id": index["id"],
        "requested_revision": revision,
        "matched_revision": selected["matched_revision"],
        "match_kind": "exact" if mode == "exact" else "higher_revision_hint",
        "requires_verification": mode == "next_higher_hint",
        "documents": [],
        "content_scope": "matched_chunks_with_conditions",
        "access_mode": "source_permissions",
        "ranking_method": "cross_encoder",
        "ranking_profile_hash": reranker.profile_hash,
        "partial": False,
        "partial_reason": None,
    }
    # A dependency outage must not look like a successful miss, including an empty KB.
    embedding.check()
    check()
    qdrant.check(index)
    check()
    reranker.check()
    check()
    if selected["matched_revision"] is None:
        return result
    vector = embedding.call([query], encode=True)["vectors"][0]
    check()
    points = qdrant.code_answer_search(
        index,
        selected["matched_revision"],
        selected["document_ids"],
        selected["generation_keys"],
        vector,
        100,
    )
    check()
    documents: dict[str, dict[str, Any]] = {}
    seen = set()
    for point in points:
        score = point.get("score")
        if (
            not isinstance(score, (float, int))
            or isinstance(score, bool)
            or not math.isfinite(score)
            or point.get("id") in seen
        ):
            raise CodeKnowledgeError("CODE_SEARCH_CANDIDATE_INVALID")
        seen.add(point.get("id"))
        selected_point = store.chunk(
            index=index, point=point, allowed_paths=allowed_paths, environment_id=environment_id
        )
        if selected_point is None:
            continue
        answer, chunk = selected_point["answer"], selected_point["chunk"]
        if (
            answer["document_id"] not in selected["document_ids"]
            or answer["svn_revision"] != selected["matched_revision"]
        ):
            raise CodeKnowledgeError("CODE_SEARCH_CANDIDATE_INVALID")
        if answer["document_id"] not in documents and len(documents) < 50:
            documents[answer["document_id"]] = {
                key: answer[key]
                for key in (
                    "document_id",
                    "revision_id",
                    "source_id",
                    "svn_revision",
                    "title",
                    "question_text",
                    "conditions",
                    "claims",
                    "coverage",
                    "unknowns",
                    "support_status",
                )
            } | {"evidence": [], "retrieval_score": score, "_ranking_blocks": []}
        candidate = documents.get(answer["document_id"])
        if candidate is not None and len(candidate["evidence"]) < 2:
            candidate["evidence"].append(chunk)
            candidate["_ranking_blocks"].append(selected_point["ranking_text"])
    check()
    candidates = list(documents.values())
    if candidates:
        ranked = reranker.rank(query, [item.pop("_ranking_blocks") for item in candidates])
        check()
        ordered = sorted(
            range(len(candidates)),
            key=lambda n: (-ranked["scores"][n], candidates[n]["document_id"]),
        )
        result["documents"] = [
            {**candidates[n], "rank": rank + 1} for rank, n in enumerate(ordered[:top_k])
        ]
        result["partial"] = (
            len(points) == 100 or len(candidates) > top_k or any(ranked["truncated"])
        )
        # Whole conditions are indivisible. Drop tail candidates, never trim their conditions.
        while len(json.dumps(result, ensure_ascii=False).encode()) > 480 * 1024:
            result["documents"].pop()
            result["partial"] = True
            if not result["documents"]:
                raise CodeKnowledgeError("CODE_SEARCH_RESULT_LIMIT")
    # Recheck visibility after external I/O before returning any accepted evidence.
    for item in result["documents"]:
        store.get(
            base_id=index["knowledge_base_id"],
            environment_id=environment_id,
            source_id=index["source_id"],
            index_id=index["id"],
            document_id=item["document_id"],
            revision_id=item["revision_id"],
            allowed_paths=allowed_paths,
        )
    check()
    result["partial_reason"] = "bounded_search" if result["partial"] else None
    return result
