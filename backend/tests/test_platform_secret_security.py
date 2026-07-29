from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.internal_api_platform.infrastructure.secrets import (
    DbBackedSecretResolver,
)
from app.modules.platform_config.application.validation import (
    PlatformConfigValidationError,
    validate_secret_ref,
)
from app.modules.platform_config.infrastructure.repository import now_iso
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.helpers import container, test_settings as make_settings


def test_platform_secret_versions_are_aad_bound_and_have_one_active_version() -> None:
    runtime = container()
    resolver = DbBackedSecretResolver(
        runtime.platform_config_service.repository,
        master_key=runtime.settings.app_config_master_key,
    )
    service = runtime.platform_config_service

    created = service.create_platform_secret(
        {"code": "db_password", "value": "first-sensitive-value"},
        actor_id="local-user",
    )
    rotated = service.rotate_platform_secret(
        "db_password",
        {"value": "second-sensitive-value"},
        actor_id="local-user",
    )

    versions = runtime.database.execute(
        """
        select version, algorithm, status
        from platform_secret_version
        where secret_id = ?
        order by version
        """,
        (created["id"],),
    )
    assert versions == [
        {
            "version": 1,
            "algorithm": "AES-256-GCM-AAD-V1",
            "status": "superseded",
        },
        {
            "version": 2,
            "algorithm": "AES-256-GCM-AAD-V1",
            "status": "active",
        },
    ]
    assert rotated["active_version"] == 2
    assert resolver.resolve(created["secret_ref"]) == "second-sensitive-value"

    with pytest.raises(Exception):
        runtime.database.execute(
            """
            update platform_secret_version
            set status = 'active'
            where secret_id = ? and version = 1
            """,
            (created["id"],),
        )


def test_platform_secret_ciphertext_cannot_be_swapped_between_secret_contexts() -> None:
    runtime = container()
    service = runtime.platform_config_service
    first = service.create_platform_secret(
        {"code": "first_secret", "value": "same-sensitive-value"},
        actor_id="local-user",
    )
    second = service.create_platform_secret(
        {"code": "second_secret", "value": "same-sensitive-value"},
        actor_id="local-user",
    )
    first_version = runtime.database.execute_one(
        """
        select ciphertext, nonce
        from platform_secret_version
        where secret_id = ? and version = 1
        """,
        (first["id"],),
    )
    assert first_version is not None
    runtime.database.execute(
        """
        update platform_secret_version
        set ciphertext = ?, nonce = ?
        where secret_id = ? and version = 1
        """,
        (
            first_version["ciphertext"],
            first_version["nonce"],
            second["id"],
        ),
    )
    resolver = DbBackedSecretResolver(
        service.repository,
        master_key=runtime.settings.app_config_master_key,
    )

    with pytest.raises(
        NonRetryableExecutionError,
        match="Platform secret decrypt failed",
    ):
        resolver.resolve(second["secret_ref"])


def test_disabled_platform_secret_has_no_active_version_and_fails_closed() -> None:
    runtime = container()
    secret = runtime.platform_config_service.create_platform_secret(
        {"code": "disabled_secret", "value": "disable-sensitive-value"},
        actor_id="local-user",
    )
    disabled = runtime.platform_config_service.disable_platform_secret(
        "disabled_secret",
        actor_id="local-user",
    )
    resolver = DbBackedSecretResolver(
        runtime.platform_config_service.repository,
        master_key=runtime.settings.app_config_master_key,
    )

    assert disabled["status"] == "disabled"
    assert disabled["configured"] is False
    assert runtime.database.execute_one(
        """
        select status
        from platform_secret_version
        where secret_id = ? and version = 1
        """,
        (secret["id"],),
    ) == {"status": "disabled"}
    with pytest.raises(NonRetryableExecutionError):
        resolver.resolve(secret["secret_ref"])


def test_secret_api_audit_and_logs_never_echo_plaintext_or_crypto_material(
    caplog: pytest.LogCaptureFixture,
) -> None:
    runtime = container()
    app = create_app(make_settings(), container_factory=lambda _: runtime)
    plaintext = "q7Z-secret-9283-with-x9Vp"

    with caplog.at_level(logging.DEBUG), TestClient(app) as client:
        created = client.post(
            "/api/platform/secrets",
            json={
                "code": "leak_canary",
                "value": plaintext,
                "purpose": "database-password",
            },
            headers={"x-admin-user-id": "local-user"},
        )
        listed = client.get("/api/platform/secrets")
        fetched = client.get("/api/platform/secrets/leak_canary")
        stored = runtime.database.execute_one(
            """
            select ciphertext, nonce, key_id
            from platform_secret_version
            where secret_id = ?
            """,
            (created.json()["secret"]["id"],),
        )
        audit = runtime.platform_config_service.repository.list_config_audit(
            limit=20
        )
        all_versions = runtime.database.execute(
            "select * from platform_secret_version"
        )

    assert created.status_code == 200
    assert listed.status_code == 200
    assert fetched.status_code == 200
    responses = f"{created.text}\n{listed.text}\n{fetched.text}"
    assert stored is not None
    for forbidden in (
        plaintext,
        plaintext[:3],
        plaintext[-4:],
        stored["ciphertext"],
        stored["nonce"],
        stored["key_id"],
    ):
        assert forbidden not in responses
        assert forbidden not in caplog.text
        assert forbidden not in str(audit)
    assert plaintext not in str(all_versions)


