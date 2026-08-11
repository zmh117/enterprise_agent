from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

from app.bootstrap import build_test_container
from app.main import create_app
from app.modules.platform_config.application.governed_resources import (
    ResourceVerificationOutcome,
)
from app.shared.config import IdentitySettings, Settings
from backend.tests.test_unified_identity_rbac import csrf_headers, login

ADMIN_ID = "user_local_admin"
POSTGRES_ADMIN_DSN = os.getenv("GOVERNED_RESOURCE_POSTGRES_DSN", "")


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
            allowed_origins=("http://admin.test",),
        ),
    )


def _runtime():
    return build_test_container(
        _settings(),
        migrate=True,
        seed=True,
    )


@pytest.fixture
def postgres_runtime():
    if not POSTGRES_ADMIN_DSN:
        pytest.skip(
            "set GOVERNED_RESOURCE_POSTGRES_DSN to run the PostgreSQL resource-list regression"
        )

    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    database_name = f"governed_resource_test_{uuid.uuid4().hex}"
    with psycopg.connect(POSTGRES_ADMIN_DSN, autocommit=True) as admin:
        admin.execute(sql.SQL("create database {}").format(sql.Identifier(database_name)))
    parameters = conninfo_to_dict(POSTGRES_ADMIN_DSN)
    parameters["dbname"] = database_name
    runtime = None
    try:
        runtime = build_test_container(
            Settings(
                database_dsn=make_conninfo(**parameters),
                app_config_master_key="test-only-master-key",
                environment="test",
                identity=IdentitySettings(
                    enabled=True,
                    web_admin_enabled=True,
                    published_agent_runtime_enabled=True,
                    test_identity_headers_enabled=True,
                    cookie_secure=False,
                    allowed_origins=("http://admin.test",),
                ),
            ),
            migrate=True,
            seed=True,
        )
        yield runtime
    finally:
        if runtime is not None:
            runtime.database.close()
        with psycopg.connect(POSTGRES_ADMIN_DSN, autocommit=True) as admin:
            admin.execute(
                """
                select pg_terminate_backend(pid)
                  from pg_stat_activity
                 where datname = %s and pid <> pg_backend_pid()
                """,
                (database_name,),
            )
            admin.execute(sql.SQL("drop database {}").format(sql.Identifier(database_name)))


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
        headers = csrf_headers(login(client))
        created = client.post(
            "/api/platform/resources",
            json=_payload(),
            headers=headers,
        )

    assert created.status_code == 200, created.text
    assert created.json()["draft"]["status"] == "DRAFT"
    runtime.database.close()


def test_governed_resource_api_lifecycle_and_public_status_are_secret_safe() -> None:
    runtime = _runtime()
    _create_topology_and_secret(runtime)
    app = create_app(_settings(), container_factory=lambda _: runtime)

    with TestClient(app) as client:
        headers = csrf_headers(login(client))
        created = client.post(
            "/api/platform/resources",
            json=_payload(),
            headers=headers,
        )
        listed = client.get(
            "/api/platform/resources?resource_kind=database&scope_type=base",
            headers=headers,
        )
        publish_before_verify = client.post(
            "/api/platform/resources/api_resource_mysql/publish",
            headers=headers,
        )

    assert created.status_code == listed.status_code == 200
    assert publish_before_verify.status_code == 400
    resource = listed.json()["resources"][0]
    assert resource["draft"]["secret_refs"] == {
        "password_ref": "secret://platform/api_resource_password"
    }
    combined = created.text + listed.text
    assert "api-resource-secret-plaintext" not in combined
    assert "ciphertext" not in combined
    assert "nonce" not in combined
    assert "key_id" not in combined
    runtime.database.close()


