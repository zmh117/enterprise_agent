from __future__ import annotations

from typing import Any

from app.modules.internal_tools.domain import (
    HandlerRegistry,
    HandlerRegistryError,
    build_builtin_handler_registry,
)
from app.modules.permission.application.permission_service import (
    PermissionService,
)
from app.modules.platform_config.infrastructure.handler_governance_repository import (
    HandlerGovernanceRepository,
)
from app.modules.platform_config.infrastructure.repository import (
    PlatformConfigRepository,
)
from app.shared.database import operation_unit_of_work
from app.shared.exceptions import (
    NonRetryableExecutionError,
    PermissionDenied,
)


class HandlerGovernanceService:
    def __init__(
        self,
        repository: HandlerGovernanceRepository,
        config_repository: PlatformConfigRepository,
        permission_service: PermissionService,
        *,
        registry: HandlerRegistry | None = None,
    ) -> None:
        self.repository = repository
        self.config_repository = config_repository
        self.permission_service = permission_service
        self.registry = registry or build_builtin_handler_registry()

    def require_admin(self, actor_id: str) -> None:
        if not actor_id:
            raise PermissionDenied(
                "Handler governance actor is required",
                safe_message="缺少 Handler 治理操作人",
            )
        self.permission_service.require_action(
            user_id=actor_id,
            resource_type="platform_config",
            resource_code="*",
            action="manage",
        )

    def catalog(self) -> list[dict[str, Any]]:
        publications = {
            (item["handler_id"], item["handler_version"]): item
            for item in self.repository.list_publications()
        }
        installations = {
            (item["handler_id"], item["handler_version"]): item
            for item in self.repository.list_installations()
        }
        return [
            {
                **definition.manifest(),
                "implementation_digest": (
                    definition.implementation_digest
                ),
                "installation": installations.get(
                    (
                        definition.handler_id,
                        definition.handler_version,
                    )
                ),
                "publication": publications.get(
                    (
                        definition.handler_id,
                        definition.handler_version,
                    )
                ),
            }
            for definition in self.registry.definitions()
        ]

    @operation_unit_of_work(lambda service: service.repository.database)
    def reconcile(
        self,
        *,
        actor_id: str,
        correlation_id: str = "",
    ) -> dict[str, int]:
        self.require_admin(actor_id)
        definitions = self.registry.definitions()
        rows = [
            self.repository.reconcile_installation(definition)
            for definition in definitions
        ]
        installed_keys = {
            (definition.handler_id, definition.handler_version)
            for definition in definitions
        }
        missing = self.repository.mark_unseen_missing(installed_keys)
        summary = {
            "installed": sum(
                row["installation_status"] == "INSTALLED"
                for row in rows
            ),
            "drifted": sum(
                row["installation_status"] == "DRIFTED"
                for row in rows
            ),
            "missing": missing,
        }
        self.config_repository.record_config_audit(
            entity_type="handler_registry",
            entity_id="code",
            action="reconcile",
            actor_id=actor_id,
            before={},
            after=summary,
            correlation_id=correlation_id,
        )
        return summary

    @operation_unit_of_work(lambda service: service.repository.database)
    def publish_payload(
        self,
        payload: dict[str, Any],
        *,
        actor_id: str,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        self.require_admin(actor_id)
        try:
            self.registry.reject_dynamic_governance_payload(payload)
        except HandlerRegistryError as exc:
            raise NonRetryableExecutionError(
                str(exc),
                safe_message="数据库不得保存动态 Handler 实现",
                error_code="dynamic_handler_forbidden",
            ) from exc
        unknown = set(payload).difference(
            {"handler_id", "handler_version"}
        )
        if unknown:
            raise NonRetryableExecutionError(
                f"Unsupported Handler governance fields: {sorted(unknown)}",
                safe_message="Handler 发布参数包含不允许的字段",
                error_code="handler_governance_invalid",
            )
        handler_id = str(payload.get("handler_id") or "")
        handler_version = str(payload.get("handler_version") or "")
        try:
            definition = self.registry.require(
                handler_id,
                handler_version,
            )
        except HandlerRegistryError as exc:
            raise NonRetryableExecutionError(
                str(exc),
                safe_message="代码中未安装该 Handler 精确版本",
                error_code="handler_not_installed",
            ) from exc
        installation = self.repository.get_installation(
            handler_id,
            handler_version,
        )
        if (
            installation["implementation_digest"]
            != definition.implementation_digest
        ):
            raise NonRetryableExecutionError(
                "Handler implementation digest drifted",
                safe_message="Handler 代码版本已漂移，禁止发布",
                error_code="handler_digest_drift",
            )
        publication = self.repository.publish(
            handler_id=handler_id,
            handler_version=handler_version,
            actor_id=actor_id,
        )
        self._audit(
            publication,
            action="publish",
            actor_id=actor_id,
            correlation_id=correlation_id,
        )
        return publication

    @operation_unit_of_work(lambda service: service.repository.database)
    def set_publication_status(
        self,
        publication_id: str,
        status: str,
        *,
        actor_id: str,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        self.require_admin(actor_id)
        before = self.repository.get_publication(publication_id)
        publication = self.repository.set_publication_status(
            publication_id=publication_id,
            status=status,
            actor_id=actor_id,
        )
        self._audit(
            publication,
            action=str(status).lower(),
            actor_id=actor_id,
            correlation_id=correlation_id,
            before=before,
        )
        return publication

    def _audit(
        self,
        publication: dict[str, Any],
        *,
        action: str,
        actor_id: str,
        correlation_id: str,
        before: dict[str, Any] | None = None,
    ) -> None:
        self.config_repository.record_config_audit(
            entity_type="handler_publication",
            entity_id=str(publication["id"]),
            action=action,
            actor_id=actor_id,
            before=before or {},
            after=publication,
            correlation_id=correlation_id,
        )
