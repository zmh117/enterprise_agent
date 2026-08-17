from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.mcp_tool_runtime.resource_resolver import DirectResourceResolver
from app.modules.mcp_tool_runtime.direct_executor import DirectReadOnlyToolExecutor
from app.modules.mcp_tool_runtime.domain.errors import PolicyViolation
from app.modules.platform_config.application.governed_resources import (
    ResourceVerificationOutcome,
)
from app.modules.platform_config.application.resource_scope_bindings import (
    normalize_resource_scope_bindings,
    select_resource_scope_binding,
)
from app.shared.exceptions import NonRetryableExecutionError, ToolPolicyError
from app.shared.config import ExecutionSettings
from backend.tests.helpers import container


class _RowsDatabase:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def execute(self, _sql: str, parameters: tuple[object, ...]) -> list[dict[str, Any]]:
        return [row for row in self.rows if row["resource_kind"] == parameters[0]]


class _SecretProvider:
    def resolve(self, ref: str) -> str:
        assert ref == "secret://platform/scope_mysql_password"
        return "resolved-scope-secret"


class _PassingVerifier:
    def verify(self, **_: object) -> ResourceVerificationOutcome:
        return ResourceVerificationOutcome(
            status="PASSED",
            provider_contract_version="mysql_v1",
            checks={"connection": True, "readonly": True},
        )


class _RedisGateway:
    def __init__(self) -> None:
        self.keys: list[str] = []

    def get(self, _binding: object, key: str) -> SimpleNamespace:
        self.keys.append(key)
        return SimpleNamespace(summary={"found": True}, raw={}, truncated=False)

    def scan(self, _binding: object, pattern: str, limit: int) -> SimpleNamespace:
        self.keys.append(f"{pattern}:{limit}")
        return SimpleNamespace(summary={"count": 0}, raw={}, truncated=False)


class _LokiGateway:
    def __init__(self) -> None:
        self.selectors: list[dict[str, str]] = []

    def query(self, _binding: object, *, selector: dict[str, str], **_: object) -> SimpleNamespace:
        self.selectors.append(selector)
        return SimpleNamespace(summary={"line_count": 0}, raw={}, truncated=False)


def _database_row(*, scope_bindings: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "resource_id": "resource-scope-db",
        "code": "scope-db",
        "resource_kind": "database",
        "scope_type": "workshop",
        "placement": "",
        "environment_code": "prod",
        "base_code": "guanlan",
        "workshop_code": "GL001",
        "resource_revision_id": "revision-scope-db-1",
        "revision": 1,
        "provider_type": "mysql",
        "provider_contract_version": "mysql_v1",
        "config_json": json.dumps(
            {
                "host": "mysql.internal",
                "port": 3306,
                "database": "mes",
                "username": "readonly",
            }
        ),
        "secret_refs_json": json.dumps(
            {"password_ref": "secret://platform/scope_mysql_password"}
        ),
        "scope_bindings_json": json.dumps(scope_bindings),
        "content_hash": "a" * 64,
    }


def _redis_row() -> dict[str, Any]:
    return {
        "resource_id": "resource-scope-redis",
        "code": "scope-redis",
        "resource_kind": "redis",
        "scope_type": "workshop",
        "placement": "",
        "environment_code": "prod",
        "base_code": "guanlan",
        "workshop_code": "GL001",
        "resource_revision_id": "revision-scope-redis-1",
        "revision": 1,
        "provider_type": "redis",
        "provider_contract_version": "redis_v1",
        "config_json": json.dumps(
            {
                "host": "redis.internal",
                "port": 6379,
                "database": 0,
                "username": "",
                "tls": {"enabled": False, "verify_certificate": True},
            }
        ),
        "secret_refs_json": "{}",
        "scope_bindings_json": json.dumps(
            [
                {
                    "environment_code": "prod",
                    "base_code": "guanlan",
                    "workshop_code": "GL001",
                    "namespace_prefixes": ["mes:GL001:"],
                }
            ]
        ),
        "content_hash": "b" * 64,
    }


def _loki_row() -> dict[str, Any]:
    return {
        "resource_id": "resource-scope-loki",
        "code": "scope-loki",
        "resource_kind": "loki",
        "scope_type": "global",
        "placement": "",
        "environment_code": "",
        "base_code": "",
        "workshop_code": "",
        "resource_revision_id": "revision-scope-loki-1",
        "revision": 1,
        "provider_type": "loki",
        "provider_contract_version": "loki_v1",
        "config_json": json.dumps(
            {
                "base_url": "http://loki.internal:3100",
                "tenant_id": "tenant-a",
                "timeout_seconds": 5,
                "max_minutes": 60,
                "max_lines": 200,
                "max_response_bytes": 65536,
            }
        ),
        "secret_refs_json": "{}",
        "scope_bindings_json": json.dumps(
            [
                {
                    "environment_code": "prod",
                    "base_code": "guanlan",
                    "selector_conditions": {
                        "cluster": "cn-prod-01",
                        "kubernetes_namespace_name": "mes-production",
                    },
                }
            ]
        ),
        "content_hash": "c" * 64,
    }


