"""知识运维授权与审计；存储和进程控制通过装配提供。"""

from contextlib import AbstractContextManager
from typing import Any, Protocol
from app.modules.knowledge.application.source_service import KnowledgeAdministration


class OperationsPort(Protocol):
    def transaction(self) -> AbstractContextManager[Any]: ...
    def submit(self, **values: Any) -> dict[str, Any]: ...
    def retry(self, operation_id: str) -> dict[str, Any]: ...
    def schedule(
        self, *, binding_id: str, enabled: bool, expected_revision: int
    ) -> dict[str, Any]: ...
    def configure(
        self, *, code: str, source_code: str, configuration: dict[str, Any], expected_revision: int
    ) -> dict[str, Any]: ...
    def configuration(self, *, binding_id: str) -> dict[str, Any]: ...
    def snapshot(self) -> dict[str, Any]: ...
    def events(self, **values: Any) -> dict[str, Any]: ...


class KnowledgeOperations:
    def __init__(self, admin: KnowledgeAdministration, store: OperationsPort):
        self.admin, self.store = admin, store

    def submit(self, *, actor_id: str, **values: Any) -> dict[str, Any]:
        self.admin.require_admin(actor_id)
        with self.store.transaction():
            result = self.store.submit(actor_id=actor_id, **values)
            self.admin.record(
                "ops_requested", actor_id=actor_id, identifier=result["id"], revision=0
            )
        return result

    def retry(self, *, actor_id: str, operation_id: str) -> dict[str, Any]:
        self.admin.require_admin(actor_id)
        with self.store.transaction():
            result = self.store.retry(operation_id)
            self.admin.record("ops_retried", actor_id=actor_id, identifier=operation_id, revision=0)
        return result

    def schedule(
        self, *, actor_id: str, binding_id: str, enabled: bool, expected_revision: int
    ) -> dict[str, Any]:
        self.admin.require_admin(actor_id)
        with self.store.transaction():
            result = self.store.schedule(
                binding_id=binding_id, enabled=enabled, expected_revision=expected_revision
            )
            self.admin.record(
                "schedule_changed",
                actor_id=actor_id,
                identifier=binding_id,
                revision=expected_revision,
            )
        return result

    def configure(self, *, actor_id: str, **values: Any) -> dict[str, Any]:
        self.admin.require_admin(actor_id)
        # 存储用例持有来源锁；审计不把配置和凭据引用写入 payload。
        result = self.store.configure(**values)
        self.admin.record(
            "sync_configured",
            actor_id=actor_id,
            identifier=result["id"],
            revision=result["revision"],
        )
        return result

    def configuration(self, *, actor_id: str, binding_id: str) -> dict[str, Any]:
        self.admin.require_admin(actor_id)
        return self.store.configuration(binding_id=binding_id)

    def snapshot(self) -> dict[str, Any]:
        return self.store.snapshot()

    def events(self, **values: Any) -> dict[str, Any]:
        return self.store.events(**values)
