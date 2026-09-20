"""可读性桥用例：双身份、候选与返回前复核；具体 JWT/SQL/HTTP 由适配器负责。"""

import threading
import time
from typing import Any

from app.modules.audit.application.audit_service import AuditService
from app.modules.knowledge.application.ports import ReadabilityBridgeGateway
from app.modules.knowledge.application.readability import (
    ReadabilityCandidates,
    ReadabilityRequest,
    project_readability,
)
from app.modules.knowledge.application.resource_service import KnowledgeResourceReader
from app.modules.knowledge.domain.governance import KnowledgeGovernanceError
from app.modules.knowledge.domain.models import KnowledgeJobAccess
from app.modules.knowledge.application.retrieval_budget import (
    MAX_RETRIEVAL_SECONDS,
    knowledge_entry,
)


class KnowledgeReadabilityBridge:
    def __init__(
        self,
        gateway: ReadabilityBridgeGateway,
        resources: KnowledgeResourceReader,
        audit: AuditService,
    ) -> None:
        self.gateway, self.resources, self.audit = gateway, resources, audit
        self._slots = threading.BoundedSemaphore(4)

    def authenticate(self, service_token: str, knowledge_token: str) -> KnowledgeJobAccess:
        return self.gateway.authenticate(service_token, knowledge_token)

    @knowledge_entry
    def check(
        self,
        *,
        service_token: str,
        knowledge_token: str,
        request: ReadabilityRequest,
        deadline_ms: int | None = None,
    ) -> dict[str, Any]:
        access = self.authenticate(service_token, knowledge_token)
        if request.knowledge_base_id not in access.knowledge_base_ids:
            raise KnowledgeGovernanceError("knowledge_job_denied")
        if not self._slots.acquire(blocking=False):
            raise KnowledgeGovernanceError("knowledge_readability_busy")
        try:
            with self.gateway.budget(access.job_id, deadline_ms=deadline_ms).activate():
                started = time.monotonic()
                candidates = ReadabilityCandidates.load(self.resources, request)
                identity = self.gateway.identity_fingerprint(access.actor_id, candidates)
                # 签发该 Job 冻结的完整 ONES scope，不允许调用者指定或缩减。
                result = self.gateway.request_ones(access.job_id, request)
                safe = project_readability(result, request, access, candidates)
                if self.authenticate(service_token, knowledge_token) != access:
                    raise KnowledgeGovernanceError("knowledge_authorization_changed")
                candidates.recheck(self.resources)
                if self.gateway.identity_fingerprint(access.actor_id, candidates) != identity:
                    raise KnowledgeGovernanceError("knowledge_authorization_changed")
                if time.monotonic() - started >= MAX_RETRIEVAL_SECONDS:
                    raise KnowledgeGovernanceError("knowledge_readability_timeout")
                self.audit.record(
                    "knowledge.readability.checked",
                    status="success",
                    summary="知识候选已完成本人可读性检查",
                    actor_id=access.actor_id,
                    job_id=access.job_id,
                    payload={
                        "knowledge_base_id": request.knowledge_base_id,
                        "resource_revision_id": request.resource_revision_id,
                    },
                )
                return safe
        finally:
            self._slots.release()
