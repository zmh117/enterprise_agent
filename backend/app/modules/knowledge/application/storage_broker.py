"""固定知识连接凭据入口；服务身份与当前用户授权共同满足，绝非 Secret 代理。"""

from collections.abc import Callable
from dataclasses import dataclass
import threading
from typing import Any

from app.modules.audit.application.audit_service import AuditService
from app.modules.knowledge.application.ports import GovernanceRepository, ReadabilityBridgeGateway
from app.modules.knowledge.domain.governance import KnowledgeGovernanceError, checked_identifier
from app.modules.knowledge.domain.storage_connection import stored_config
from app.modules.knowledge.application.retrieval_budget import knowledge_entry


STORAGE_PATH = "/api/internal/knowledge/storage-connection"


@dataclass(frozen=True)
class StorageConnectionRequest:
    knowledge_base_id: str
    resource_revision_id: str

    @classmethod
    def parse(cls, value: Any) -> "StorageConnectionRequest":
        if not isinstance(value, dict) or set(value) != {
            "knowledge_base_id",
            "resource_revision_id",
        }:
            raise KnowledgeGovernanceError("knowledge_input_invalid")
        return cls(
            checked_identifier(value["knowledge_base_id"]),
            checked_identifier(value["resource_revision_id"]),
        )


class KnowledgeStorageBroker:
    def __init__(
        self,
        gateway: ReadabilityBridgeGateway,
        store: GovernanceRepository,
        credentials: Callable[[dict[str, Any], str, str], dict[str, str]],
        audit: AuditService,
    ) -> None:
        self.gateway, self.store, self.credentials, self.audit = gateway, store, credentials, audit
        self._slots = threading.BoundedSemaphore(4)

    def authenticate(self, service_token: str, knowledge_token: str) -> Any:
        return self.gateway.authenticate(service_token, knowledge_token)

    def _published(
        self, request: StorageConnectionRequest
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        resources = self.store.enabled_resources(request.knowledge_base_id)
        if (
            len(resources) != 1
            or resources[0]["published_revision_id"] != request.resource_revision_id
        ):
            raise KnowledgeGovernanceError("knowledge_resource_unavailable")
        revision = self.store.get("retrieval_revision", request.resource_revision_id)
        if revision["resource_id"] != resources[0]["id"] or not revision["published_at"]:
            raise KnowledgeGovernanceError("knowledge_resource_unavailable")
        return resources[0], revision

    @knowledge_entry
    def check(
        self,
        *,
        service_token: str,
        knowledge_token: str,
        request: StorageConnectionRequest,
        deadline_ms: int | None = None,
    ) -> dict[str, Any]:
        access = self.authenticate(service_token, knowledge_token)
        if request.knowledge_base_id not in access.knowledge_base_ids:
            raise KnowledgeGovernanceError("knowledge_job_denied")
        if not self._slots.acquire(blocking=False):
            raise KnowledgeGovernanceError("knowledge_readability_busy")
        try:
            budget = self.gateway.budget(access.job_id, deadline_ms=deadline_ms)
            with budget.activate():
                budget.check()
                before = self._published(request)
                config = stored_config(before[1].get("storage_config_json"))
                if config is None:
                    raise KnowledgeGovernanceError("knowledge_storage_config_invalid")
                resolved = self.credentials(
                    config, request.knowledge_base_id, request.resource_revision_id
                )
                if (
                    self.authenticate(service_token, knowledge_token) != access
                    or self._published(request) != before
                ):
                    raise KnowledgeGovernanceError("knowledge_authorization_changed")
                # 安全审计先完成；失败时不下发任何连接凭据。
                self.audit.record(
                    "knowledge.storage.resolved",
                    status="success",
                    summary="已解析授权知识连接",
                    actor_id=access.actor_id,
                    job_id=access.job_id,
                    payload={
                        "knowledge_base_id": request.knowledge_base_id,
                        "resource_revision_id": request.resource_revision_id,
                    },
                )
                budget.check()
                return {
                    "knowledge_base_id": request.knowledge_base_id,
                    "resource_revision_id": request.resource_revision_id,
                    "config": config,
                    "credentials": resolved,
                }
        finally:
            self._slots.release()
