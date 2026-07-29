from __future__ import annotations

from fastapi.testclient import TestClient

from app.bootstrap import build_test_container
from app.main import create_app
from app.shared.config import IdentitySettings, Settings

ADMIN_ID = "user_local_admin"


def _settings() -> Settings:
    return Settings(
        database_dsn="sqlite:///:memory:",
        app_config_master_key="test-only-master-key",
        environment="test",
        identity=IdentitySettings(
            enabled=True,
            web_admin_enabled=True,
            published_agent_runtime_enabled=True,
            test_identity_headers_enabled=True,
            cookie_secure=False,
        ),
    )


def _runtime():
    return build_test_container(
        _settings(),
        migrate=True,
        seed=True,
    )


def _create_topology_and_secret(runtime: object) -> None:
    service = runtime.platform_config_service
    service.upsert_environment(
        {"code": "api_resource_env"},
        actor_id=ADMIN_ID,
    )
    service.upsert_base(
        {
            "environment_code": "api_resource_env",
            "code": "api_resource_base",
            "engine": "mysql",
        },
        actor_id=ADMIN_ID,
    )
    service.create_platform_secret(
        {
            "code": "api_resource_password",
            "value": "api-resource-secret-plaintext",
        },
        actor_id=ADMIN_ID,
    )


def _payload() -> dict[str, object]:
    return {
        "code": "api_resource_mysql",
        "name": "API Resource MySQL",
        "resource_kind": "database",
        "scope_type": "base",
        "environment_code": "api_resource_env",
        "base_code": "api_resource_base",
        "provider_type": "mysql",
        "config": {
            "host": "mysql.example.internal",
            "port": 3306,
            "database": "orders",
            "username": "reader",
        },
        "secret_refs": {
            "password_ref": "secret://platform/api_resource_password",
        },
    }


def test_governed_resource_api_requires_login_and_management_permission() -> None:
    runtime = _runtime()
    _create_topology_and_secret(runtime)
    app = create_app(_settings(), container_factory=lambda _: runtime)

    with TestClient(app) as client:
        assert client.get("/api/platform/resources").status_code == 401
        created = client.post(
            "/api/platform/resources",
            json=_payload(),
            headers={"x-admin-user-id": "local-user"},
        )

    assert created.status_code == 200, created.text
    assert created.json()["draft"]["status"] == "DRAFT"
    runtime.database.close()


def test_governed_resource_api_lifecycle_and_public_status_are_secret_safe() -> None:
    runtime = _runtime()
    _create_topology_and_secret(runtime)
    app = create_app(_settings(), container_factory=lambda _: runtime)
    headers = {"x-admin-user-id": "local-user"}

    with TestClient(app) as client:
        created = client.post(
            "/api/platform/resources",
            json=_payload(),
            headers=headers,
        )
        listed = client.get(
            "/api/platform/resources?resource_kind=database&scope_type=base",
            headers=headers,
        )
        runtime_status = client.get(
            "/api/platform/runtime-generation/status",
            headers=headers,
        )
        publish_before_verify = client.post(
            "/api/platform/resources/api_resource_mysql/publish",
            headers=headers,
        )

    assert created.status_code == listed.status_code == 200
    assert runtime_status.status_code == 200
    assert publish_before_verify.status_code == 400
    resource = listed.json()["resources"][0]
    assert resource["activation_status"] == "EMPTY"
    assert resource["draft"]["secret_refs"] == {
        "password_ref": "secret://platform/api_resource_password"
    }
    combined = created.text + listed.text + runtime_status.text
    assert "api-resource-secret-plaintext" not in combined
    assert "ciphertext" not in combined
    assert "nonce" not in combined
    assert "key_id" not in combined
    runtime.database.close()


def test_governed_resource_api_rejects_arbitrary_or_legacy_secret_fields() -> None:
    runtime = _runtime()
    _create_topology_and_secret(runtime)
    app = create_app(_settings(), container_factory=lambda _: runtime)
    headers = {"x-admin-user-id": "local-user"}
    payload = _payload()
    payload["secret_refs"] = {"password_ref": "env:MYSQL_PASSWORD"}

    with TestClient(app) as client:
        legacy = client.post(
            "/api/platform/resources",
            json=payload,
            headers=headers,
        )
        payload["secret_refs"] = {
            "password_ref": "secret://platform/api_resource_password",
            "arbitrary_ref": "secret://platform/api_resource_password",
        }
        arbitrary = client.post(
            "/api/platform/resources",
            json=payload,
            headers=headers,
        )
        resources = (
            runtime.platform_config_service.governed_resources.list_resources()
        )

    assert legacy.status_code == 400
    assert "env 凭据引用必须先导入凭据中心" in legacy.text
    assert arbitrary.status_code == 400
    assert resources == []
    runtime.database.close()
