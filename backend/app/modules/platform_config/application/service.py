from __future__ import annotations

from pathlib import Path
from typing import Any

from app.modules.platform_config.application.runtime_config import (
    RuntimeConfigRegistry,
    RuntimeConfigSnapshotBuilder,
    validate_runtime_config_definition_payload,
)
from app.modules.permission.application.permission_service import PermissionService
from app.modules.platform_config.application.governed_resources import (
    GovernedResourceService,
)
from app.modules.platform_config.application.loki_draft_discovery import (
    HttpLokiDraftDiscoveryGateway,
    LokiDraftDiscoveryService,
)
from app.modules.platform_config.application.database_resource_verifier import (
    GovernedResourceTechnicalVerifier,
)
from app.modules.platform_config.infrastructure.governed_resource_repository import (
    GovernedResourceRepository,
)
from app.shared.database import operation_unit_of_work
from app.shared.exceptions import (
    PermissionDenied,
)

from ..infrastructure.repository import PlatformConfigRepository
from .importer import PlatformTopologyYamlImporter
from .legacy_env_import import LegacyEnvSecretImportService
from .secrets import SecretProviderPort
from .secret_usage import PlatformSecretUsageService
from .validation import (
    assert_no_secret_payload,
    assert_no_resource_placement,
    coerce_runtime_value,
    normalize_aliases,
    normalize_json_object,
    validate_config_value_type,
    validate_code,
    validate_engine,
    validate_runtime_scope_type,
    validate_secret_provider,
    validate_secret_ref,
    validate_status,
    validate_topology_code,
)


