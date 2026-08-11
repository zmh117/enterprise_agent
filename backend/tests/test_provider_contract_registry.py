from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.platform_config.application.validation import (
    PlatformConfigValidationError,
)
from app.modules.platform_config.domain.provider_contracts import (
    ProviderContractRegistry,
)
from backend.tests.helpers import container, test_settings as make_settings


def test_database_contract_rejects_ambiguous_fields_and_projects_runtime() -> None:
    registry = ProviderContractRegistry()
    with pytest.raises(
        PlatformConfigValidationError,
        match="Legacy or unsafe database fields",
    ):
        registry.normalize(
            provider_type="mysql",
            config={
                "host": "mysql",
                "port": 3306,
                "database": "orders",
                "user": "reader",
                "username": "other",
            },
            secret_refs={
                "password_ref": "secret://platform/mysql_password"
            },
        )

    imported = registry.normalize(
        provider_type="mysql",
        config={
            "host": "mysql",
            "port": "3306",
            "database": "orders",
            "user": "reader",
        },
        secret_refs={"password": "secret://platform/mysql_password"},
        import_legacy=True,
    )
    assert imported.config == {
        "host": "mysql",
        "port": 3306,
        "database": "orders",
        "username": "reader",
    }
    assert imported.secret_refs == {
        "password_ref": "secret://platform/mysql_password"
    }
    projected = registry.runtime_projection(
        imported,
        resolve_secret=lambda ref: (
            "resolved-password"
            if ref == "secret://platform/mysql_password"
            else ""
        ),
    )
    assert projected["user"] == "reader"
    assert projected["password"] == "resolved-password"
    assert "username" not in projected


@pytest.mark.parametrize("address_key", ["service_name", "sid"])
def test_oracle_contract_requires_exactly_one_structured_address(
    address_key: str,
) -> None:
    registry = ProviderContractRegistry()
    document = registry.normalize(
        provider_type="oracle",
        config={
            "host": "oracle.internal",
            "port": 1521,
            address_key: "ORCL",
            "username": "reader",
            "schema": "APP_READ",
        },
        secret_refs={
            "password_ref": "secret://platform/oracle_password"
        },
    )
    assert document.contract_version == "oracle_11g_v1"
    assert document.config[address_key] == "ORCL"

    for invalid in (
        {},
        {"service_name": "ORCL", "sid": "ORCL"},
        {"connect_descriptor": "(DESCRIPTION=...)"},
    ):
        with pytest.raises(PlatformConfigValidationError):
            registry.normalize(
                provider_type="oracle",
                config={
                    "host": "oracle.internal",
                    "port": 1521,
                    "username": "reader",
                    **invalid,
                },
                secret_refs={
                    "password_ref": "secret://platform/oracle_password"
                },
            )


def test_redis_and_loki_contracts_convert_only_in_import_mode() -> None:
    registry = ProviderContractRegistry()
    with pytest.raises(PlatformConfigValidationError):
        registry.normalize(
            provider_type="redis",
            config={"host": "redis", "port": 6379, "db": 1},
        )
    redis = registry.normalize(
        provider_type="redis",
        config={
            "host": "redis",
            "port": 6379,
            "db": 1,
            "user": "reader",
        },
        secret_refs={
            "password": "secret://platform/redis_password"
        },
        import_legacy=True,
    )
    assert redis.config["database"] == 1
    assert redis.config["username"] == "reader"
    assert redis.config["tls"] == {
        "enabled": False,
        "verify_certificate": True,
    }

    with pytest.raises(PlatformConfigValidationError):
        registry.normalize(
            provider_type="loki",
            config={
                "base_url": "http://loki:3100",
                "tenant": "orders",
                "timeout_seconds": 5,
                "max_minutes": 60,
                "max_lines": 100,
                "max_response_bytes": 65536,
            },
        )
    loki = registry.normalize(
        provider_type="loki",
        config={
            "base_url": "http://loki:3100/",
            "tenant": "orders",
            "timeout_seconds": 5,
            "max_minutes": 60,
            "max_lines": 100,
            "max_response_bytes": 65536,
        },
        import_legacy=True,
    )
    assert loki.config["base_url"] == "http://loki:3100"
    assert loki.config["tenant_id"] == "orders"


def test_redis_tls_and_loki_auth_limits_are_strict_and_projectable() -> None:
    registry = ProviderContractRegistry()
    for tls in (
        {"enabled": "false"},
        {"enabled": True, "verify_certificate": "true"},
        {
            "enabled": True,
            "verify_certificate": True,
            "server_name": "redis.internal",
        },
    ):
        with pytest.raises(PlatformConfigValidationError):
            registry.normalize(
                provider_type="redis",
                config={
                    "host": "redis.internal",
                    "port": 6380,
                    "database": 1,
                    "tls": tls,
                },
            )

    redis = registry.normalize(
        provider_type="redis",
        config={
            "host": "redis.internal",
            "port": 6380,
            "database": 1,
            "username": "reader",
            "tls": {
                "enabled": True,
                "verify_certificate": True,
            },
        },
        secret_refs={
            "password_ref": "secret://platform/redis_password"
        },
    )
    projected_redis = registry.runtime_projection(
        redis,
        resolve_secret=lambda _ref: "redis-password",
    )
    assert projected_redis["db"] == 1
    assert projected_redis["password"] == "redis-password"
    assert "database" not in projected_redis

    with pytest.raises(PlatformConfigValidationError):
        registry.normalize(
            provider_type="loki",
            config={
                "base_url": "http://user:password@loki:3100?token=x",
                "timeout_seconds": 5,
                "max_minutes": 60,
                "max_lines": 500,
                "max_response_bytes": 65536,
            },
        )
    loki = registry.normalize(
        provider_type="loki",
        config={
            "base_url": "http://loki:3100",
            "tenant_id": "tenant-a",
            "timeout_seconds": 5,
            "max_minutes": 60,
            "max_lines": 500,
            "max_response_bytes": 65536,
        },
        secret_refs={"auth_ref": "secret://platform/loki_auth"},
    )
    projected_loki = registry.runtime_projection(
        loki,
        resolve_secret=lambda _ref: "loki-token",
    )
    assert projected_loki["tenant"] == "tenant-a"
    assert projected_loki["auth_token"] == "loki-token"
    assert "tenant_id" not in projected_loki


def test_provider_contract_api_is_metadata_only_and_marks_postgres_unavailable() -> None:
    runtime = container()
    app = create_app(
        make_settings(),
        container_factory=lambda _: runtime,
    )
    with TestClient(app) as client:
        response = client.get(
            "/api/platform/provider-contracts",
            headers={"x-admin-user-id": "admin"},
        )

    assert response.status_code == 200
    contracts = {
        item["provider_type"]: item
        for item in response.json()["contracts"]
    }
    assert contracts["mysql"]["available"] is True
    assert contracts["sqlserver"]["available"] is True
    assert contracts["oracle"]["available"] is True
    assert contracts["postgresql"]["available"] is False
    assert "Handler" in contracts["postgresql"]["unavailable_reason"]
    serialized = response.text.lower()
    assert "python" not in serialized
    assert "script" not in serialized
    assert "resolved-password" not in serialized
