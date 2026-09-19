"""授权后的有界 dense 检索；返回引用，不向调用者返回离线正文。"""

from dataclasses import dataclass
import threading
from typing import Any

from app.modules.audit.application.audit_service import AuditService
from app.modules.knowledge.application.candidates import current_documents
from app.modules.knowledge.domain.governance import KnowledgeGovernanceError, checked_identifier
from app.modules.knowledge.application.ports import (
    PrincipalAccess,
    EmbeddingPort,
    QdrantPort,
    ReadabilityPort,
)
from app.modules.knowledge.application.readability import ReadabilityCandidates, ReadabilityRequest
from app.modules.knowledge.application.readability import project_readability
from app.modules.knowledge.domain.models import KnowledgeJobAccess
from app.modules.knowledge.application.resource_service import KnowledgeResourceReader
from app.modules.knowledge.application.retrieval_budget import RetrievalBudget
from app.shared.exceptions import AppError


MAX_POINTS = 200
MAX_DOCUMENTS = 50


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
    ) -> None:
        self.access, self.resources = access, resources
        self.embedding, self.qdrant = embedding, qdrant
        self.readability, self.audit = readability, audit
        self._slots = threading.BoundedSemaphore(4)

    def search(self, *, token: str, arguments: Any) -> dict[str, Any]:
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
        token: str,
        request: SearchRequest,
        access: KnowledgeJobAccess,
        budget: RetrievalBudget,
    ) -> dict[str, Any]:
        identity = self.access.identity(access.actor_id)
        pin = self.resources.resolve(request.knowledge_base_id)
        binding = self.resources.store.get("source_binding", pin.binding_id)
        if (
            binding["instance_code"] != identity.instance_code
            or binding["team_id"] != identity.team_id
        ):
            raise KnowledgeGovernanceError("knowledge_source_identity_invalid")
        index = self.resources.vectors.get(pin.index_code)
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
        self.qdrant.check(index)
        recheck()
        vector = self.embedding.call([request.query], encode=True)["vectors"][0]
        recheck()
        # 一次最多读取 200 点，随后在同一候选池内按文档补齐，避免重复扩大请求的累计超限。
        candidates = self.qdrant.search(index, vector, MAX_POINTS)
        documents = current_documents(self.resources.vectors, index, candidates)
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
                            **document,
                            "index_id": pin.index_id,
                            "source_binding_id": pin.binding_id,
                            "work_item_uuid": reference["task_id"],
                            "number": reference["number"],
                        }
                    )
            checked += len(batch)
        recheck()
        current = {
            doc["document_id"]: doc
            for doc in current_documents(self.resources.vectors, index, candidates)
        }
        for result in results:
            before = {
                key: result[key] for key in ("document_id", "revision_id", "score", "evidence")
            }
            if current.get(result["document_id"]) != before:
                raise KnowledgeGovernanceError("knowledge_candidate_invalid")
        budget.check()
        partial = len(results) < request.top_k and (
            timed_out or len(candidates) == MAX_POINTS or len(documents) > MAX_DOCUMENTS
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
            },
        )
        return {
            "knowledge_base_id": pin.knowledge_base_id,
            "resource_revision_id": pin.revision_id,
            "index_id": pin.index_id,
            "documents": results,
            "partial": partial,
            "partial_reason": "bounded_search" if partial else None,
        }