def test_secret_plaintext_cannot_be_copied_to_public_metadata() -> None:
    runtime = container()
    app = create_app(make_settings(), container_factory=lambda _: runtime)
    plaintext = "metadata-canary-sensitive-value"

    with TestClient(app) as client:
        response = client.post(
            "/api/platform/secrets",
            json={
                "code": "metadata_canary",
                "value": plaintext,
                "metadata": {"note": plaintext},
            },
            headers={"x-admin-user-id": "local-user"},
        )
        secret = (
            runtime.platform_config_service.repository.get_platform_secret_by_code(
                "metadata_canary"
            )
        )

    assert response.status_code == 400
    assert plaintext not in response.text
    assert secret is None


@pytest.mark.parametrize(
    ("ref", "safe_message"),
    (
        ("env:ORDER_DB_PASSWORD", "env 凭据引用必须先导入凭据中心"),
        ("vault:secret/data/order", "Provider 尚未实现"),
        ("kms:key/order", "Provider 尚未实现"),
        (
            "secret://legacy/order_password",
            "新配置只能选择凭据中心的 secret://platform/<code>",
        ),
    ),
)
def test_new_secret_bindings_reject_legacy_and_reserved_providers(
    ref: str,
    safe_message: str,
) -> None:
    runtime = container()
    resolver = DbBackedSecretResolver(
        runtime.platform_config_service.repository,
        master_key=runtime.settings.app_config_master_key,
    )

    with pytest.raises(PlatformConfigValidationError) as validation_error:
        validate_secret_ref(ref)
    assert validation_error.value.safe_message == safe_message

    with pytest.raises(NonRetryableExecutionError) as resolution_error:
        resolver.resolve(ref)
    expected_runtime_message = (
        "Provider 尚未实现"
        if ref.startswith(("vault:", "kms:"))
        else (
            "env 凭据引用必须先导入凭据中心"
            if ref.startswith("env:")
            else "新配置只能使用凭据中心 Secret"
        )
    )
    assert resolution_error.value.safe_message == expected_runtime_message


def test_new_resource_binding_requires_existing_active_platform_secret() -> None:
    runtime = container()
    service = runtime.platform_config_service

    with pytest.raises(PlatformConfigValidationError) as missing:
        service.upsert_resource_binding(
            {
                "code": "new_mysql",
                "scope_type": "base",
                "environment_code": "default",
                "base_code": "default",
                "resource_kind": "database",
                "engine": "mysql",
                "config": {
                    "host": "mysql",
                    "port": 3306,
                    "database": "app",
                    "username": "reader",
                },
                "secret_refs": {
                    "password": "secret://platform/missing_password"
                },
            },
            actor_id="local-user",
        )
    assert "不存在、已禁用" in missing.value.safe_message


def test_secret_usage_api_returns_only_dependency_metadata() -> None:
    runtime = container()
    service = runtime.platform_config_service
    plaintext = "usage-secret-value-never-returned"
    secret = service.create_platform_secret(
        {
            "code": "usage_secret",
            "value": plaintext,
            "purpose": "dependency-test",
        },
        actor_id="local-user",
    )
    service.upsert_environment(
        {"code": "usage_env"},
        actor_id="local-user",
    )
    service.upsert_base(
        {
            "environment_code": "usage_env",
            "code": "usage_base",
            "engine": "mysql",
        },
        actor_id="local-user",
    )
    service.upsert_resource_binding(
        {
            "code": "usage_database",
            "scope_type": "base",
            "environment_code": "usage_env",
            "base_code": "usage_base",
            "resource_kind": "database",
            "engine": "mysql",
            "config": {
                "host": "mysql",
                "port": 3306,
                "database": "usage",
                "username": "reader",
            },
            "secret_refs": {"password": secret["secret_ref"]},
        },
        actor_id="local-user",
    )
    service.upsert_runtime_config_definition(
        {
            "key": "USAGE_RUNTIME_SECRET",
            "value_type": "secret_ref",
            "sensitive": True,
        },
        actor_id="local-user",
    )
    service.upsert_runtime_config_value(
        {
            "key": "USAGE_RUNTIME_SECRET",
            "secret_ref": secret["secret_ref"],
        },
        actor_id="local-user",
    )
    timestamp = now_iso()
    runtime.database.execute(
        """
        insert into integration_connector
          (id, connector_type, name, secret_ref, created_at, updated_at)
        values (?, ?, ?, ?, ?, ?)
        """,
        (
            "connector-usage-secret",
            "webhook",
            "Usage Secret Connector",
            secret["secret_ref"],
            timestamp,
            timestamp,
        ),
    )
    app = create_app(make_settings(), container_factory=lambda _: runtime)

    with TestClient(app) as client:
        response = client.get("/api/platform/secrets/usage_secret/usage")
        duplicate = client.post(
            "/api/platform/secrets",
            json={"code": "usage_secret", "value": "must-not-rotate"},
            headers={"x-admin-user-id": "local-user"},
        )
        usage = response.json()["usage"]
        version_count = runtime.database.execute_one(
            """
            select count(*) as count
            from platform_secret_version
            where secret_id = ?
            """,
            (secret["id"],),
        )
        stored = (
            runtime.platform_config_service.repository.get_active_secret_version(
                secret["id"]
            )
        )

    assert response.status_code == 200
    assert duplicate.status_code == 400
    assert version_count == {"count": 1}
    assert usage["usage_count"] == 3
    assert {
        item["dependency_type"] for item in usage["dependencies"]
    } == {"connector", "resource_binding", "runtime_config"}
    serialized = response.text
    assert stored is not None
    for forbidden in (
        plaintext,
        "must-not-rotate",
        stored["ciphertext"],
        stored["nonce"],
        stored["key_id"],
    ):
        assert forbidden not in serialized