def test_loki_scope_binding_accepts_arbitrary_discovered_exact_labels() -> None:
    normalized = normalize_resource_scope_bindings(
        [
            {
                "environment_code": "prod",
                "base_code": "guanlan",
                "selector_conditions": {
                    "cluster": "cn-prod-01",
                    "namespace": "mes",
                    "app": "edge-gateway",
                },
            }
        ],
        resource_kind="loki",
        scope_type="global",
        environment_code="",
        base_code="",
        workshop_code="",
    )

    assert normalized == [
        {
            "environment_code": "prod",
            "base_code": "guanlan",
            "selector_conditions": {
                "app": "edge-gateway",
                "cluster": "cn-prod-01",
                "namespace": "mes",
            },
        }
    ]
    assert select_resource_scope_binding(
        normalized,
        resource_kind="loki",
        environment_code="prod",
        base_code="guanlan",
        workshop_code="GL001",
    ) == normalized[0]


def test_scope_binding_rejects_wildcards_and_duplicate_targets() -> None:
    with pytest.raises(NonRetryableExecutionError) as wildcard:
        normalize_resource_scope_bindings(
            [
                {
                    "environment_code": "prod",
                    "base_code": "guanlan",
                    "selector_conditions": {"cluster": "prod-*"},
                }
            ],
            resource_kind="loki",
            scope_type="global",
            environment_code="",
            base_code="",
            workshop_code="",
        )
    assert wildcard.value.error_code == "resource_scope_bindings_invalid"

    with pytest.raises(NonRetryableExecutionError, match="同一平台目标"):
        normalize_resource_scope_bindings(
            [
                {
                    "environment_code": "prod",
                    "namespace_prefixes": ["one:"],
                },
                {
                    "environment_code": "prod",
                    "namespace_prefixes": ["two:"],
                },
            ],
            resource_kind="redis",
            scope_type="environment",
            environment_code="prod",
            base_code="",
            workshop_code="",
        )


def test_resource_draft_rejects_scope_binding_outside_current_topology() -> None:
    runtime = container()
    service = runtime.platform_config_service.governed_resources
    try:
        with pytest.raises(NonRetryableExecutionError) as error:
            service.create_resource(
                {
                    "code": "scope_loki_missing_target",
                    "name": "Scope Loki Missing Target",
                    "resource_kind": "loki",
                    "scope_type": "global",
                    "environment_code": "",
                    "base_code": "",
                    "workshop_code": "",
                    "provider_type": "loki",
                    "config": {
                        "base_url": "http://loki.internal:3100",
                        "tenant_id": "",
                        "timeout_seconds": 5,
                        "max_minutes": 60,
                        "max_lines": 200,
                        "max_response_bytes": 65536,
                    },
                    "secret_refs": {},
                    "scope_bindings": [
                        {
                            "environment_code": "missing_environment",
                            "selector_conditions": {"cluster": "cn-prod-01"},
                        }
                    ],
                },
                actor_id="user_local_admin",
            )
        assert error.value.error_code == "resource_scope_binding_target_unavailable"
    finally:
        runtime.database.close()


