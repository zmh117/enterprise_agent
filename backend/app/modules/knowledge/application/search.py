"""授权后的有界 dense/混合检索；返回引用，不向调用者返回离线正文。"""

from app.modules.knowledge.application.principal import PrincipalToken

from dataclasses import dataclass
import threading
from typing import Any

from app.modules.audit.application.audit_service import AuditService
from app.modules.knowledge.application.candidates import (
    candidate_pool,
    retrieval_mode,
    retrieve_points,
    route_limit,
)
from app.modules.knowledge.application.ranking import rerank
from app.modules.knowledge.application.content_access import KnowledgeContent
from app.modules.knowledge.domain.governance import KnowledgeGovernanceError, checked_identifier
from app.modules.knowledge.application.ports import (
    PrincipalAccess,
    EmbeddingPort,
    QdrantPort,
    ReadabilityPort,
    RerankPort,
)
from app.modules.knowledge.application.readability import ReadabilityCandidates, ReadabilityRequest
from app.modules.knowledge.application.readability import project_readability
from app.modules.knowledge.domain.models import (
    KnowledgeJobAccess,
    PinnedKnowledgeResource,
    OnesKnowledgeIdentity,
)
from app.modules.knowledge.application.resource_service import KnowledgeResourceReader
from app.modules.knowledge.application.retrieval_budget import RetrievalBudget, knowledge_entry
from app.shared.exceptions import AppError
from app.modules.knowledge.domain.rerank_contract import MAX_CANDIDATE_POINTS, MAX_DOCUMENTS
from app.modules.knowledge.domain.vector_contract import VectorError


MAX_POINTS = MAX_CANDIDATE_POINTS


@dataclass(frozen=True, repr=False)
class SearchRequest:
    knowledge_base_id: str
    query: str
    top_k: int

    @classmethod
    def parse(cls, value: Any) -> "SearchRequest":
        if (
            not isinstance(value, dict)
            or not {"knowledge_base_id", "query"} <= set(value)
            or not set(value) <= {"knowledge_base_id", "query", "top_k"}
        ):
            raise KnowledgeGovernanceError("knowledge_input_invalid")
        query, top_k = value["query"], value.get("top_k", 10)
        if (
            not isinstance(query, str)
            or not query.strip()
            or not 1 <= len(query) <= 2000
            or type(top_k) is not int
            or not 1 <= top_k <= 20
        ):
            raise KnowledgeGovernanceError("knowledge_input_invalid")
        try:
            query.encode("utf-8", errors="strict")
        except UnicodeError:
            raise KnowledgeGovernanceError("knowledge_input_invalid") from None
        return cls(checked_identifier(value["knowledge_base_id"]), query, top_k)