class PlatformConfigService:
    def __init__(
        self,
        repository: PlatformConfigRepository,
        permission_service: PermissionService,
        secret_provider: SecretProviderPort,
        *,
        environment: str = "production",
    ) -> None:
        self.repository = repository
        self.permission_service = permission_service
        self.secret_provider = secret_provider
        self.legacy_env_secret_importer = LegacyEnvSecretImportService(
            repository,
            secret_provider,
        )
        self.secret_usage_service = PlatformSecretUsageService(repository)
        self.yaml_importer = PlatformTopologyYamlImporter(repository)
        self.runtime_registry = RuntimeConfigRegistry(repository)
        self.runtime_snapshot_builder = RuntimeConfigSnapshotBuilder(repository)
        self.governed_resources = GovernedResourceService(
            GovernedResourceRepository(repository.database),
            repository,
            permission_service,
            verifier=GovernedResourceTechnicalVerifier(
                resolve_secret=secret_provider.resolve,
                allow_privileged_database_accounts=environment == "local",
            ),
        )
        self.loki_draft_discovery = LokiDraftDiscoveryService(
            GovernedResourceRepository(repository.database),
            permission_service,
            HttpLokiDraftDiscoveryGateway(
                resolve_secret=secret_provider.resolve,
            ),
        )

    def require_admin(self, actor_id: str) -> None:
        if not actor_id:
            raise PermissionDenied(
                "Platform config actor is required",
                safe_message="缺少平台配置操作人",
            )
        self.permission_service.require_action(
            user_id=actor_id,
            resource_type="platform_config",
            resource_code="*",
            action="manage",
        )

    def require_secret_admin(self, actor_id: str) -> None:
        if not actor_id:
            raise PermissionDenied(
                "Secret administrator actor is required",
                safe_message="缺少凭据管理员操作人",
            )
        self.permission_service.require_action(
            user_id=actor_id,
            resource_type="secret",
            resource_code="*",
            action="manage",
        )

    def list_environments(self, *, include_disabled: bool = True) -> list[dict[str, Any]]:
        return self.repository.list_environments(include_disabled=include_disabled)

    @operation_unit_of_work(lambda service: service.repository.database)
    def upsert_environment(
        self,
        payload: dict[str, Any],
        *,
        actor_id: str,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        self.require_admin(actor_id)
        assert_no_resource_placement(payload, context="业务 topology")
        code = validate_topology_code(
            str(payload.get("code") or ""),
            field="environment_code",
            level="Environment",
        )
        before = self.repository.get_environment_by_code(code)
        entity = self.repository.upsert_environment(
            code=code,
            display_name=str(payload.get("display_name") or ""),
            status=validate_status(str(payload.get("status") or "enabled")).value,
            aliases=normalize_aliases(payload.get("aliases")),
            metadata=normalize_json_object(payload.get("metadata"), field="metadata"),
        )
        self._audit("environment", entity, "upsert", actor_id, before, correlation_id)
        return entity

    @operation_unit_of_work(lambda service: service.repository.database)
    def set_environment_status(
        self, code: str, status: str, *, actor_id: str, correlation_id: str = ""
    ) -> dict[str, Any]:
        self.require_admin(actor_id)
        before = self.repository.get_environment_by_code(code)
        entity = self.repository.set_environment_status(
            validate_code(code), validate_status(status).value
        )
        self._audit("environment", entity, status, actor_id, before, correlation_id)
        return entity

    def list_bases(
        self, *, environment_code: str | None = None, include_disabled: bool = True
    ) -> list[dict[str, Any]]:
        return self.repository.list_bases(
            environment_code=environment_code,
            include_disabled=include_disabled,
        )

    @operation_unit_of_work(lambda service: service.repository.database)
    def upsert_base(
        self, payload: dict[str, Any], *, actor_id: str, correlation_id: str = ""
    ) -> dict[str, Any]:
        self.require_admin(actor_id)
        assert_no_resource_placement(payload, context="业务 topology")
        environment_code = validate_topology_code(
            str(payload.get("environment_code") or ""),
            field="environment_code",
            level="Environment",
        )
        code = validate_topology_code(
            str(payload.get("code") or ""),
            field="base_code",
            level="Base",
        )
        before = self.repository.get_base_by_code(environment_code=environment_code, code=code)
        entity = self.repository.upsert_base(
            environment_code=environment_code,
            code=code,
            engine=validate_engine(str(payload.get("engine") or "")),
            display_name=str(payload.get("display_name") or ""),
            status=validate_status(str(payload.get("status") or "enabled")).value,
            aliases=normalize_aliases(payload.get("aliases")),
            metadata=normalize_json_object(payload.get("metadata"), field="metadata"),
        )
        self._audit("base", entity, "upsert", actor_id, before, correlation_id)
        return entity

    @operation_unit_of_work(lambda service: service.repository.database)
    def set_base_status(
        self,
        *,
        environment_code: str,
        code: str,
        status: str,
        actor_id: str,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        self.require_admin(actor_id)
        before = self.repository.get_base_by_code(environment_code=environment_code, code=code)
        entity = self.repository.set_base_status(
            environment_code=validate_code(environment_code, field="environment_code"),
            code=validate_code(code),
            status=validate_status(status).value,
        )
        self._audit("base", entity, status, actor_id, before, correlation_id)
        return entity

    def list_workshops(
        self,
        *,
        environment_code: str | None = None,
        base_code: str | None = None,
        include_disabled: bool = True,
    ) -> list[dict[str, Any]]:
        return self.repository.list_workshops(
            environment_code=environment_code,
            base_code=base_code,
            include_disabled=include_disabled,
        )

    @operation_unit_of_work(lambda service: service.repository.database)
    def upsert_workshop(
        self, payload: dict[str, Any], *, actor_id: str, correlation_id: str = ""
    ) -> dict[str, Any]:
        self.require_admin(actor_id)
        assert_no_resource_placement(payload, context="业务 topology")
        environment_code = validate_topology_code(
            str(payload.get("environment_code") or ""),
            field="environment_code",
            level="Environment",
        )
        base_code = validate_topology_code(
            str(payload.get("base_code") or ""),
            field="base_code",
            level="Base",
        )
        code = validate_topology_code(
            str(payload.get("code") or ""),
            field="workshop_code",
            level="Workshop",
        )
        before = self.repository.get_workshop_by_code(
            environment_code=environment_code,
            base_code=base_code,
            code=code,
        )
        loki_labels = normalize_json_object(payload.get("loki_labels"), field="loki_labels")
        entity = self.repository.upsert_workshop(
            environment_code=environment_code,
            base_code=base_code,
            code=code,
            display_name=str(payload.get("display_name") or ""),
            table_prefix=str(payload.get("table_prefix") or ""),
            redis_key_prefix=str(payload.get("redis_key_prefix") or ""),
            loki_labels={str(k): str(v) for k, v in loki_labels.items()},
            status=validate_status(str(payload.get("status") or "enabled")).value,
            aliases=normalize_aliases(payload.get("aliases")),
            metadata=normalize_json_object(payload.get("metadata"), field="metadata"),
        )
        self._audit("workshop", entity, "upsert", actor_id, before, correlation_id)
        return entity

    @operation_unit_of_work(lambda service: service.repository.database)
    def set_workshop_status(
        self,
        *,
        environment_code: str,
        base_code: str,
        code: str,
        status: str,
        actor_id: str,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        self.require_admin(actor_id)
        before = self.repository.get_workshop_by_code(
            environment_code=environment_code,
            base_code=base_code,
            code=code,
        )
        entity = self.repository.set_workshop_status(
            environment_code=validate_code(environment_code, field="environment_code"),
            base_code=validate_code(base_code, field="base_code"),
            code=validate_code(code),
            status=validate_status(status).value,
        )
        self._audit("workshop", entity, status, actor_id, before, correlation_id)
        return entity

    def list_secret_references(self, *, include_disabled: bool = True) -> list[dict[str, Any]]:
        return self.repository.list_secret_references(include_disabled=include_disabled)

    @operation_unit_of_work(lambda service: service.repository.database)
    def upsert_secret_reference(
        self, payload: dict[str, Any], *, actor_id: str, correlation_id: str = ""
    ) -> dict[str, Any]:
        self.require_secret_admin(actor_id)
        code = validate_code(str(payload.get("code") or ""))
        ref = validate_secret_ref(str(payload.get("ref") or ""))
        provider = validate_secret_provider(str(payload.get("provider") or ref.split(":", 1)[0]))
        self._require_available_platform_secret(ref)
        before = self.repository.get_secret_reference_by_code(code)
        entity = self.repository.upsert_secret_reference(
            code=code,
            provider=provider.value,
            ref=ref,
            purpose=str(payload.get("purpose") or ""),
            status=validate_status(str(payload.get("status") or "enabled")).value,
            metadata=normalize_json_object(payload.get("metadata"), field="metadata"),
        )
        self._audit("secret_reference", entity, "upsert", actor_id, before, correlation_id)
        return entity

    def list_platform_secrets(self, *, include_disabled: bool = True) -> list[dict[str, Any]]:
        return [
            self._public_secret(item)
            for item in self.repository.list_platform_secrets(include_disabled=include_disabled)
        ]

    def get_platform_secret(self, code: str) -> dict[str, Any]:
        secret = self.repository.get_platform_secret_by_code(validate_code(code))
        if not secret:
            from app.shared.exceptions import NotFound

            raise NotFound(f"Platform secret not found: {code}")
        return self._public_secret(secret)

    def legacy_env_secret_report(self) -> dict[str, Any]:
        return self.legacy_env_secret_importer.report()

    def get_platform_secret_usage(self, code: str) -> dict[str, Any]:
        secret = self.repository.get_platform_secret_by_code(validate_code(code))
        if not secret:
            from app.shared.exceptions import NotFound

            raise NotFound(f"Platform secret not found: {code}")
        dependencies = self.secret_usage_service.dependencies(
            secret_id=str(secret["id"]),
            secret_ref=str(secret["ref"]),
        )
        return {
            "secret": self._public_secret(secret),
            "usage_count": len(dependencies),
            "active_usage_count": sum(1 for item in dependencies if item["active"]),
            "dependencies": dependencies,
        }

    @operation_unit_of_work(lambda service: service.repository.database)
    def import_legacy_env_secret(
        self,
        payload: dict[str, Any],
        *,
        actor_id: str,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        self.require_secret_admin(actor_id)
        return self.legacy_env_secret_importer.import_reference(
            env_ref=str(payload.get("env_ref") or ""),
            code=str(payload.get("code") or ""),
            actor_id=actor_id,
            correlation_id=correlation_id,
            dry_run=bool(payload.get("dry_run", True)),
            expected_digest=str(payload.get("expected_digest") or ""),
        )

    @operation_unit_of_work(lambda service: service.repository.database)
    def create_platform_secret(
        self, payload: dict[str, Any], *, actor_id: str, correlation_id: str = ""
    ) -> dict[str, Any]:
        self.require_secret_admin(actor_id)
        code = validate_code(str(payload.get("code") or ""))
        before = self.repository.get_platform_secret_by_code(code)
        value = str(payload.pop("value", "") or "")
        try:
            secret = self._secret_provider().create_secret(
                code=code,
                value=value,
                purpose=str(payload.get("purpose") or ""),
                actor_id=actor_id,
                metadata=normalize_json_object(payload.get("metadata"), field="metadata"),
            )
        finally:
            value = ""
        public = self._public_secret(secret)
        self._audit("platform_secret", public, "create", actor_id, before, correlation_id)
        return public

    @operation_unit_of_work(lambda service: service.repository.database)
    def rotate_platform_secret(
        self, code: str, payload: dict[str, Any], *, actor_id: str, correlation_id: str = ""
    ) -> dict[str, Any]:
        self.require_secret_admin(actor_id)
        before = self.repository.get_platform_secret_by_code(validate_code(code))
        value = str(payload.pop("value", "") or "")
        try:
            secret = self._secret_provider().rotate_secret(
                code=code,
                value=value,
                actor_id=actor_id,
            )
        finally:
            value = ""
        public = self._public_secret(secret)
        self._audit("platform_secret", public, "rotate", actor_id, before, correlation_id)
        return public

    @operation_unit_of_work(lambda service: service.repository.database)
    def disable_platform_secret(
        self, code: str, *, actor_id: str, correlation_id: str = ""
    ) -> dict[str, Any]:
        self.require_secret_admin(actor_id)
        before = self.repository.get_platform_secret_by_code(validate_code(code))
        secret = self._secret_provider().disable_secret(code=code, actor_id=actor_id)
        public = self._public_secret(secret)
        self._audit("platform_secret", public, "disable", actor_id, before, correlation_id)
        return public

    def list_provider_contracts(self) -> list[dict[str, Any]]:
        return self.governed_resources.provider_contracts.public_contracts()

    @operation_unit_of_work(lambda service: service.repository.database)
    def ensure_runtime_config_definitions(
        self, *, actor_id: str = "", correlation_id: str = ""
    ) -> dict[str, Any]:
        if actor_id:
            self.require_admin(actor_id)
        before_revision = self.repository.runtime_config_revision()
        summary = self.runtime_registry.ensure_builtin_definitions()
        after_revision = self.repository.runtime_config_revision()
        if actor_id and (summary["created"] or summary["updated"]):
            self.repository.record_config_audit(
                entity_type="runtime_config_definition",
                entity_id="builtin",
                action="sync",
                actor_id=actor_id,
                before={"revision": before_revision},
                after={"revision": after_revision, **summary},
                correlation_id=correlation_id,
            )
        return {"revision": after_revision, **summary}

    def runtime_config_env_migration(self) -> list[dict[str, Any]]:
        return self.runtime_registry.env_migration_list()

    def list_runtime_config_definitions(
        self, *, include_disabled: bool = True
    ) -> list[dict[str, Any]]:
        return self.repository.list_runtime_config_definitions(include_disabled=include_disabled)

    def runtime_config_definition_diagnostics(self) -> list[dict[str, Any]]:
        missing = self.runtime_registry.missing_builtin_definition_keys()
        if not missing:
            return []
        return [
            {
                "code": "runtime_config_definition_missing",
                "keys": missing,
            }
        ]

    @operation_unit_of_work(lambda service: service.repository.database)
    def upsert_runtime_config_definition(
        self, payload: dict[str, Any], *, actor_id: str, correlation_id: str = ""
    ) -> dict[str, Any]:
        self.require_admin(actor_id)
        normalized = validate_runtime_config_definition_payload(payload)
        key = validate_code(normalized["key"], field="key")
        before = self.repository.get_runtime_config_definition(key)
        reconciliation = self.repository.upsert_runtime_config_definition(
            key=key,
            value_type=normalized["value_type"],
            default=normalized["default"],
            sensitive=normalized["sensitive"],
            bootstrap_only=normalized["bootstrap_only"],
            service_names=normalized["service_names"],
            description=normalized["description"],
            status=validate_status(normalized["status"]).value,
        )
        entity = reconciliation.entity
        if reconciliation.outcome != "unchanged":
            self._audit(
                "runtime_config_definition",
                entity,
                "upsert",
                actor_id,
                before,
                correlation_id,
            )
        return entity

    def list_runtime_config_values(self, *, include_disabled: bool = True) -> list[dict[str, Any]]:
        return [
            self._public_runtime_config_value(item)
            for item in self.repository.list_runtime_config_values(
                include_disabled=include_disabled
            )
        ]

    @operation_unit_of_work(lambda service: service.repository.database)
    def upsert_runtime_config_value(
        self, payload: dict[str, Any], *, actor_id: str, correlation_id: str = ""
    ) -> dict[str, Any]:
        self.require_admin(actor_id)
        key = validate_code(str(payload.get("key") or ""), field="key")
        definition = self.repository.get_runtime_config_definition(key)
        if not definition:
            from app.shared.exceptions import NotFound

            raise NotFound(f"Runtime config definition not found: {key}")
        if definition.get("bootstrap_only"):
            raise ValueError(f"{key} is bootstrap-only and must be managed by deployment env")
        value_type = validate_config_value_type(str(definition["value_type"]))
        scope_type = validate_runtime_scope_type(str(payload.get("scope_type") or "global"))
        scope_code = str(payload.get("scope_code") or "*")
        service_name = str(payload.get("service_name") or "")
        before = self.repository.find_runtime_config_value(
            key=key,
            scope_type=scope_type.value,
            scope_code=scope_code,
            service_name=service_name,
        )
        secret_ref = ""
        value: Any = None
        if definition.get("sensitive") or value_type.value == "secret_ref":
            secret_ref = validate_secret_ref(
                str(payload.get("secret_ref") or payload.get("value") or "")
            )
            self._require_available_platform_secret(secret_ref)
        else:
            value = coerce_runtime_value(payload.get("value"), value_type)
            assert_no_secret_payload({key: value})
        entity = self.repository.upsert_runtime_config_value(
            key=key,
            scope_type=scope_type.value,
            scope_code=scope_code,
            service_name=service_name,
            value=value,
            secret_ref=secret_ref,
            status=validate_status(str(payload.get("status") or "enabled")).value,
        )
        public = self._public_runtime_config_value(entity)
        self._audit("runtime_config_value", public, "upsert", actor_id, before, correlation_id)
        return public

    @operation_unit_of_work(lambda service: service.repository.database)
    def set_runtime_config_value_status(
        self, value_id: str, status: str, *, actor_id: str, correlation_id: str = ""
    ) -> dict[str, Any]:
        self.require_admin(actor_id)
        before = self.repository.get_runtime_config_value(value_id)
        entity = self.repository.set_runtime_config_value_status(
            validate_code(value_id, field="value_id"),
            validate_status(status).value,
        )
        public = self._public_runtime_config_value(entity)
        self._audit("runtime_config_value", public, status, actor_id, before, correlation_id)
        return public

    def runtime_config_snapshot(
        self, *, service_name: str = "", scopes: dict[str, str] | None = None
    ) -> dict[str, Any]:
        return self.runtime_snapshot_builder.build_snapshot(
            service_name=service_name,
            scopes=scopes or {},
        )

    @operation_unit_of_work(lambda service: service.repository.database)
    def import_topology_yaml(
        self,
        *,
        yaml_text: str | None = None,
        path: str | Path | None = None,
        actor_id: str,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        self.require_admin(actor_id)
        if yaml_text is not None:
            return self.yaml_importer.import_text(
                yaml_text,
                actor_id=actor_id,
                correlation_id=correlation_id,
            )
        if path is None:
            raise ValueError("yaml_text or path is required")
        return self.yaml_importer.import_file(
            path,
            actor_id=actor_id,
            correlation_id=correlation_id,
        )

    def _audit(
        self,
        entity_type: str,
        after: dict[str, Any],
        action: str,
        actor_id: str,
        before: dict[str, Any] | None,
        correlation_id: str,
    ) -> None:
        self.repository.record_config_audit(
            entity_type=entity_type,
            entity_id=str(after["id"]),
            action=action,
            actor_id=actor_id,
            before=before or {},
            after=after,
            correlation_id=correlation_id,
        )

    def _secret_provider(self) -> SecretProviderPort:
        return self.secret_provider

    def resolve_secret(self, ref: str) -> str:
        return self._secret_provider().resolve(ref)

    def _require_available_platform_secret(self, ref: str) -> None:
        secret = self.repository.get_platform_secret_by_ref(ref)
        if not secret or not secret.get("configured"):
            from .validation import PlatformConfigValidationError

            raise PlatformConfigValidationError(
                f"Platform secret is unavailable: {ref}",
                safe_message="所选凭据不存在、已禁用或没有活动版本",
            )

    def _public_secret(self, secret: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": secret["id"],
            "code": secret["code"],
            "provider": secret["provider"],
            "secret_ref": secret["ref"],
            "purpose": secret.get("purpose") or "",
            "status": secret["status"],
            "active_version": int(secret.get("active_version") or 0),
            "configured": bool(secret.get("configured")),
            "masked_summary": secret.get("masked_summary") or "",
            "metadata": secret.get("metadata") or {},
            "revision": int(secret.get("revision") or 0),
            "updated_at": secret.get("updated_at"),
        }

    def _public_runtime_config_value(self, value: dict[str, Any]) -> dict[str, Any]:
        sensitive = bool(value.get("sensitive")) or bool(value.get("secret_ref"))
        return {
            "id": value["id"],
            "key": value["key"],
            "scope_type": value["scope_type"],
            "scope_code": value["scope_code"],
            "service_name": value.get("service_name") or "",
            "value": None if sensitive else value.get("value"),
            "secret_ref": value.get("secret_ref") or "",
            "configured": bool(value.get("secret_ref") or value.get("value") is not None),
            "sensitive": sensitive,
            "status": value["status"],
            "revision": int(value.get("revision") or 0),
        }
