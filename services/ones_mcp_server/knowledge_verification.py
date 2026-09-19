"""仅内部可用的来源核验；复用 ONES Principal 和详情查询，不注册模型工具。"""

from collections import OrderedDict
from dataclasses import asdict
import threading
import time
from typing import Any

from app.modules.knowledge.infrastructure.governance_repository import GovernanceStore
from app.modules.knowledge.domain.governance import KnowledgeGovernanceError
from app.modules.knowledge.infrastructure.ones_verifier import SOURCE_VERIFICATION_PATH as SOURCE_VERIFICATION_PATH
from app.modules.knowledge.domain.vector_contract import fingerprint
from app.modules.permission.application.permission_service import PermissionService
from app.shared.database import Database
from services.ones_mcp_server.errors import invalid_provider_response
from services.ones_mcp_server.tools.base import ProviderCall
from services.ones_mcp_server.tools.query_services import OnesWorkItemDetailService
from services.ones_mcp_server.auth.principal import ResolvedOnesPrincipal


class OnesWorkItemReferenceService(OnesWorkItemDetailService):
    """详情 Operation 的内存投影；正文不得进入核验响应及核验审计。"""

    def call_provider(
        self, principal: ResolvedOnesPrincipal, arguments: dict[str, Any]
    ) -> ProviderCall:
        call = super().call_provider(principal, arguments)
        item = call.output.get("work_item")
        if (
            not isinstance(item, dict)
            or item.get("uuid") != arguments["work_item_uuid"]
            or not isinstance(item.get("project"), dict)
        ):
            raise invalid_provider_response("ones_provider_schema_invalid")
        reference = {
            "task_id": item["uuid"],
            "project_id": item["project"]["uuid"],
            "number": item["number"],
            "team_id": principal.team_id,
        }
        return ProviderCall(reference, call.request_summary, {"projection": "work_item_reference"})


class SourceVerificationLimiter:
    """每进程最多四个在途核验；同 Job 每分钟一次，计时槽最多 256 项。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._recent: OrderedDict[str, float] = OrderedDict()
        self._active: set[str] = set()

    def acquire(self, job_id: str) -> None:
        with self._lock:
            current = time.monotonic()
            while self._recent and next(iter(self._recent.values())) <= current - 60:
                self._recent.popitem(last=False)
            if (
                job_id in self._recent
                or job_id in self._active
                or len(self._active) >= 4
                or len(self._recent) >= 256
            ):
                raise KnowledgeGovernanceError("knowledge_verification_busy")
            self._recent[job_id] = current
            self._active.add(job_id)

    def release(self, job_id: str) -> None:
        with self._lock:
            self._active.discard(job_id)


class OnesSourceVerification:
    def __init__(
        self,
        database: Database,
        permissions: PermissionService,
        detail: OnesWorkItemReferenceService,
        *,
        instance_code: str,
        target_hash: str,
    ) -> None:
        self.store = GovernanceStore(database)
        self.permissions = permissions
        self.detail = detail
        self.instance_code = instance_code
        self.target_hash = target_hash
        self.limiter = SourceVerificationLimiter()

    def _authorize(self, token: str, binding: dict[str, Any]) -> dict[str, Any]:
        # 每次检查都认证原 JWT，而非只相信第一次解码的 claims；保留完整 scope 校验。
        claims = self.detail.authenticate(token)
        principal = self.detail.resolver.resolve(
            claims, tool_identifier=self.detail.tool_identifier
        )
        self.permissions.require_action(
            user_id=principal.actor_user_id,
            resource_type="platform_config",
            resource_code="*",
            action="manage",
        )
        identity = self.store.database.execute_one(
            "select tenant_code from user_external_identity where id=?",
            (principal.external_identity_id,),
        )
        if (
            not identity
            or identity["tenant_code"] != self.instance_code
            or principal.team_id != binding["team_id"]
            or binding["instance_code"] != self.instance_code
            or binding["target_hash"] != self.target_hash
            or binding["state"] != "PENDING"
        ):
            raise KnowledgeGovernanceError("knowledge_source_unavailable")
        return claims

    def verify(self, *, token: str, binding_id: str) -> dict[str, Any]:
        self.detail.authenticate(token)
        binding = self.store.get("source_binding", binding_id)
        claims = self._authorize(token, binding)
        job_id = str(claims["job_id"])
        self.limiter.acquire(job_id)
        try:
            items = self.store.source_items(binding["source_id"])
            if (
                self.store.source_hash(items) != binding["corpus_hash"]
                or len(items) != binding["document_count"]
            ):
                raise KnowledgeGovernanceError("knowledge_source_changed")
            sample = items[:20]
            started = time.monotonic()
            for item in sample:
                if time.monotonic() - started >= 60:
                    raise KnowledgeGovernanceError("knowledge_verification_failed")
                claims = self._authorize(token, binding)
                reference = self.detail.invoke(
                    claims=claims,
                    arguments={"work_item_uuid": item.task_id},
                    correlation_id="",
                    invocation_id="",
                )
                if (
                    reference.get("task_id") != item.task_id
                    or reference.get("project_id") != item.project_id
                    or reference.get("team_id") != binding["team_id"]
                ):
                    raise KnowledgeGovernanceError("knowledge_verification_failed")
            # 不返回允许结果的跨调用缓存；终态 Job、撤权、换源和旧 JWT 均在返回前拒绝。
            self._authorize(token, binding)
            if (
                time.monotonic() - started >= 60
                or self.store.get("source_binding", binding_id) != binding
                or self.store.source_items(binding["source_id"]) != items
            ):
                raise KnowledgeGovernanceError("knowledge_source_changed")
            return {
                "binding_id": binding_id,
                "job_id": job_id,
                "actor_id": str(claims["sub"]),
                "target_hash": binding["target_hash"],
                "corpus_hash": binding["corpus_hash"],
                "sample_hash": fingerprint([asdict(item) for item in sample]),
                "checked_count": len(sample),
            }
        finally:
            self.limiter.release(job_id)