class KnowledgeSearch:
    def __init__(
        self,
        access: PrincipalAccess,
        resources: KnowledgeResourceReader,
        embedding: EmbeddingPort,
        qdrant: QdrantPort,
        readability: ReadabilityPort,
        audit: AuditService,
        *,
        reranker: RerankPort,
    ) -> None:
        self.access, self.resources = access, resources
        self.embedding, self.qdrant = embedding, qdrant
        self.readability, self.audit = readability, audit
        self.reranker = reranker
        self._slots = threading.BoundedSemaphore(4)

    @knowledge_entry
    def search(self, *, token: PrincipalToken, arguments: Any) -> dict[str, Any]:
        access, acquired = None, False
        try:
            request = SearchRequest.parse(arguments)
            access = self.access.authenticate(token, "knowledge_search")
            if request.knowledge_base_id not in access.knowledge_base_ids:
                raise KnowledgeGovernanceError("knowledge_job_denied")
            acquired = self._slots.acquire(blocking=False)
            if not acquired:
                raise KnowledgeGovernanceError("knowledge_search_busy")
            budget = self.access.budget(access.job_id)
            with budget.activate():
                return self._search(token, request, access, budget)
        except KnowledgeGovernanceError as exc:
            failure = exc
        except VectorError as exc:
            code = "knowledge_search_dependency_failed"
            if exc.code.startswith("knowledge_embedding_"):
                code = (
                    exc.code
                    if exc.code in {"knowledge_embedding_busy", "knowledge_embedding_read_timeout"}
                    else "knowledge_embedding_unavailable"
                )
            elif exc.code.startswith("knowledge_rerank_"):
                code = (
                    exc.code
                    if exc.code
                    in {
                        "knowledge_rerank_busy",
                        "knowledge_rerank_read_timeout",
                        "knowledge_rerank_input_limit",
                    }
                    else "knowledge_rerank_unavailable"
                )
            failure = KnowledgeGovernanceError(code)
        except AppError:
            failure = KnowledgeGovernanceError("knowledge_job_denied")
        except Exception:
            # 客户端/数据库异常可能含请求内容；不记录异常字符串、参数或原响应。
            failure = KnowledgeGovernanceError("knowledge_search_dependency_failed")
        finally:
            if acquired:
                self._slots.release()
        try:
            self.audit.record(
                "knowledge.search.denied",
                status="denied",
                summary="知识检索未完成",
                actor_id=access.actor_id if access else None,
                job_id=access.job_id if access else None,
                payload={"error_code": failure.error_code},
            )
        except Exception:
            raise KnowledgeGovernanceError("knowledge_search_dependency_failed") from None
        raise failure from None

    def _search(
        self,
        token: PrincipalToken,
        request: SearchRequest,
        access: KnowledgeJobAccess,
        budget: RetrievalBudget,
    ) -> dict[str, Any]:
        identity = self.access.identity(access.actor_id)
        pin = self.resources.resolve(request.knowledge_base_id)
        with self.resources.content_for(pin) as content:
            return self._search_content(token, request, access, budget, identity, pin, content)

    def _search_content(
        self,
        token: PrincipalToken,
        request: SearchRequest,
        access: KnowledgeJobAccess,
        budget: RetrievalBudget,
        identity: OnesKnowledgeIdentity,
        pin: PinnedKnowledgeResource,
        content: KnowledgeContent,
    ) -> dict[str, Any]:
        index = content.vectors.get(pin.index_code)
        qdrant = content.qdrant or self.qdrant
        if index is None:
            raise KnowledgeGovernanceError("knowledge_index_unavailable")

        def recheck() -> None:
            budget.check()
            if (
                self.access.authenticate(token, "knowledge_search") != access
                or self.access.identity(access.actor_id) != identity
            ):
                raise KnowledgeGovernanceError("knowledge_authorization_changed")
            self.resources.recheck(pin)
            budget.check()

        recheck()
        self.embedding.check()
        recheck()
        qdrant.check(index)
        recheck()
        vector = self.embedding.call([request.query], encode=True)["vectors"][0]
        recheck()
        selected_mode = retrieval_mode(index)
        candidates = retrieve_points(qdrant, index, vector, request.query, selected_mode)
        pool = candidate_pool(content.vectors, index, candidates)
        recheck()
        ranked = rerank(pool, request.query, self.reranker)
        recheck()
        documents = ranked.documents
        results: list[dict[str, Any]] = []
        checked, timed_out = 0, False
        while checked < min(len(documents), MAX_DOCUMENTS) and len(results) < request.top_k:
            budget.check()
            if budget.remaining() <= 1:
                timed_out = True
                break  # 预留返回前授权/资源复核时间，不启动新的外部请求。
            recheck()
            batch = documents[
                checked : checked + min(10, request.top_k - len(results), MAX_DOCUMENTS - checked)
            ]
            bridge_request = ReadabilityRequest(
                pin.knowledge_base_id,
                pin.revision_id,
                pin.index_id,
                tuple(doc["evidence"][0]["chunk_id"] for doc in batch),
            )
            member_facts = ReadabilityCandidates.load(self.resources, bridge_request)
            raw = self.readability.check(token=token, request=bridge_request)
            verified = project_readability(raw, bridge_request, access, member_facts)
            budget.check()
            for document, reference in zip(batch, verified["items"], strict=True):
                if reference["readable"]:
                    results.append(
                        {
                            **{
                                key: document[key]
                                for key in (
                                    "document_id",
                                    "revision_id",
                                    "retrieval_score",
                                    "evidence",
                                )
                            },
                            "rank": len(results) + 1,
                            "index_id": pin.index_id,
                            "source_id": pin.source_id,
                            "work_item_uuid": reference["task_id"],
                            "number": reference["number"],
                        }
                    )
            checked += len(batch)
        recheck()
        pool.recheck(content.vectors, index)
        budget.check()
        partial = len(results) < request.top_k and (
            timed_out
            or len(candidates) >= route_limit(selected_mode)
            or len(pool.documents) > MAX_DOCUMENTS
        )
        self.audit.record(
            "knowledge.search.completed",
            status="success",
            summary="知识检索完成",
            actor_id=access.actor_id,
            job_id=access.job_id,
            payload={
                "knowledge_base_id": pin.knowledge_base_id,
                "resource_revision_id": pin.revision_id,
                "index_id": pin.index_id,
                "returned": len(results),
                "partial": partial,
                "retrieval_mode": selected_mode,
                "ranking_profile_hash": ranked.profile_hash,
                "rerank_executed": bool(pool.selected),
                "rerank_duration_ms": round(ranked.duration_ms, 3),
            },
        )
        return {
            "knowledge_base_id": pin.knowledge_base_id,
            "resource_revision_id": pin.revision_id,
            "index_id": pin.index_id,
            "documents": results,
            "retrieval_mode": selected_mode,
            "ranking_method": "cross_encoder",
            "ranking_profile_hash": ranked.profile_hash,
            "partial": partial,
            "partial_reason": "bounded_search" if partial else None,
        }
