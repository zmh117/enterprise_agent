"""来源绑定用例；权限、核验与事务顺序由用例协调。"""

from dataclasses import asdict
from typing import Any
import uuid
from app.modules.audit.application.audit_service import AuditService
from app.modules.permission.application.permission_service import PermissionService
from app.modules.knowledge.domain.governance import (
    KnowledgeGovernanceError,
    SourceItem,
    checked_identifier,
    checked_hash,
    checked_revision,
)
from app.modules.knowledge.domain.vector_contract import fingerprint
from app.modules.knowledge.domain.identity import now
from app.modules.knowledge.application.ports import GovernanceRepository, SourceTechnicalVerifier
from app.shared.exceptions import PermissionDenied


class KnowledgeAdministration:
    def __init__(
        self,
        store: GovernanceRepository,
        permission_service: PermissionService,
        audit_service: AuditService,
    ) -> None:
        self.store = store
        self.permissions = permission_service
        self.audit = audit_service

    def require_admin(self, actor_id: str) -> None:
        if not actor_id:
            raise PermissionDenied(
                "Knowledge administrator required", safe_message="缺少知识资源操作人"
            )
        self.permissions.require_action(
            user_id=actor_id, resource_type="platform_config", resource_code="*", action="manage"
        )

    def record(
        self,
        action: str,
        *,
        actor_id: str,
        identifier: str,
        revision: int,
        error: str | None = None,
    ) -> None:
        self.audit.record(
            "knowledge." + action,
            status="FAILED" if error else "SUCCEEDED",
            summary="知识治理状态变更",
            actor_id=actor_id,
            payload={"id": identifier, "revision": revision, "error_code": error},
        )


class SourceBindingService(KnowledgeAdministration):
    def catalog(self) -> dict[str, Any]:
        return self.store.source_catalog()

    def __init__(
        self,
        store: GovernanceRepository,
        permission_service: PermissionService,
        audit_service: AuditService,
        verifier: SourceTechnicalVerifier | None = None,
    ) -> None:
        super().__init__(store, permission_service, audit_service)
        self.verifier = verifier

    def _verifier(self, binding: dict[str, Any] | None = None) -> SourceTechnicalVerifier:
        verifier = self.verifier
        if verifier is None:
            raise KnowledgeGovernanceError("knowledge_verifier_unavailable")
        checked_identifier(verifier.instance_code)
        checked_hash(verifier.target_hash)
        if binding and (
            binding["instance_code"] != verifier.instance_code
            or binding["target_hash"] != verifier.target_hash
        ):
            raise KnowledgeGovernanceError("knowledge_source_changed")
        return verifier

    def create(
        self,
        *,
        actor_id: str,
        source_id: str,
        instance_code: str,
        team_id: str,
        expected_revision: int,
        batch_attested: bool,
        attestation_hash: str,
    ) -> dict[str, Any]:
        self.require_admin(actor_id)
        checked_identifier(source_id)
        checked_identifier(instance_code)
        checked_identifier(team_id)
        checked_hash(attestation_hash)
        checked_revision(expected_revision)
        if batch_attested is not True or instance_code != self._verifier().instance_code:
            raise KnowledgeGovernanceError("knowledge_input_invalid")
        with self.store.source_lock(source_id), self.store.unit_of_work():
            self.store.get("source", source_id, lock=True)
            if self.store.latest_source_revision(source_id) != expected_revision:
                raise KnowledgeGovernanceError("knowledge_revision_conflict")
            items = self.store.source_items(source_id)
            timestamp = now()
            # 换版立即撤销旧核验；新修订不能自动沿用旧实例或 Team 的证明。
            self.store.revoke_source_bindings(source_id, actor_id, timestamp)
            identifier = str(uuid.uuid4())
            self.store.add(
                "source_binding",
                {
                    "id": identifier,
                    "source_id": source_id,
                    "revision": expected_revision + 1,
                    "instance_code": instance_code,
                    "target_hash": self._verifier().target_hash,
                    "team_id": team_id,
                    "state": "PENDING",
                    "attestation_hash": attestation_hash,
                    "corpus_hash": self.store.source_hash(items),
                    "document_count": len(items),
                    "created_by": actor_id,
                    "created_at": timestamp,
                },
            )
            self.record(
                "source.created",
                actor_id=actor_id,
                identifier=identifier,
                revision=expected_revision + 1,
            )
            return self.store.get("source_binding", identifier)

    def assert_current(
        self, binding: dict[str, Any], *, verified: bool = True
    ) -> tuple[SourceItem, ...]:
        verifier = self._verifier(binding)
        return self.store.assert_current_source(
            binding,
            instance_code=verifier.instance_code,
            target_hash=verifier.target_hash,
            verified=verified,
        )

    def verify(self, *, actor_id: str, binding_id: str, job_id: str) -> dict[str, Any]:
        self.require_admin(actor_id)
        checked_identifier(job_id)
        binding = self.store.get("source_binding", binding_id)
        items = self.assert_current(binding, verified=False)
        # 固定确定性抽样仅为交叉检查；完整批次证明来自显式人工确认，不以抽样替代。
        sample = items[:20]
        try:
            if (
                self._verifier(binding).verify(
                    actor_id=actor_id,
                    job_id=job_id,
                    binding_id=binding_id,
                    team_id=binding["team_id"],
                    items=sample,
                )
                is not True
            ):
                raise KnowledgeGovernanceError("knowledge_verification_failed")
        except Exception:
            self.record(
                "source.verification",
                actor_id=actor_id,
                identifier=binding_id,
                revision=binding["revision"],
                error="knowledge_verification_failed",
            )
            raise KnowledgeGovernanceError("knowledge_verification_failed") from None
        with self.store.source_lock(binding["source_id"]), self.store.unit_of_work():
            self.require_admin(actor_id)
            current = self.store.get("source_binding", binding_id, lock=True)
            if current != binding:
                raise KnowledgeGovernanceError("knowledge_revision_conflict")
            self.assert_current(current, verified=False)
            digest = fingerprint(
                {
                    "binding": binding_id,
                    "job_id": job_id,
                    "target": binding["target_hash"],
                    "team": binding["team_id"],
                    "corpus": binding["corpus_hash"],
                    "checked": [asdict(item) for item in sample],
                }
            )
            self.store.verify_binding(binding_id, digest, len(sample), actor_id, job_id)
            self.record(
                "source.verified",
                actor_id=actor_id,
                identifier=binding_id,
                revision=binding["revision"],
            )
            return self.store.get("source_binding", binding_id)

    def revoke(self, *, actor_id: str, binding_id: str) -> None:
        self.require_admin(actor_id)
        with self.store.unit_of_work():
            binding = self.store.get("source_binding", binding_id, lock=True)
            if binding["state"] == "REVOKED":
                return
            self.store.revoke_binding(binding_id, actor_id)

            self.record(
                "source.revoked",
                actor_id=actor_id,
                identifier=binding_id,
                revision=binding["revision"],
            )
