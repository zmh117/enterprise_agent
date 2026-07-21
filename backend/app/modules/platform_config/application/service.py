from __future__ import annotations

from pathlib import Path
from typing import Any

from app.modules.platform_config.application.runtime_config import (
    RuntimeConfigRegistry,
    RuntimeConfigSnapshotBuilder,
    validate_runtime_config_definition_payload,
)
from app.modules.permission.application.permission_service import PermissionService
from app.shared.exceptions import PermissionDenied

from ..infrastructure.repository import PlatformConfigRepository
from .importer import PlatformTopologyYamlImporter
from .secrets import EncryptedDbSecretProvider
from .snapshot import PlatformTopologySnapshotBuilder, RuntimeTopologySnapshot
from .validation import (
    assert_no_secret_payload,
    coerce_runtime_value,
    assert_readonly_tool_scope,
    normalize_aliases,
    normalize_json_list,
    normalize_json_object,
    normalize_oracle_database_config,
    normalize_redis_resource_config,
    validate_config_value_type,
    validate_access_effect,
    validate_code,
    validate_engine,
    validate_resource_kind,
    validate_runtime_scope_type,
    validate_scope_type,
    validate_secret_provider,
    validate_secret_ref,
    validate_status,
    validate_subject_type,
)


class PlatformConfigService:
    def __init__(
        self,
        repository: PlatformConfigRepository,
        permission_service: PermissionService,
    ) -> None:
        self.repository = repository
        self.permission_service = permission_service
        self.snapshot_builder = PlatformTopologySnapshotBuilder(repository)
        self.yaml_importer = PlatformTopologyYamlImporter(repository)
        self.runtime_registry = RuntimeConfigRegistry(repository)
        self.runtime_snapshot_builder = RuntimeConfigSnapshotBuilder(repository)

    def require_admin(self, actor_id: str) -> None:
        if not actor_id:
            raise PermissionDenied(
                "Platform config actor is required",
                safe_message="Platform config actor is required",
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
                safe_message="Secret administrator actor is required",
            )
        self.permission_service.require_action(
            user_id=actor_id,
            resource_type="secret",
            resource_code="*",
            action="manage",
        )

    def list_environments(self, *, include_disabled: bool = True) -> list[dict[str, Any]]:
        return self.repository.list_environments(include_disabled=include_disabled)

    def upsert_environment(
        self,
        payload: dict[str, Any],
        *,
        actor_id: str,
        correlation_id: str = "",
    ) -> dict[str, Any]:
        self.require_admin(actor_id)
        code = validate_code(str(payload.get("code") or ""))
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

    def upsert_base(
        self, payload: dict[str, Any], *, actor_id: str, correlation_id: str = ""
    ) -> dict[str, Any]:
        self.require_admin(actor_id)
        environment_code = validate_code(
            str(payload.get("environment_code") or ""), field="environment_code"
        )
        code = validate_code(str(payload.get("code") or ""))
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

    def upsert_workshop(
        self, payload: dict[str, Any], *, actor_id: str, correlation_id: str = ""
    ) -> dict[str, Any]:
        self.require_admin(actor_id)
        environment_code = validate_code(
            str(payload.get("environment_code") or ""), field="environment_code"
        )
        base_code = validate_code(str(payload.get("base_code") or ""), field="base_code")
        code = validate_code(str(payload.get("code") or ""))
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

    def upsert_secret_reference(
        self, payload: dict[str, Any], *, actor_id: str, correlation_id: str = ""
    ) -> dict[str, Any]:
        self.require_secret_admin(actor_id)
        code = validate_code(str(payload.get("code") or ""))
        ref = validate_secret_ref(str(payload.get("ref") or ""))
        provider = validate_secret_provider(str(payload.get("provider") or ref.split(":", 1)[0]))
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

    def create_platform_secret(
        self, payload: dict[str, Any], *, actor_id: str, correlation_id: str = ""
    ) -> dict[str, Any]:
        self.require_secret_admin(actor_id)
        code = validate_code(str(payload.get("code") or ""))
        before = self.repository.get_platform_secret_by_code(code)
        secret = self._secret_provider().create_secret(
            code=code,
            value=str(payload.get("value") or ""),
            purpose=str(payload.get("purpose") or ""),
            actor_id=actor_id,
            metadata=normalize_json_object(payload.get("metadata"), field="metadata"),
        )
        public = self._public_secret(secret)
        self._audit("platform_secret", public, "create", actor_id, before, correlation_id)
        return public

    def rotate_platform_secret(
        self, code: str, payload: dict[str, Any], *, actor_id: str, correlation_id: str = ""
    ) -> dict[str, Any]:
        self.require_secret_admin(actor_id)
        before = self.repository.get_platform_secret_by_code(validate_code(code))
        secret = self._secret_provider().rotate_secret(
            code=code,
            value=str(payload.get("value") or ""),
            actor_id=actor_id,
        )
        public = self._public_secret(secret)
        self._audit("platform_secret", public, "rotate", actor_id, before, correlation_id)
        return public

    def disable_platform_secret(
        self, code: str, *, actor_id: str, correlation_id: str = ""
    ) -> dict[str, Any]:
        self.require_secret_admin(actor_id)
        before = self.repository.get_platform_secret_by_code(validate_code(code))
        secret = self._secret_provider().disable_secret(code=code, actor_id=actor_id)
        public = self._public_secret(secret)
        self._audit("platform_secret", public, "disable", actor_id, before, correlation_id)
        return public

    def list_resource_bindings(self, *, include_disabled: bool = True) -> list[dict[str, Any]]:
        return self.repository.list_resource_bindings(include_disabled=include_disabled)

    def upsert_resource_binding(
        self,
        payload: dict[str, Any],
        *,
        actor_id: str,
        correlation_id: str = "",
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        self.require_admin(actor_id)
        code = validate_code(str(payload.get("code") or ""))
        config = normalize_json_object(payload.get("config"), field="config")
        assert_no_secret_payload(config)
        secret_refs = {
            str(key): validate_secret_ref(str(value))
            for key, value in normalize_json_object(
                payload.get("secret_refs"), field="secret_refs"
            ).items()
        }
        kind = validate_resource_kind(str(payload.get("resource_kind") or ""))
        if kind.value == "redis":
            config = normalize_redis_resource_config(config)
        engine = (
            validate_engine(str(payload.get("engine") or ""))
            if kind.value == "database"
            else payload.get("engine")
        )
        if kind.value == "database" and engine == "oracle":
            config = normalize_oracle_database_config(config)
        before = self.repository.get_resource_binding_by_code(code)
        entity = self.repository.upsert_resource_binding(
            code=code,
            scope_type=validate_scope_type(str(payload.get("scope_type") or "")).value,
            environment_code=payload.get("environment_code"),
            base_code=payload.get("base_code"),
            workshop_code=payload.get("workshop_code"),
            resource_kind=kind.value,
            connector_id=payload.get("connector_id"),
            engine=engine if kind.value == "database" else None,
            config=config,
            secret_refs=secret_refs,
            status=validate_status(str(payload.get("status") or "enabled")).value,
            expected_revision=expected_revision,
        )
        self._audit("resource_binding", entity, "upsert", actor_id, before, correlation_id)
        return entity

    def ensure_runtime_config_definitions(
        self, *, actor_id: str = "", correlation_id: str = ""
    ) -> dict[str, Any]:
        if actor_id:
            self.require_admin(actor_id)
        before_revision = self.repository.runtime_config_revision()
        self.runtime_registry.ensure_builtin_definitions()
        after_revision = self.repository.runtime_config_revision()
        if actor_id:
            self.repository.record_config_audit(
                entity_type="runtime_config_definition",
                entity_id="builtin",
                action="sync",
                actor_id=actor_id,
                before={"revision": before_revision},
                after={"revision": after_revision},
                correlation_id=correlation_id,
            )
        return {"revision": after_revision}

    def runtime_config_env_migration(self) -> list[dict[str, Any]]:
        return self.runtime_registry.env_migration_list()

    def list_runtime_config_definitions(
        self, *, include_disabled: bool = True
    ) -> list[dict[str, Any]]:
        return self.repository.list_runtime_config_definitions(include_disabled=include_disabled)

    def upsert_runtime_config_definition(
        self, payload: dict[str, Any], *, actor_id: str, correlation_id: str = ""
    ) -> dict[str, Any]:
        self.require_admin(actor_id)
        normalized = validate_runtime_config_definition_payload(payload)
        key = validate_code(normalized["key"], field="key")
        before = self.repository.get_runtime_config_definition(key)
        entity = self.repository.upsert_runtime_config_definition(
            key=key,
            value_type=normalized["value_type"],
            default=normalized["default"],
            sensitive=normalized["sensitive"],
            bootstrap_only=normalized["bootstrap_only"],
            service_names=normalized["service_names"],
            description=normalized["description"],
            status=validate_status(normalized["status"]).value,
        )
        self._audit("runtime_config_definition", entity, "upsert", actor_id, before, correlation_id)
        return entity

    def list_runtime_config_values(self, *, include_disabled: bool = True) -> list[dict[str, Any]]:
        return [
            self._public_runtime_config_value(item)
            for item in self.repository.list_runtime_config_values(
                include_disabled=include_disabled
            )
        ]

    def upsert_runtime_config_value(
        self, payload: dict[str, Any], *, actor_id: str, correlation_id: str = ""
    ) -> dict[str, Any]:
        self.require_admin(actor_id)
        key = validate_code(str(payload.get("key") or ""), field="key")
        definition = self.repository.get_runtime_config_definition(key)
        if not definition:
            self.runtime_registry.ensure_builtin_definitions()
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
        self.runtime_registry.ensure_builtin_definitions()
        return self.runtime_snapshot_builder.build_snapshot(
            service_name=service_name,
            scopes=scopes or {},
        )

    def set_resource_binding_status(
        self, code: str, status: str, *, actor_id: str, correlation_id: str = ""
    ) -> dict[str, Any]:
        self.require_admin(actor_id)
        before = self.repository.get_resource_binding_by_code(code)
        entity = self.repository.set_resource_binding_status(
            validate_code(code), validate_status(status).value
        )
        self._audit("resource_binding", entity, status, actor_id, before, correlation_id)
        return entity

    def list_access_grants(self, *, include_disabled: bool = True) -> list[dict[str, Any]]:
        return self.repository.list_access_grants(include_disabled=include_disabled)

    def upsert_access_grant(
        self, payload: dict[str, Any], *, actor_id: str, correlation_id: str = ""
    ) -> dict[str, Any]:
        self.require_admin(actor_id)
        subject_type = validate_subject_type(str(payload.get("subject_type") or ""))
        subject_code = validate_code(str(payload.get("subject_code") or ""), field="subject_code")
        effect = validate_access_effect(str(payload.get("effect") or "allow"))
        tool_scope = [
            str(item) for item in normalize_json_list(payload.get("tool_scope"), field="tool_scope")
        ]
        assert_readonly_tool_scope(tool_scope)
        environment_code = payload.get("environment_code")
        base_code = payload.get("base_code")
        workshop_code = payload.get("workshop_code")
        ids = self.repository.resolve_scope_ids(
            environment_code=environment_code,
            base_code=base_code,
            workshop_code=workshop_code,
            allow_wildcard=True,
        )
        before = self.repository.find_access_grant(
            subject_type=subject_type.value,
            subject_code=subject_code,
            effect=effect.value,
            environment_id=ids[0],
            base_id=ids[1],
            workshop_id=ids[2],
        )
        entity = self.repository.upsert_access_grant(
            subject_type=subject_type.value,
            subject_code=subject_code,
            effect=effect.value,
            environment_code=environment_code,
            base_code=base_code,
            workshop_code=workshop_code,
            tool_scope=tool_scope,
            resource_scope=normalize_json_object(
                payload.get("resource_scope"), field="resource_scope"
            ),
            condition=normalize_json_object(payload.get("condition"), field="condition"),
            priority=int(payload.get("priority") or 100),
            status=validate_status(str(payload.get("status") or "enabled")).value,
        )
        self._audit("access_grant", entity, "upsert", actor_id, before, correlation_id)
        return entity

    def set_access_grant_status(
        self, grant_id: str, status: str, *, actor_id: str, correlation_id: str = ""
    ) -> dict[str, Any]:
        self.require_admin(actor_id)
        before = self.repository.get_access_grant(grant_id)
        entity = self.repository.set_access_grant_status(
            validate_code(grant_id, field="grant_id"), validate_status(status).value
        )
        self._audit("access_grant", entity, status, actor_id, before, correlation_id)
        return entity

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

    def public_snapshot(self) -> dict[str, Any]:
        return self.snapshot_builder.build_public_snapshot()

    def runtime_snapshot(self) -> RuntimeTopologySnapshot:
        return self.snapshot_builder.build_runtime_snapshot(resolve_secrets=True)

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

    def _secret_provider(self) -> EncryptedDbSecretProvider:
        return EncryptedDbSecretProvider(self.repository)

    def resolve_secret(self, ref: str) -> str:
        return self._secret_provider().resolve(ref)

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
