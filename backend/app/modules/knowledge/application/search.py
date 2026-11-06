"""有界入库快照检索；默认执行 ONES 当前可读性检查，显式离线模式仅校验 KB 授权。"""

from app.modules.knowledge.application.principal import PrincipalToken

from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime
import threading
from typing import Any, cast
from app.modules.knowledge.application.code_search import CodeSearchQdrant, search_code
from app.modules.knowledge.domain.code_contracts import (
    CodeKnowledgeError,
    VERSION_SELECTOR,
    validate,
)

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
    RerankPort,
    ReadabilityPort,
    CodeHistoryPort,
)
from app.modules.knowledge.domain.models import (
    KnowledgeJobAccess,
    KnowledgeAccessMode,
    PinnedKnowledgeResource,
)
from app.modules.knowledge.application.readability import (
    ReadabilityCandidates,
    ReadabilityRequest,
    project_readability,
)
from app.modules.knowledge.application.resource_service import KnowledgeResourceReader
from app.modules.knowledge.application.retrieval_budget import RetrievalBudget, knowledge_entry
from app.modules.knowledge.application.retrieval_timing import stage
from app.shared.exceptions import AppError
from app.modules.knowledge.domain.rerank_contract import MAX_CANDIDATE_POINTS, MAX_DOCUMENTS
from app.modules.knowledge.domain.vector_contract import VectorError


MAX_POINTS = MAX_CANDIDATE_POINTS