def test_governed_resource_revision_action_routes_disable_and_archive() -> None:
    runtime = _runtime()
    _create_topology_and_secret(runtime)
    resources = runtime.platform_config_service.governed_resources
    resources.create_resource(_payload(), actor_id=ADMIN_ID)

    class PassingVerifier:
        def verify(self, **_kwargs: object) -> ResourceVerificationOutcome:
            return ResourceVerificationOutcome(
                status="PASSED",
                provider_contract_version="mysql_v1",
                checks={"connection": True, "read_only": True},
            )

    resources.verify_draft(
        "api_resource_mysql",
        actor_id=ADMIN_ID,
        verifier=PassingVerifier(),
    )
    published = resources.publish_draft(
        "api_resource_mysql",
        actor_id=ADMIN_ID,
    )
    app = create_app(_settings(), container_factory=lambda _: runtime)
    revision_path = f"/api/platform/resources/api_resource_mysql/revisions/{published['id']}"

    with TestClient(app) as client:
        headers = csrf_headers(login(client))
        disabled = client.post(f"{revision_path}/disable", headers=headers)
        archived = client.post(f"{revision_path}/archive", headers=headers)
        separated = client.get(
            "/api/platform/resources?lifecycle_status=enabled&revision_status=ARCHIVED",
            headers=headers,
        )

    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["revision"]["status"] == "DISABLED"
    assert archived.status_code == 200, archived.text
    assert archived.json()["revision"]["status"] == "ARCHIVED"
    assert separated.status_code == 200, separated.text
    separated_resource = separated.json()["resources"][0]
    assert separated_resource["status"] == "enabled"
    assert separated_resource["published_revision"]["status"] == "ARCHIVED"
    runtime.database.close()


def test_governed_resource_identity_lifecycle_routes_are_separate() -> None:
    runtime = _runtime()
    _create_topology_and_secret(runtime)
    resources = runtime.platform_config_service.governed_resources
    created = resources.create_resource(_payload(), actor_id=ADMIN_ID)
    app = create_app(_settings(), container_factory=lambda _: runtime)
    lifecycle_path = "/api/platform/resources/api_resource_mysql/lifecycle"

    with TestClient(app) as client:
        headers = csrf_headers(login(client))
        disabled = client.post(
            f"{lifecycle_path}/disable",
            json={"expected_revision": created["resource"]["revision"]},
            headers=headers,
        )
        restored = client.post(
            f"{lifecycle_path}/restore",
            json={"expected_revision": 2},
            headers=headers,
        )

    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["resource"]["status"] == "disabled"
    assert disabled.json()["resource"]["revision"] == 2
    assert restored.status_code == 200, restored.text
    assert restored.json()["resource"]["status"] == "enabled"
    assert restored.json()["resource"]["revision"] == 3
    runtime.database.close()


def test_postgres_lists_first_resource_after_creation(postgres_runtime) -> None:
    _create_topology_and_secret(postgres_runtime)
    app = create_app(
        postgres_runtime.settings,
        container_factory=lambda _: postgres_runtime,
    )

    with TestClient(app) as client:
        headers = csrf_headers(login(client))
        created = client.post(
            "/api/platform/resources",
            json=_payload(),
            headers=headers,
        )
        listed = client.get(
            "/api/platform/resources",
            headers=headers,
        )

    assert created.status_code == 200, created.text
    assert listed.status_code == 200, listed.text
    assert [item["code"] for item in listed.json()["resources"]] == ["api_resource_mysql"]


def test_governed_resource_api_rejects_arbitrary_or_legacy_secret_fields() -> None:
    runtime = _runtime()
    _create_topology_and_secret(runtime)
    app = create_app(_settings(), container_factory=lambda _: runtime)
    payload = _payload()
    payload["secret_refs"] = {"password_ref": "env:MYSQL_PASSWORD"}

    with TestClient(app) as client:
        headers = csrf_headers(login(client))
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
        resources = runtime.platform_config_service.governed_resources.list_resources()

    assert legacy.status_code == 400
    assert "env 凭据引用必须先导入凭据中心" in legacy.text
    assert arbitrary.status_code == 400
    assert resources == []
    runtime.database.close()
