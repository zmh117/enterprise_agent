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
from app.modules.platform_config.application.builtin_tool_verifier import (
    BuiltinToolVerifier,
    verification_input_hash,
)
from app.modules.platform_config.infrastructure.repository import (
    PlatformConfigRepository,
)
from app.shared.database import operation_unit_of_work
from app.shared.exceptions import (
    NonRetryableExecutionError,
    NotFound,
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
        verifier: BuiltinToolVerifier | None = None,
    ) -> None:
        self.repository = repository
        self.config_repository = config_repository
        self.permission_service = permission_service
        self.registry = registry or build_builtin_handler_registry()
        self.verifier = verifier or BuiltinToolVerifier()

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

    def require_builtin_action(self, actor_id: str, action: str) -> None:
        if not actor_id:
            raise PermissionDenied(
                "Built-in Tool governance actor is required",
                safe_message="缺少内置工具治理操作人",
            )
        self.permission_service.require_action(
            user_id=actor_id,
            resource_type="builtin_tool",
            resource_code="*",
            action=action,
        )

    def catalog(self) -> list[dict[str, Any]]:
        installations = {
            (item["tool_identifier"], item["handler_version"]): item
            for item in self.repository.list_builtin_installations()
        }
        verifications: dict[str, list[dict[str, Any]]] = {}
        for item in self.repository.list_builtin_verifications():
            verifications.setdefault(str(item["tool_identifier"]), []).append(
                self._public_verification(item)
            )
        releases: dict[str, list[dict[str, Any]]] = {}
        for item in self.repository.list_builtin_releases():
            releases.setdefault(str(item["tool_identifier"]), []).append(
                self._public_release(item)
            )
        result: list[dict[str, Any]] = []
        for definition in self.registry.definitions():
            installation = installations.get(
                (definition.tool_identifier, definition.handler_version)
            )
            result.append(
                {
                    "manifest": definition.manifest(),
                    "code_implementation_digest": (
                        definition.implementation_digest
                    ),
                    "installation": installation,
                    "verifications": verifications.get(
                        definition.tool_identifier,
                        [],
                    ),
                    "releases": releases.get(
                        definition.tool_identifier,
                        [],
                    ),
                    "effective_status": self._effective_status(
                        installation,
                        releases.get(definition.tool_identifier, []),
                    ),
                }
            )
        return result

    def detail(self, tool_identifier: str) -> dict[str, Any]:
        for item in self.catalog():
            if item["manifest"]["tool_identifier"] == tool_identifier:
                return item
        raise NotFound(
            f"Built-in Tool not found: {tool_identifier}",
            safe_message="未找到内置只读工具",
        )

    def _public_release(self, item: dict[str, Any]) -> dict[str, Any]:
        release_id = str(item["id"])
        return {
            key: item[key]
            for key in (
                "id",
                "tool_identifier",
                "release_revision",
                "tool_semantic_version",
                "handler_version",
                "implementation_digest",
                "manifest_hash",
                "public_schema_hash",
                "verification_id",
                "status",
                "published_by",
                "published_at",
                "deprecated_by",
                "deprecated_at",
                "disabled_by",
                "disabled_at",
                "archived_by",
                "archived_at",
            )
        } | {
            "dependencies": self.repository.builtin_release_dependencies(
                release_id
            ),
            "lifecycle_audit": self.repository.list_builtin_lifecycle_audit(
                release_id
            ),
        }

    @staticmethod
    def _public_verification(item: dict[str, Any]) -> dict[str, Any]:
        return {
            key: item[key]
            for key in (
                "id",
                "tool_identifier",
                "handler_version",
                "implementation_digest",
                "verifier_version",
                "normalized_input_hash",
                "status",
                "result_summary",
                "safe_error_summary",
                "verified_by",
                "verified_at",
            )
        }

    @staticmethod
    def _effective_status(
        installation: dict[str, Any] | None,
        releases: list[dict[str, Any]],
    ) -> str:
        if installation is None:
            return "NOT_RECONCILED"
        if installation["installation_status"] != "INSTALLED":
            return str(installation["installation_status"])
        if any(item["status"] in {"ACTIVE", "DEPRECATED"} for item in releases):
            return "CALLABLE"
        if releases:
            return "LIFECYCLE_BLOCKED"
        return "UNPUBLISHED"

    @operation_unit_of_work(lambda service: service.repository.database)
    def reconcile(
        self,
        *,
        actor_id: str,
        correlation_id: str = "",
    ) -> dict[str, int]:
        self.require_builtin_action(actor_id, "reconcile")
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
    def verify_payload(
        self,
        payload: dict[str, Any],
        *,
        actor_id: str,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        self.require_builtin_action(actor_id, "verify")
        unknown = set(payload).difference(
            {"tool_identifier", "handler_version"}
        )
        if unknown:
            raise NonRetryableExecutionError(
                "Built-in Tool manual verification fields are forbidden",
                safe_message="验证结果只能由代码中的固定机器 Verifier 产生",
                error_code="builtin_tool_manual_verification_forbidden",
            )
        tool_identifier = str(payload.get("tool_identifier") or "")
        handler_version = str(payload.get("handler_version") or "")
        try:
            definition = self.registry.require(
                tool_identifier,
                handler_version,
            )
        except HandlerRegistryError as exc:
            raise NonRetryableExecutionError(
                "Built-in Tool exact implementation is missing",
                safe_message="代码中未安装该内置工具精确版本",
                error_code="builtin_tool_installation_missing",
            ) from exc
        installation = self.repository.find_builtin_installation(
            tool_identifier,
            handler_version,
        )
        if installation is None or installation["installation_status"] == "MISSING":
            raise NonRetryableExecutionError(
                "Built-in Tool installation is missing",
                safe_message="内置工具安装记录缺失，无法验证",
                error_code="builtin_tool_installation_missing",
            )
        if (
            installation["installation_status"] != "INSTALLED"
            or installation["implementation_digest"]
            != definition.implementation_digest
        ):
            raise NonRetryableExecutionError(
                "Built-in Tool installation digest drifted",
                safe_message="内置工具代码版本已漂移，无法验证",
                error_code="builtin_tool_installation_drifted",
            )
        result = self.verifier.verify(definition)
        evidence = self.repository.record_builtin_verification(
            tool_identifier=definition.tool_identifier,
            handler_version=definition.handler_version,
            implementation_digest=definition.implementation_digest,
            verifier_version=definition.verifier_plan.verifier_version,
            normalized_input_hash=verification_input_hash(definition),
            status=result.status,
            result_summary=result.summary,
            safe_error_summary=result.safe_error_summary,
            actor_id=actor_id,
        )
        self.config_repository.record_config_audit(
            entity_type="builtin_tool_verification",
            entity_id=str(evidence["id"]),
            action="verify",
            actor_id=actor_id,
            before={},
            after={
                "tool_identifier": evidence["tool_identifier"],
                "handler_version": evidence["handler_version"],
                "implementation_digest_prefix": str(
                    evidence["implementation_digest"]
                )[:12],
                "verifier_version": evidence["verifier_version"],
                "status": evidence["status"],
            },
            correlation_id=correlation_id,
        )
        return evidence

    @operation_unit_of_work(lambda service: service.repository.database)
    def publish_builtin_tool_payload(
        self,
        payload: dict[str, Any],
        *,
        actor_id: str,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        self.require_builtin_action(actor_id, "publish")
        unknown = set(payload).difference(
            {
                "tool_identifier",
                "handler_version",
                "verification_id",
                "idempotency_key",
            }
        )
        if unknown:
            raise NonRetryableExecutionError(
                "Built-in Tool publish fields are invalid",
                safe_message="内置工具发布参数包含不允许的字段",
                error_code="builtin_tool_manifest_invalid",
            )
        tool_identifier = str(payload.get("tool_identifier") or "")
        handler_version = str(payload.get("handler_version") or "")
        verification_id = str(payload.get("verification_id") or "")
        idempotency_key = str(payload.get("idempotency_key") or "").strip()
        if not idempotency_key or len(idempotency_key) > 128:
            raise NonRetryableExecutionError(
                "Built-in Tool publish idempotency key is invalid",
                safe_message="发布幂等键无效",
                error_code="builtin_tool_publish_idempotency_conflict",
            )
        try:
            definition = self.registry.require(
                tool_identifier,
                handler_version,
            )
        except HandlerRegistryError as exc:
            raise NonRetryableExecutionError(
                "Built-in Tool exact implementation is missing",
                safe_message="代码中未安装该内置工具精确版本",
                error_code="builtin_tool_installation_missing",
            ) from exc
        installation = self.repository.find_builtin_installation(
            tool_identifier,
            handler_version,
        )
        if installation is None or installation["installation_status"] == "MISSING":
            raise NonRetryableExecutionError(
                "Built-in Tool installation is missing",
                safe_message="内置工具安装记录缺失，禁止发布",
                error_code="builtin_tool_installation_missing",
            )
        if (
            installation["installation_status"] != "INSTALLED"
            or installation["implementation_digest"]
            != definition.implementation_digest
        ):
            raise NonRetryableExecutionError(
                "Built-in Tool installation digest drifted",
                safe_message="内置工具代码版本已漂移，禁止发布",
                error_code="builtin_tool_installation_drifted",
            )
        evidence = self.repository.find_builtin_verification_by_id(
            verification_id
        )
        if evidence is None:
            raise NonRetryableExecutionError(
                "Built-in Tool verification evidence is missing",
                safe_message="缺少当前实现的机器验证证据",
                error_code="builtin_tool_verification_missing",
            )
        if evidence["status"] != "PASSED":
            raise NonRetryableExecutionError(
                "Built-in Tool verification evidence failed",
                safe_message="机器验证未通过，禁止发布",
                error_code="builtin_tool_verification_failed",
            )
        if (
            evidence["tool_identifier"] != definition.tool_identifier
            or evidence["handler_version"] != definition.handler_version
            or evidence["implementation_digest"]
            != definition.implementation_digest
            or evidence["verifier_version"]
            != definition.verifier_plan.verifier_version
            or evidence["normalized_input_hash"]
            != verification_input_hash(definition)
        ):
            raise NonRetryableExecutionError(
                "Built-in Tool verification evidence is stale",
                safe_message="机器验证证据与当前代码内容不一致",
                error_code="builtin_tool_verification_stale",
            )
        existing = self.repository.find_builtin_release_by_idempotency_key(
            idempotency_key
        )
        release = self.repository.publish_builtin_release(
            definition=definition,
            verification_id=verification_id,
            idempotency_key=idempotency_key,
            actor_id=actor_id,
            correlation_id=correlation_id,
        )
        if existing is None and release["idempotency_key"] == idempotency_key:
            self.config_repository.record_config_audit(
                entity_type="builtin_tool_release",
                entity_id=str(release["id"]),
                action="publish",
                actor_id=actor_id,
                before={},
                after={
                    "tool_identifier": release["tool_identifier"],
                    "release_revision": release["release_revision"],
                    "handler_version": release["handler_version"],
                    "implementation_digest_prefix": str(
                        release["implementation_digest"]
                    )[:12],
                    "status": release["status"],
                    "verification_id": release["verification_id"],
                },
                correlation_id=correlation_id,
            )
        return release

    @operation_unit_of_work(lambda service: service.repository.database)
    def set_builtin_tool_release_status(
        self,
        release_id: str,
        status: str,
        *,
        reason_code: str,
        actor_id: str,
        verification_id: str = "",
        correlation_id: str = "",
    ) -> dict[str, Any]:
        self.require_builtin_action(actor_id, "lifecycle")
        normalized = status.upper()
        if normalized not in {
            "ACTIVE",
            "DEPRECATED",
            "DISABLED",
            "ARCHIVED",
        }:
            raise NonRetryableExecutionError(
                "Built-in Tool Release lifecycle state is invalid",
                safe_message="内置工具 Release 生命周期状态无效",
                error_code="builtin_tool_release_lifecycle_invalid",
            )
        if not reason_code.strip():
            raise NonRetryableExecutionError(
                "Built-in Tool Release lifecycle reason is required",
                safe_message="生命周期变更必须填写原因",
                error_code="builtin_tool_release_lifecycle_invalid",
            )
        before = self.repository.get_builtin_release(release_id)
        current = str(before["status"])
        if current == "ARCHIVED":
            raise NonRetryableExecutionError(
                "Archived Built-in Tool Release is terminal",
                safe_message="已归档的内置工具 Release 不可恢复",
                error_code="builtin_tool_release_lifecycle_invalid",
            )
        transitions = {
            "ACTIVE": {"DEPRECATED", "DISABLED", "ARCHIVED"},
            "DEPRECATED": {"DISABLED", "ARCHIVED"},
            "DISABLED": {"ACTIVE", "ARCHIVED"},
        }
        if normalized not in transitions.get(current, set()):
            raise NonRetryableExecutionError(
                "Built-in Tool Release lifecycle transition is invalid",
                safe_message="内置工具 Release 生命周期不能执行该转换",
                error_code="builtin_tool_release_lifecycle_invalid",
            )
        if normalized == "ARCHIVED":
            dependencies = self.repository.builtin_release_dependencies(
                release_id
            )
            if sum(dependencies.values()) > 0:
                raise NonRetryableExecutionError(
                    "Built-in Tool Release still has active dependencies",
                    safe_message="Release 仍被活动发布或可恢复 Job 引用，不能归档",
                    error_code="builtin_tool_release_dependency_in_use",
                )
        if normalized == "ACTIVE":
            self._assert_restore_evidence(
                before,
                verification_id=verification_id,
            )
        release = self.repository.set_builtin_release_status(
            release_id=release_id,
            status=normalized,
            reason_code=reason_code.strip(),
            actor_id=actor_id,
            correlation_id=correlation_id,
        )
        self.config_repository.record_config_audit(
            entity_type="builtin_tool_release",
            entity_id=release_id,
            action=normalized.lower(),
            actor_id=actor_id,
            before={"status": current},
            after={
                "tool_identifier": release["tool_identifier"],
                "release_revision": release["release_revision"],
                "handler_version": release["handler_version"],
                "implementation_digest_prefix": str(
                    release["implementation_digest"]
                )[:12],
                "verification_id": release["verification_id"],
                "status": release["status"],
                "reason_code": reason_code.strip(),
            },
            correlation_id=correlation_id,
        )
        return release

    def _assert_restore_evidence(
        self,
        release: dict[str, Any],
        *,
        verification_id: str,
    ) -> None:
        try:
            definition = self.registry.require(
                str(release["tool_identifier"]),
                str(release["handler_version"]),
            )
        except HandlerRegistryError as exc:
            raise NonRetryableExecutionError(
                "Built-in Tool installation is missing",
                safe_message="精确代码实现缺失，不能恢复 Release",
                error_code="builtin_tool_installation_missing",
            ) from exc
        installation = self.repository.find_builtin_installation(
            definition.tool_identifier,
            definition.handler_version,
        )
        if installation is None or installation["installation_status"] == "MISSING":
            raise NonRetryableExecutionError(
                "Built-in Tool installation is missing",
                safe_message="精确代码实现缺失，不能恢复 Release",
                error_code="builtin_tool_installation_missing",
            )
        if (
            installation["installation_status"] != "INSTALLED"
            or installation["implementation_digest"]
            != definition.implementation_digest
            or release["implementation_digest"]
            != definition.implementation_digest
        ):
            raise NonRetryableExecutionError(
                "Built-in Tool installation digest drifted",
                safe_message="精确代码实现已漂移，不能恢复 Release",
                error_code="builtin_tool_installation_drifted",
            )
        evidence = self.repository.find_builtin_verification_by_id(
            verification_id
        )
        if evidence is None:
            raise NonRetryableExecutionError(
                "Built-in Tool verification evidence is missing",
                safe_message="恢复 Release 需要当前机器验证证据",
                error_code="builtin_tool_verification_missing",
            )
        if (
            evidence["status"] != "PASSED"
            or evidence["tool_identifier"] != definition.tool_identifier
            or evidence["handler_version"] != definition.handler_version
            or evidence["implementation_digest"]
            != definition.implementation_digest
            or evidence["verifier_version"]
            != definition.verifier_plan.verifier_version
            or evidence["normalized_input_hash"]
            != verification_input_hash(definition)
        ):
            raise NonRetryableExecutionError(
                "Built-in Tool verification evidence is stale or failed",
                safe_message="恢复证据与当前精确实现不一致",
                error_code="builtin_tool_verification_stale",
            )

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