def test_resource_draft_hash_and_revision_include_scope_bindings() -> None:
    runtime = container()
    service = runtime.platform_config_service.governed_resources
    actor_id = "user_local_admin"
    try:
        runtime.platform_config_service.upsert_environment(
            {"code": "scope_env"}, actor_id=actor_id
        )
        runtime.platform_config_service.upsert_base(
            {
                "environment_code": "scope_env",
                "code": "scope_base",
                "engine": "mysql",
            },
            actor_id=actor_id,
        )
        runtime.platform_config_service.upsert_workshop(
            {
                "environment_code": "scope_env",
                "base_code": "scope_base",
                "code": "S001",
            },
            actor_id=actor_id,
        )
        runtime.platform_config_service.create_platform_secret(
            {"code": "scope_mysql_password", "value": "scope-secret"},
            actor_id=actor_id,
        )
        created = service.create_resource(
            {
                "code": "scope_mysql",
                "name": "Scope MySQL",
                "resource_kind": "database",
                "scope_type": "workshop",
                "environment_code": "scope_env",
                "base_code": "scope_base",
                "workshop_code": "S001",
                "provider_type": "mysql",
                "config": {
                    "host": "mysql.internal",
                    "port": 3306,
                    "database": "mes",
                    "username": "reader",
                },
                "secret_refs": {
                    "password_ref": "secret://platform/scope_mysql_password"
                },
                "scope_bindings": [
                    {
                        "environment_code": "scope_env",
                        "base_code": "scope_base",
                        "workshop_code": "S001",
                        "table_prefix": "S001_EBR_",
                    }
                ],
            },
            actor_id=actor_id,
        )
        first_hash = created["draft"]["content_hash"]
        changed = service.save_draft(
            "scope_mysql",
            {
                "provider_type": "mysql",
                "config": created["draft"]["config"],
                "secret_refs": created["draft"]["secret_refs"],
                "scope_bindings": [
                    {
                        "environment_code": "scope_env",
                        "base_code": "scope_base",
                        "workshop_code": "S001",
                        "table_prefix": "S001_MES_",
                    }
                ],
            },
            expected_revision=1,
            actor_id=actor_id,
        )
        assert changed["content_hash"] != first_hash
        service.verify_draft(
            "scope_mysql", actor_id=actor_id, verifier=_PassingVerifier()
        )
        published = service.publish_draft("scope_mysql", actor_id=actor_id)
        assert published["scope_bindings"][0]["table_prefix"] == "S001_MES_"
        assert published["content_hash"] == changed["content_hash"]
    finally:
        runtime.database.close()


def test_direct_resolver_uses_revision_scope_and_fails_closed_without_it() -> None:
    binding = {
        "environment_code": "prod",
        "base_code": "guanlan",
        "workshop_code": "GL001",
        "table_prefix": "GL001_EBR_",
    }
    resolver = DirectResourceResolver(
        _RowsDatabase([_database_row(scope_bindings=[binding])]),
        secret_provider=_SecretProvider(),
    )
    resolved = resolver.resolve(
        resource_kind="database",
        environment="prod",
        base="guanlan",
        workshop="GL001",
    )
    assert resolved.table_prefix == "GL001_EBR_"
    assert resolved.binding.workshop is not None
    assert resolved.binding.workshop.table_prefix == "GL001_EBR_"

    missing = DirectResourceResolver(
        _RowsDatabase([_database_row(scope_bindings=[])]),
        secret_provider=_SecretProvider(),
    )
    with pytest.raises(ToolPolicyError) as rejected:
        missing.resolve(
            resource_kind="database",
            environment="prod",
            base="guanlan",
            workshop="GL001",
        )
    assert rejected.value.error_code == "mcp_resource_scope_not_resolved"


def test_direct_executor_enforces_redis_namespace_before_gateway_access() -> None:
    resolver = DirectResourceResolver(
        _RowsDatabase([_redis_row()]),
        secret_provider=_SecretProvider(),
    )
    executor = DirectReadOnlyToolExecutor(resolver, limits=ExecutionSettings())
    gateway = _RedisGateway()
    executor.redis = gateway  # type: ignore[assignment]

    executor.query_redis_get(
        "ignored",
        "mes:GL001:order:1",
        None,  # type: ignore[arg-type]
        environment="prod",
        base="guanlan",
        workshop="GL001",
    )
    assert gateway.keys == ["mes:GL001:order:1"]

    with pytest.raises(PolicyViolation):
        executor.query_redis_get(
            "ignored",
            "mes:CZ002:order:1",
            None,  # type: ignore[arg-type]
            environment="prod",
            base="guanlan",
            workshop="GL001",
        )
    assert gateway.keys == ["mes:GL001:order:1"]


def test_direct_executor_injects_arbitrary_mandatory_loki_selector() -> None:
    resolver = DirectResourceResolver(
        _RowsDatabase([_loki_row()]),
        secret_provider=_SecretProvider(),
    )
    executor = DirectReadOnlyToolExecutor(resolver, limits=ExecutionSettings())
    gateway = _LokiGateway()
    executor._loki = lambda _resource: gateway  # type: ignore[method-assign]

    executor.query_loki(
        {"service": "edge-gateway"},
        "error",
        15,
        20,
        None,  # type: ignore[arg-type]
        environment="prod",
        base="guanlan",
        workshop="GL001",
    )
    assert gateway.selectors == [
        {
            "cluster": "cn-prod-01",
            "kubernetes_namespace_name": "mes-production",
            "service": "edge-gateway",
        }
    ]

    with pytest.raises(PolicyViolation):
        executor.query_loki(
            {"cluster": "override"},
            "",
            15,
            20,
            None,  # type: ignore[arg-type]
            environment="prod",
            base="guanlan",
        )
