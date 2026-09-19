"""固定内部候选可读性入口；只接收库内块引用，不接受 ONES UUID 或连接参数。"""

import threading
import time
from typing import Any

from app.modules.knowledge.domain.governance import KnowledgeGovernanceError, checked_identifier
from app.modules.knowledge.infrastructure.job_access import KnowledgeJobGate
from app.modules.knowledge.domain.models import KnowledgeJobAccess
from app.modules.knowledge.application.resource_service import KnowledgeResourceReader
from app.modules.knowledge.application.readability import (
    READABILITY_PATH as READABILITY_PATH,
    ReadabilityRequest as ReadabilityRequest,
    ReadabilityCandidates,
)
from app.shared.exceptions import AppError
from app.modules.knowledge.infrastructure.reader_access import job_budget
from services.ones_mcp_server.knowledge_verification import OnesWorkItemReferenceService


class OnesKnowledgeReadability:
    def __init__(
        self,
        gate: KnowledgeJobGate,
        resources: KnowledgeResourceReader,
        detail: OnesWorkItemReferenceService,
    ) -> None:
        self.gate = gate
        self.resources = resources
        self.detail = detail
        self._slots = threading.BoundedSemaphore(4)

    def _identity(
        self, token: str, binding: dict[str, Any]
    ) -> tuple[dict[str, Any], tuple[str, ...]]:
        claims = self.detail.authenticate(token)
        principal = self.detail.resolver.resolve(
            claims, tool_identifier=self.detail.tool_identifier
        )
        identity = self.gate.database.execute_one(
            "select tenant_code from user_external_identity where id=?",
            (principal.external_identity_id,),
        )
        if (
            not identity
            or identity["tenant_code"] != self.resources.instance_code
            or binding["instance_code"] != self.resources.instance_code
            or binding["target_hash"] != self.resources.target_hash
            or binding["team_id"] != principal.team_id
        ):
            raise KnowledgeGovernanceError("knowledge_source_unavailable")
        return claims, (
            principal.actor_user_id,
            principal.external_identity_id,
            principal.provider_user_id,
            principal.team_id,
        )

    def check(
        self, *, token: str, request: ReadabilityRequest, deadline_ms: int | None = None
    ) -> dict[str, Any]:
        claims = self.detail.authenticate(token)
        # 在解析候选、索引和 Provider I/O 之前校验本人的 Job/Tool/KB 授权。
        access = self.gate.require(
            job_id=claims["job_id"],
            actor_id=claims["sub"],
            knowledge_base_id=request.knowledge_base_id,
        )
        if not self._slots.acquire(blocking=False):
            raise KnowledgeGovernanceError("knowledge_readability_busy")
        try:
            with job_budget(self.gate.database, access.job_id, deadline_ms=deadline_ms).activate():
                return self._check(token, request, access)
        finally:
            self._slots.release()

    def _check(
        self, token: str, request: ReadabilityRequest, access: KnowledgeJobAccess
    ) -> dict[str, Any]:
        started = time.monotonic()
        candidates = ReadabilityCandidates.load(self.resources, request)
        pin, binding = candidates.pin, candidates.binding
        claims, identity = self._identity(token, binding)
        evidence, documents = candidates.evidence, candidates.documents
        references: dict[str, dict[str, Any]] = {}
        for document_id in sorted(documents):
            if time.monotonic() - started >= 60:
                raise KnowledgeGovernanceError("knowledge_readability_timeout")
            self.gate.recheck(access)
            claims, current_identity = self._identity(token, binding)
            if current_identity != identity:
                raise KnowledgeGovernanceError("knowledge_authorization_changed")
            document = documents[document_id]
            try:
                reference = self.detail.invoke(
                    claims=claims,
                    arguments={"work_item_uuid": checked_identifier(document["external_id"])},
                    correlation_id="",
                    invocation_id="",
                )
            except AppError as exc:
                if exc.error_code not in {
                    "ones_provider_forbidden",
                    "ones_provider_operation_unavailable",
                }:
                    raise
                references[document_id] = {"readable": False}
                continue
            if (
                reference.get("task_id") != document["external_id"]
                or reference.get("project_id") != document["source_project_id"]
                or reference.get("team_id") != binding["team_id"]
            ):
                raise KnowledgeGovernanceError("knowledge_source_changed")
            references[document_id] = {
                "readable": True,
                "task_id": reference["task_id"],
                "number": reference["number"],
                "document_id": document_id,
                "revision_id": document["current_revision_id"],
                "source_binding_id": binding["id"],
            }
        # 任何 Provider 故障都不会落入空命中；检查结束后仍须校验 JWT、当前授权和成员版本。
        _, current_identity = self._identity(token, binding)
        self.gate.recheck(access)
        candidates.recheck(self.resources)
        if current_identity != identity:
            raise KnowledgeGovernanceError("knowledge_authorization_changed")
        if time.monotonic() - started >= 60:
            raise KnowledgeGovernanceError("knowledge_readability_timeout")
        return {
            "knowledge_base_id": pin.knowledge_base_id,
            "resource_revision_id": pin.revision_id,
            "index_id": pin.index_id,
            "job_id": access.job_id,
            "actor_id": access.actor_id,
            "items": [
                {"chunk_id": chunk, **references[evidence[chunk]["document_id"]]}
                for chunk in request.chunk_ids
            ],
        }
