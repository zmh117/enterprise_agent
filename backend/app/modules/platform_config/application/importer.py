from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..infrastructure.repository import PlatformConfigRepository
from .validation import (
    PlatformConfigValidationError,
    assert_no_secret_payload,
    validate_engine,
    validate_secret_ref,
)


@dataclass
class ImportStats:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def record(self, before: dict[str, Any] | None) -> None:
        if before:
            self.updated += 1
        else:
            self.created += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "created": self.created,
            "updated": self.updated,
            "skipped": self.skipped,
            "errors": self.errors,
        }


class PlatformTopologyYamlImporter:
    def __init__(self, repository: PlatformConfigRepository) -> None:
        self.repository = repository

    def import_file(
        self,
        path: str | Path,
        *,
        actor_id: str = "",
        correlation_id: str = "",
    ) -> dict[str, Any]:
        return self.import_text(
            Path(path).read_text(),
            actor_id=actor_id,
            correlation_id=correlation_id,
        )

    def import_text(
        self,
        text: str,
        *,
        actor_id: str = "",
        correlation_id: str = "",
    ) -> dict[str, Any]:
        raw = yaml.safe_load(text) or {}
        if not isinstance(raw, dict):
            raise PlatformConfigValidationError(
                "Topology YAML root must be an object",
                safe_message="Topology YAML root must be an object",
            )
        stats = ImportStats()
        for env_code, env_data in (raw.get("environments") or {}).items():
            env_data = env_data or {}
            before_env = self.repository.get_environment_by_code(str(env_code))
            env = self.repository.upsert_environment(
                code=str(env_code),
                display_name=str(env_data.get("display_name") or ""),
                aliases=[str(item) for item in env_data.get("aliases") or []],
            )
            stats.record(before_env)
            self._audit("environment", env, "import", actor_id, before_env, correlation_id)
            for base_code, base_data in (env_data.get("bases") or {}).items():
                self._import_base(
                    stats,
                    env_code=str(env_code),
                    base_code=str(base_code),
                    base_data=base_data or {},
                    actor_id=actor_id,
                    correlation_id=correlation_id,
                )
        self._import_access(raw.get("access") or {}, stats, actor_id, correlation_id)
        return stats.to_dict()

    def _import_base(
        self,
        stats: ImportStats,
        *,
        env_code: str,
        base_code: str,
        base_data: dict[str, Any],
        actor_id: str,
        correlation_id: str,
    ) -> None:
        engine = validate_engine(str(base_data.get("engine") or ""))
        before_base = self.repository.get_base_by_code(environment_code=env_code, code=base_code)
        base = self.repository.upsert_base(
            environment_code=env_code,
            code=base_code,
            engine=engine,
            display_name=str(base_data.get("display_name") or ""),
            aliases=[str(item) for item in base_data.get("aliases") or []],
        )
        stats.record(before_base)
        self._audit("base", base, "import", actor_id, before_base, correlation_id)
        for kind in ("database", "redis", "loki"):
            if base_data.get(kind):
                self._import_resource_binding(
                    stats,
                    env_code=env_code,
                    base_code=base_code,
                    engine=engine,
                    kind=kind,
                    data=base_data[kind] or {},
                    actor_id=actor_id,
                    correlation_id=correlation_id,
                )
        for workshop_code, workshop_data in (base_data.get("workshops") or {}).items():
            workshop_data = workshop_data or {}
            before_workshop = self.repository.get_workshop_by_code(
                environment_code=env_code,
                base_code=base_code,
                code=str(workshop_code),
            )
            workshop = self.repository.upsert_workshop(
                environment_code=env_code,
                base_code=base_code,
                code=str(workshop_code),
                display_name=str(workshop_data.get("display_name") or ""),
                table_prefix=str(workshop_data.get("table_prefix") or ""),
                redis_key_prefix=str(workshop_data.get("redis_key_prefix") or ""),
                loki_labels={
                    str(k): str(v) for k, v in (workshop_data.get("loki_label") or {}).items()
                },
                aliases=[str(item) for item in workshop_data.get("aliases") or []],
            )
            stats.record(before_workshop)
            self._audit(
                "workshop",
                workshop,
                "import",
                actor_id,
                before_workshop,
                correlation_id,
            )

    def _import_resource_binding(
        self,
        stats: ImportStats,
        *,
        env_code: str,
        base_code: str,
        engine: str,
        kind: str,
        data: dict[str, Any],
        actor_id: str,
        correlation_id: str,
    ) -> None:
        config: dict[str, Any] = {}
        secret_refs: dict[str, str] = {}
        for key, value in data.items():
            key_text = str(key)
            if key_text.endswith("_ref"):
                target_key = key_text.removesuffix("_ref")
                ref = validate_secret_ref(str(value))
                secret_code = self._secret_code(ref)
                before_secret = self.repository.get_secret_reference_by_code(secret_code)
                secret = self.repository.upsert_secret_reference(
                    code=secret_code,
                    provider=ref.split(":", 1)[0],
                    ref=ref,
                    purpose=f"{env_code}/{base_code}/{kind}/{target_key}",
                )
                stats.record(before_secret)
                self._audit(
                    "secret_reference",
                    secret,
                    "import",
                    actor_id,
                    before_secret,
                    correlation_id,
                )
                secret_refs[target_key] = ref
            else:
                config[key_text] = value
        assert_no_secret_payload(config)
        code = f"{env_code}_{base_code}_{kind}"
        before = self.repository.get_resource_binding_by_code(code)
        binding = self.repository.upsert_resource_binding(
            code=code,
            scope_type="base",
            environment_code=env_code,
            base_code=base_code,
            resource_kind=kind,
            engine=engine if kind == "database" else None,
            config=config,
            secret_refs=secret_refs,
        )
        stats.record(before)
        self._audit("resource_binding", binding, "import", actor_id, before, correlation_id)

    def _import_access(
        self,
        access_data: dict[str, Any],
        stats: ImportStats,
        actor_id: str,
        correlation_id: str,
    ) -> None:
        for subject_code, grants in access_data.items():
            for grant in grants or []:
                env = str(grant.get("environment") or "*")
                base = str(grant.get("base") or "*")
                workshop = str(grant.get("workshop") or "*")
                ids = self._grant_ids(env, base, workshop)
                before = self.repository.find_access_grant(
                    subject_type="user",
                    subject_code=str(subject_code),
                    effect="allow",
                    environment_id=ids["environment_id"],
                    base_id=ids["base_id"],
                    workshop_id=ids["workshop_id"],
                )
                access_grant = self.repository.upsert_access_grant(
                    subject_type="user",
                    subject_code=str(subject_code),
                    effect="allow",
                    environment_code=env,
                    base_code=base,
                    workshop_code=workshop,
                    tool_scope=["read_only"],
                    priority=100,
                )
                stats.record(before)
                self._audit(
                    "access_grant",
                    access_grant,
                    "import",
                    actor_id,
                    before,
                    correlation_id,
                )

    def _grant_ids(self, env: str, base: str, workshop: str) -> dict[str, str | None]:
        environment_id, base_id, workshop_id = self.repository.resolve_scope_ids(
            environment_code=env,
            base_code=base,
            workshop_code=workshop,
            allow_wildcard=True,
        )
        return {
            "environment_id": environment_id,
            "base_id": base_id,
            "workshop_id": workshop_id,
        }

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

    @staticmethod
    def _secret_code(ref: str) -> str:
        cleaned = "".join(ch if ch.isalnum() else "_" for ch in ref).strip("_").lower()
        return f"secret_{cleaned}"[:128]
