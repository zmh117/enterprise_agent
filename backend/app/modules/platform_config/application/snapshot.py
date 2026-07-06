from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from app.modules.internal_api_platform.domain.access import AccessPolicy, AccessScope, ScopeRule
from app.modules.internal_api_platform.domain.topology import (
    Base,
    DatabaseConnection,
    DatabaseEngine,
    Environment,
    LokiConnection,
    RedisConnection,
    Topology,
    Workshop,
)
from app.modules.internal_api_platform.infrastructure.secrets import (
    EnvSecretResolver,
    SecretResolver,
)

from ..infrastructure.repository import PlatformConfigRepository


@dataclass(frozen=True)
class RuntimeTopologySnapshot:
    topology: Topology
    access_policy: AccessPolicy
    source: str
    revision: int
    resource_count: int
    errors: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.errors


class PlatformTopologySnapshotBuilder:
    def __init__(
        self,
        repository: PlatformConfigRepository,
        *,
        resolver: SecretResolver | None = None,
    ) -> None:
        self.repository = repository
        self.resolver = resolver or EnvSecretResolver()

    def build_public_snapshot(self) -> dict[str, Any]:
        runtime = self.build_runtime_snapshot(resolve_secrets=False)
        return {
            "source": runtime.source,
            "revision": runtime.revision,
            "config_hash": self._config_hash(),
            "valid": runtime.valid,
            "errors": runtime.errors,
            "resource_count": runtime.resource_count,
            "environments": self._public_environments(),
            "access_grant_count": len(self.repository.list_access_grants(include_disabled=False)),
        }

    def build_runtime_snapshot(self, *, resolve_secrets: bool = True) -> RuntimeTopologySnapshot:
        environments = self.repository.list_environments(include_disabled=False)
        if not environments:
            return RuntimeTopologySnapshot(
                topology=Topology(),
                access_policy=AccessPolicy(),
                source="database-empty",
                revision=0,
                resource_count=0,
            )

        bases = self.repository.list_bases(include_disabled=False)
        workshops = self.repository.list_workshops(include_disabled=False)
        bindings = self.repository.list_resource_bindings(include_disabled=False)
        errors: list[str] = []

        bases_by_env: dict[str, list[dict[str, Any]]] = {}
        for base in bases:
            bases_by_env.setdefault(str(base["environment_code"]), []).append(base)
        workshops_by_base: dict[str, list[dict[str, Any]]] = {}
        for workshop in workshops:
            workshops_by_base.setdefault(str(workshop["base_id"]), []).append(workshop)
        bindings_by_base: dict[str, dict[str, dict[str, Any]]] = {}
        for binding in bindings:
            if binding.get("base_id") and binding.get("workshop_id") is None:
                bindings_by_base.setdefault(str(binding["base_id"]), {})[
                    str(binding["resource_kind"])
                ] = binding

        env_map: dict[str, Environment] = {}
        for env in environments:
            base_map: dict[str, Base] = {}
            for base in bases_by_env.get(str(env["code"]), []):
                try:
                    engine = DatabaseEngine(str(base["engine"]))
                except ValueError:
                    errors.append(f"Base {env['code']}/{base['code']} has invalid engine")
                    continue
                base_bindings = bindings_by_base.get(str(base["id"]), {})
                workshop_map = {
                    str(workshop["code"]): Workshop(
                        code=str(workshop["code"]),
                        table_prefix=str(workshop.get("table_prefix") or ""),
                        redis_key_prefix=str(workshop.get("redis_key_prefix") or ""),
                        loki_label={
                            str(k): str(v) for k, v in (workshop.get("loki_labels") or {}).items()
                        },
                        display_name=str(workshop.get("display_name") or ""),
                        aliases=tuple(str(item) for item in workshop.get("aliases") or []),
                    )
                    for workshop in workshops_by_base.get(str(base["id"]), [])
                }
                base_map[str(base["code"])] = Base(
                    code=str(base["code"]),
                    engine=engine,
                    database=self._database_connection(
                        base_bindings.get("database"),
                        errors=errors,
                        resolve_secrets=resolve_secrets,
                    ),
                    redis=self._redis_connection(
                        base_bindings.get("redis"),
                        errors=errors,
                        resolve_secrets=resolve_secrets,
                    ),
                    loki=self._loki_connection(
                        base_bindings.get("loki"),
                        errors=errors,
                        resolve_secrets=resolve_secrets,
                    ),
                    workshops=workshop_map,
                    display_name=str(base.get("display_name") or ""),
                    aliases=tuple(str(item) for item in base.get("aliases") or []),
                )
            env_map[str(env["code"])] = Environment(
                code=str(env["code"]),
                bases=base_map,
                display_name=str(env.get("display_name") or ""),
                aliases=tuple(str(item) for item in env.get("aliases") or []),
            )

        source = "database-invalid" if errors else "database"
        return RuntimeTopologySnapshot(
            topology=Topology(environments=env_map),
            access_policy=self.build_access_policy(),
            source=source,
            revision=self.repository.topology_revision(),
            resource_count=len(bindings),
            errors=errors,
        )

    def build_access_policy(self) -> AccessPolicy:
        scopes: dict[str, AccessScope] = {}
        for grant in self.repository.list_access_grants(include_disabled=False):
            subject = str(grant["subject_code"])
            scopes.setdefault(subject, AccessScope()).rules.append(
                ScopeRule(
                    environment=str(grant.get("environment_code") or "*"),
                    base=str(grant.get("base_code") or "*"),
                    workshop=str(grant.get("workshop_code") or "*"),
                    effect=str(grant.get("effect") or "allow"),
                    priority=int(grant.get("priority") or 100),
                )
            )
        return AccessPolicy(scopes=scopes)

    def _public_environments(self) -> list[dict[str, Any]]:
        bases = self.repository.list_bases(include_disabled=False)
        workshops = self.repository.list_workshops(include_disabled=False)
        resources = self.repository.list_resource_bindings(include_disabled=False)

        workshops_by_base: dict[str, list[dict[str, Any]]] = {}
        for workshop in workshops:
            workshops_by_base.setdefault(str(workshop["base_id"]), []).append(workshop)
        resources_by_scope: dict[str, list[dict[str, Any]]] = {}
        for resource in resources:
            key = str(
                resource.get("workshop_id")
                or resource.get("base_id")
                or resource.get("environment_id")
            )
            resources_by_scope.setdefault(key, []).append(self._public_resource(resource))

        bases_by_environment: dict[str, list[dict[str, Any]]] = {}
        for base in bases:
            base_resources = resources_by_scope.get(str(base["id"]), [])
            base_workshops = []
            for workshop in workshops_by_base.get(str(base["id"]), []):
                base_workshops.append(
                    {
                        "code": workshop["code"],
                        "display_name": workshop.get("display_name") or "",
                        "table_prefix": workshop.get("table_prefix") or "",
                        "redis_key_prefix": workshop.get("redis_key_prefix") or "",
                        "loki_labels": workshop.get("loki_labels") or {},
                        "aliases": workshop.get("aliases") or [],
                        "resources": resources_by_scope.get(str(workshop["id"]), []),
                    }
                )
            bases_by_environment.setdefault(str(base["environment_id"]), []).append(
                {
                    "code": base["code"],
                    "display_name": base.get("display_name") or "",
                    "engine": base.get("engine") or "",
                    "aliases": base.get("aliases") or [],
                    "resources": base_resources,
                    "workshops": base_workshops,
                }
            )

        result = []
        for environment in self.repository.list_environments(include_disabled=False):
            result.append(
                {
                    "code": environment["code"],
                    "display_name": environment.get("display_name") or "",
                    "aliases": environment.get("aliases") or [],
                    "resources": resources_by_scope.get(str(environment["id"]), []),
                    "bases": bases_by_environment.get(str(environment["id"]), []),
                }
            )
        return result

    def _public_resource(self, resource: dict[str, Any]) -> dict[str, Any]:
        return {
            "code": resource["code"],
            "scope_type": resource["scope_type"],
            "resource_kind": resource["resource_kind"],
            "engine": resource.get("engine"),
            "config": resource.get("config") or {},
            "secret_refs": resource.get("secret_refs") or {},
            "revision": resource.get("revision"),
        }

    def _database_connection(
        self,
        binding: dict[str, Any] | None,
        *,
        errors: list[str],
        resolve_secrets: bool,
    ) -> DatabaseConnection | None:
        if binding is None:
            return None
        config = binding.get("config") or {}
        return DatabaseConnection(
            host=self._value(binding, "host", errors=errors, resolve_secrets=resolve_secrets),
            port=int(config.get("port") or 0),
            database=self._value(
                binding, "database", errors=errors, resolve_secrets=resolve_secrets
            ),
            user=self._value(binding, "user", errors=errors, resolve_secrets=resolve_secrets),
            password=self._value(
                binding, "password", errors=errors, resolve_secrets=resolve_secrets
            ),
        )

    def _redis_connection(
        self,
        binding: dict[str, Any] | None,
        *,
        errors: list[str],
        resolve_secrets: bool,
    ) -> RedisConnection | None:
        if binding is None:
            return None
        config = binding.get("config") or {}
        return RedisConnection(
            host=self._value(binding, "host", errors=errors, resolve_secrets=resolve_secrets),
            port=int(config.get("port") or 6379),
            db=int(config.get("db") or 0),
            password=self._optional_value(binding, "password", resolve_secrets=resolve_secrets),
        )

    def _loki_connection(
        self,
        binding: dict[str, Any] | None,
        *,
        errors: list[str],
        resolve_secrets: bool,
    ) -> LokiConnection | None:
        if binding is None:
            return None
        config = binding.get("config") or {}
        return LokiConnection(
            base_url=self._value(
                binding, "base_url", errors=errors, resolve_secrets=resolve_secrets
            ),
            tenant=str(config.get("tenant") or ""),
        )

    def _value(
        self,
        binding: dict[str, Any],
        key: str,
        *,
        errors: list[str],
        resolve_secrets: bool,
    ) -> str:
        value = self._optional_value(binding, key, resolve_secrets=resolve_secrets)
        if not value:
            errors.append(f"Resource {binding['code']} missing required field: {key}")
        return value

    def _optional_value(self, binding: dict[str, Any], key: str, *, resolve_secrets: bool) -> str:
        config = binding.get("config") or {}
        secret_refs = binding.get("secret_refs") or {}
        if key in config:
            return str(config[key])
        ref = secret_refs.get(key)
        if not ref:
            return ""
        return self.resolver.resolve(str(ref)) if resolve_secrets else str(ref)

    def _config_hash(self) -> str:
        payload = {
            "environments": self.repository.list_environments(include_disabled=False),
            "bases": self.repository.list_bases(include_disabled=False),
            "workshops": self.repository.list_workshops(include_disabled=False),
            "resources": self.repository.list_resource_bindings(include_disabled=False),
            "access": self.repository.list_access_grants(include_disabled=False),
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