@dataclass(frozen=True, repr=False)
class SearchRequest:
    knowledge_base_id: str
    query: str
    top_k: int
    version: dict[str, Any] | None = None

    @classmethod
    def parse(cls, value: Any) -> "SearchRequest":
        if (
            not isinstance(value, dict)
            or not {"knowledge_base_id", "query"} <= set(value)
            or not set(value) <= {"knowledge_base_id", "query", "top_k", "version"}
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
        if "version" in value:
            validate(value["version"], VERSION_SELECTOR)
        return cls(
            checked_identifier(value["knowledge_base_id"]), query, top_k, value.get("version")
        )


class KnowledgeSearch:
    def __init__(
        self,
        access: PrincipalAccess,
        resources: KnowledgeResourceReader,
        embedding: EmbeddingPort,
        qdrant: QdrantPort,
        audit: AuditService,
        *,
        reranker: RerankPort,
        access_mode: KnowledgeAccessMode = KnowledgeAccessMode.ONLINE,
        readability: ReadabilityPort | None = None,
        code_history: CodeHistoryPort | None = None,
    ) -> None:
        self.access_mode = KnowledgeAccessMode(access_mode)
        if self.access_mode is KnowledgeAccessMode.ONLINE and readability is None:
            raise ValueError("在线知识检索必须装配 ONES 可读性检查")
        self.readability = readability
        self.code_history = code_history
        self.access, self.resources = access, resources
        self.embedding, self.qdrant = embedding, qdrant
        self.audit = audit
        self.reranker = reranker
        self._slots = threading.BoundedSemaphore(4)

    @knowledge_entry
    def search(self, *, token: PrincipalToken, arguments: Any) -> dict[str, Any]:
        access, acquired = None, False
        try:
            request = SearchRequest.parse(arguments)
            with stage("access_check"):
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
        except CodeKnowledgeError as exc:
            failure = KnowledgeGovernanceError(exc.code)
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
        with ExitStack() as stack:
            with stage("resource"):
                pin = self.resources.resolve(request.knowledge_base_id)
                content = stack.enter_context(self.resources.content_for(pin))
            if content.records.get("source", pin.source_id)["source_system"] == "code":
                return self._search_code(token, request, access, budget, pin, content)
            if request.version is not None:
                raise KnowledgeGovernanceError("knowledge_input_invalid")
            return self._search_content(token, request, access, budget, pin, content)

    def _search_code(
        self,
        token: PrincipalToken,
        request: SearchRequest,
        access: KnowledgeJobAccess,
        budget: RetrievalBudget,
        pin: PinnedKnowledgeResource,
        content: KnowledgeContent,
    ) -> dict[str, Any]:
        index = content.vectors.get(pin.index_code)
        store = content.code
        if store is None or index is None:
            raise CodeKnowledgeError("code_source_unavailable")

        def check() -> None:
            budget.check()
            if self.access.authenticate(token, "knowledge_search") != access:
                raise KnowledgeGovernanceError("knowledge_authorization_changed")
            self.resources.recheck(pin)

        def retrieve() -> dict[str, Any]:
            return search_code(
                store=store,
                index=index,
                version=request.version,
                query=request.query,
                top_k=request.top_k,
                resource_revision_id=pin.revision_id,
                embedding=self.embedding,
                qdrant=cast(CodeSearchQdrant, content.qdrant or self.qdrant),
                reranker=self.reranker,
                check=check,
            )

        result = retrieve()
        if (
            result["version"]["status"] == "BUILD_REQUIRED"
            and request.version is not None
            and request.version["kind"] == "svn"
            and self.code_history is not None
        ):
            result["version"] = self.code_history.code_history(
                token=token,
                request={
                    "action": "version",
                    "knowledge_base_id": request.knowledge_base_id,
                    "resource_revision_id": pin.revision_id,
                    "revision": request.version["revision"],
                },
            )
            check()
            if result["version"]["status"] == "READY":
                # The exact snapshot can finish between the read and cache request.
                # Return its verified contents rather than READY with a stale empty result.
                result = retrieve()
        self.audit.record(
            "knowledge.search.completed",
            status="success",
            summary="已返回指定版本代码知识定位结果",
            actor_id=access.actor_id,
            job_id=access.job_id,
            payload={
                "knowledge_base_id": pin.knowledge_base_id,
                "returned": len(result["documents"]),
                "version_status": result["version"]["status"],
            },
        )
        return result

    def _search_content(
        self,
        token: PrincipalToken,
        request: SearchRequest,
        access: KnowledgeJobAccess,
        budget: RetrievalBudget,
        pin: PinnedKnowledgeResource,
        content: KnowledgeContent,
    ) -> dict[str, Any]:
        identity = (
            self.access.identity(access.actor_id)
            if self.access_mode is KnowledgeAccessMode.ONLINE
            else None
        )
        index = content.vectors.get(pin.index_code)
        qdrant = content.qdrant or self.qdrant
        if index is None:
            raise KnowledgeGovernanceError("knowledge_index_unavailable")

        def recheck() -> None:
            budget.check()
            if self.access.authenticate(token, "knowledge_search") != access:
                raise KnowledgeGovernanceError("knowledge_authorization_changed")
            if identity is not None and self.access.identity(access.actor_id) != identity:
                raise KnowledgeGovernanceError("knowledge_authorization_changed")
            self.resources.recheck(pin)
            budget.check()

        recheck()
        with stage("embedding"):
            self.embedding.check()
            recheck()
        with stage("vector_search"):
            qdrant.check(index)
            recheck()
        with stage("embedding"):
            vector = self.embedding.call([request.query], encode=True)["vectors"][0]
            recheck()
        selected_mode = retrieval_mode(index)
        with stage("vector_search"):
            candidates = retrieve_points(qdrant, index, vector, request.query, selected_mode)
            pool = candidate_pool(content.vectors, index, candidates)
            recheck()
        with stage("rerank"):
            ranked = rerank(pool, request.query, self.reranker)
            recheck()
        documents, timed_out = self._select_documents(
            ranked.documents,
            token=token,
            request=request,
            access=access,
            pin=pin,
            budget=budget,
            recheck=recheck,
        )
        with stage("response"):
            ids = tuple(document["document_id"] for document in documents)
            snapshots = content.records.document_snapshots(
                pin.knowledge_base_id, pin.source_id, ids
            )
            results: list[dict[str, Any]] = []
            for document in documents:
                snapshot = snapshots[document["document_id"]]
                if snapshot["current_revision_id"] != document["revision_id"]:
                    raise KnowledgeGovernanceError("knowledge_candidate_invalid")
                results.append(
                    {
                        **{
                            key: document[key]
                            for key in ("document_id", "revision_id", "retrieval_score")
                        },
                        "rank": len(results) + 1,
                        "index_id": pin.index_id,
                        "source_id": pin.source_id,
                        "work_item_uuid": snapshot["external_id"],
                        "number": snapshot["external_number"],
                        **{
                            key: snapshot[key]
                            for key in (
                                "title",
                                "document_kind",
                                "source_name",
                                "source_project_id",
                                "source_project_name",
                                "source_status_name",
                            )
                        },
                        **{
                            key: value.isoformat() if isinstance(value, datetime) else value
                            for key in ("source_updated_at", "ingested_at")
                            for value in (snapshot[key],)
                        },
                        "evidence": [
                            {**evidence, "text": pool.rows[evidence["chunk_id"]]["evidence_text"]}
                            for evidence in document["evidence"]
                        ],
                    }
                )
            recheck()
            pool.recheck(content.vectors, index)
            if (
                content.records.document_snapshots(pin.knowledge_base_id, pin.source_id, ids)
                != snapshots
            ):
                raise KnowledgeGovernanceError("knowledge_candidate_invalid")
            recheck()
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
                "access_mode": self.access_mode.value,
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
            "content_mode": "ingested_snapshot",
            "access_mode": self.access_mode.value,
            "content_scope": "matched_chunks",
            "retrieval_mode": selected_mode,
            "ranking_method": "cross_encoder",
            "ranking_profile_hash": ranked.profile_hash,
            "partial": partial,
            "partial_reason": "bounded_search" if partial else None,
        }

    def _select_documents(
        self,
        documents: list[dict[str, Any]],
        *,
        token: PrincipalToken,
        request: SearchRequest,
        access: KnowledgeJobAccess,
        pin: PinnedKnowledgeResource,
        budget: RetrievalBudget,
        recheck: Callable[[], None],
    ) -> tuple[list[dict[str, Any]], bool]:
        if self.access_mode is KnowledgeAccessMode.OFFLINE:
            return documents[: request.top_k], False
        assert self.readability is not None
        selected: list[dict[str, Any]] = []
        checked = 0
        while checked < min(len(documents), MAX_DOCUMENTS) and len(selected) < request.top_k:
            recheck()
            if budget.remaining() <= 1:
                return selected, True
            batch = documents[
                checked : checked + min(10, request.top_k - len(selected), MAX_DOCUMENTS - checked)
            ]
            bridge_request = ReadabilityRequest(
                pin.knowledge_base_id,
                pin.revision_id,
                pin.index_id,
                tuple(doc["evidence"][0]["chunk_id"] for doc in batch),
            )
            with stage("readability"):
                facts = ReadabilityCandidates.load(self.resources, bridge_request)
                raw = self.readability.check(token=token, request=bridge_request)
                verified = project_readability(raw, bridge_request, access, facts)
                facts.recheck(self.resources)
                recheck()
            selected.extend(
                document
                for document, reference in zip(batch, verified["items"], strict=True)
                if reference["readable"]
            )
            checked += len(batch)
        return selected, False
