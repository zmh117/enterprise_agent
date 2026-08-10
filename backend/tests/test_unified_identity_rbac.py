from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.bootstrap import Container, build_test_container
from app.main import create_app
from app.shared.config import IdentitySettings, Settings
from app.shared.exceptions import PermissionDenied
from backend.tests.helpers import test_settings as base_test_settings


ADMIN_ID = "user_local_admin"
ADMIN_USERNAME = "local-user"
ADMIN_PASSWORD = "local-admin-change-me"
ORIGIN = "http://admin.test"


def unified_settings() -> Settings:
    return replace(
        base_test_settings(),
        environment="test",
        identity=IdentitySettings(
            enabled=True,
            web_admin_enabled=True,
            published_agent_runtime_enabled=True,
            test_identity_headers_enabled=False,
            cookie_secure=False,
            allowed_origins=(ORIGIN,),
        ),
    )


def unified_container() -> Container:
    return build_test_container(unified_settings(), migrate=True, seed=True)


def login(
    client: TestClient, username: str = ADMIN_USERNAME, password: str = ADMIN_PASSWORD
) -> str:
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    csrf = client.cookies.get("enterprise_agent_csrf")
    assert csrf
    return csrf


def csrf_headers(csrf: str) -> dict[str, str]:
    return {"origin": ORIGIN, "x-csrf-token": csrf}


def test_web_auth_uses_hashed_sessions_csrf_and_rejects_forged_headers() -> None:
    settings = unified_settings()
    container = unified_container()
    app = create_app(settings, container_factory=lambda _: container)

    with TestClient(app) as client:
        unknown = client.post(
            "/api/auth/login",
            json={"username": "missing-user", "password": "wrong-password"},
        )
        wrong = client.post(
            "/api/auth/login",
            json={"username": ADMIN_USERNAME, "password": "wrong-password"},
        )
        assert unknown.status_code == wrong.status_code == 401
        assert unknown.json() == wrong.json()

        csrf = login(client)
        me = client.get("/api/auth/me")
        assert me.status_code == 200
        capabilities = me.json()["user"]["capabilities"]
        assert capabilities["agents_manage"] is True
        assert capabilities["applications_manage"] is True
        assert capabilities["mcp_tools_manage"] is True
        assert capabilities["secrets_manage"] is True
        assert capabilities["dashboard_read"] is True
        assert capabilities["users_manage"] is True
        assert capabilities["roles_manage"] is True
        assert capabilities["identities_manage"] is True
        assert capabilities["channels_manage"] is True
        assert capabilities["jobs_debug"] is True
        assert capabilities["mcp_servers_read"] is True
        assert capabilities["mcp_resources_manage"] is True
        session_token = client.cookies.get("enterprise_agent_session")
        assert session_token
        stored = container.database.execute_one(
            "select token_hash, csrf_hash from user_session order by created_at desc limit 1"
        )
        assert stored
        assert stored["token_hash"] == hashlib.sha256(session_token.encode()).hexdigest()
        assert stored["token_hash"] != session_token
        assert stored["csrf_hash"] == hashlib.sha256(csrf.encode()).hexdigest()
        assert ADMIN_PASSWORD not in json.dumps(stored)

        assert client.post("/api/auth/logout").status_code == 403
        assert client.post("/api/auth/logout", headers=csrf_headers(csrf)).status_code == 200
        forged = client.get("/api/auth/me", headers={"x-admin-user-id": ADMIN_ID})
        assert forged.status_code == 401


def test_session_expiry_password_change_and_owned_revocation_fail_closed() -> None:
    container = unified_container()
    principal, token, _csrf = container.auth_service.login(
        username=ADMIN_USERNAME,
        password=ADMIN_PASSWORD,
    )
    container.database.execute(
        "update user_session set idle_expires_at = ? where id = ?",
        ("2000-01-01T00:00:00+00:00", principal.session_id),
    )
    with pytest.raises(PermissionDenied):
        container.auth_service.authenticate_session(token)

    principal, token, _csrf = container.auth_service.login(
        username=ADMIN_USERNAME,
        password=ADMIN_PASSWORD,
    )
    container.auth_service.change_password(
        principal=principal,
        current=ADMIN_PASSWORD,
        new="new-local-admin-password",
    )
    with pytest.raises(PermissionDenied):
        container.auth_service.authenticate_session(token)
    password_row = container.database.execute_one(
        "select password_hash from user_password_credential where user_id = ?",
        (ADMIN_ID,),
    )
    assert password_row
    assert password_row["password_hash"] != "new-local-admin-password"
    assert str(password_row["password_hash"]).startswith("$argon2id$")

    settings = unified_settings()
    api_container = unified_container()
    with TestClient(create_app(settings, container_factory=lambda _: api_container)) as client:
        csrf = login(client)
        session_id = api_container.database.execute_one(
            "select id from user_session where status = 'active' order by created_at desc limit 1"
        )
        assert session_id
        revoked = client.delete(
            f"/api/auth/sessions/{session_id['id']}",
            headers=csrf_headers(csrf),
        )
        assert revoked.status_code == 200
        assert client.get("/api/auth/me").status_code == 401


def test_control_plane_writes_require_csrf_revision_idempotency_and_safe_conflicts() -> None:
    settings = unified_settings()
    container = unified_container()
    container.model_connection_service.dns_resolver = lambda *args, **kwargs: [
        (2, 1, 6, "", ("1.1.1.1", 443))
    ]
    app = create_app(settings, container_factory=lambda _: container)
    agent_body = {
        "expected_revision": 0,
        "code": "governed-agent",
        "name": "Governed Agent",
        "description": "",
        "project_code": "default",
    }
    application_body = {
        "expected_revision": 0,
        "code": "governed-application",
        "name": "Governed Application",
        "description": "",
        "project_code": "default",
        "owner_user_id": ADMIN_ID,
    }
    tool_body = {
        "expected_revision": 0,
        "code": "governed-tool",
        "name": "Governed Tool",
        "catalog_key": "ones-mcp/ones_work_item_search",
        "resource_deployment_id": "",
    }

    try:
        with TestClient(app) as client:
            csrf = login(client)
            assert (
                client.post(
                    "/api/admin/agents",
                    json=agent_body,
                    headers={"Idempotency-Key": "agent-create"},
                ).status_code
                == 403
            )

            protected_headers = {
                **csrf_headers(csrf),
                "Idempotency-Key": "agent-create",
            }
            assert (
                client.post(
                    "/api/admin/agents",
                    json={
                        key: value
                        for key, value in agent_body.items()
                        if key != "expected_revision"
                    },
                    headers=protected_headers,
                ).status_code
                == 422
            )
            assert (
                client.post(
                    "/api/admin/agents",
                    json=agent_body,
                    headers=csrf_headers(csrf),
                ).status_code
                == 422
            )

            created_agent = client.post(
                "/api/admin/agents",
                json=agent_body,
                headers=protected_headers,
            )
            assert created_agent.status_code == 200, created_agent.text
            replayed_agent = client.post(
                "/api/admin/agents",
                json=agent_body,
                headers=protected_headers,
            )
            assert replayed_agent.json() == created_agent.json()

            stale = client.put(
                "/api/admin/agents/governed-agent",
                json={
                    "expected_revision": 999,
                    "name": "Governed Agent",
                    "description": "",
                    "project_code": "default",
                    "status": "enabled",
                },
                headers={
                    **csrf_headers(csrf),
                    "Idempotency-Key": "agent-stale-update",
                },
            )
            assert stale.status_code == 409
            assert stale.json()["detail"]["code"] == "revision_conflict"
            assert stale.json()["detail"]["current_revision"] == 1

            created_application = client.post(
                "/api/admin/business-applications",
                json=application_body,
                headers={
                    **csrf_headers(csrf),
                    "Idempotency-Key": "application-create",
                },
            )
            assert created_application.status_code == 200, created_application.text
            created_tool = client.post(
                "/api/admin/mcp/tool-publications",
                json=tool_body,
                headers={
                    **csrf_headers(csrf),
                    "Idempotency-Key": "tool-create",
                },
            )
            assert created_tool.status_code == 200, created_tool.text

            model_connection = client.get("/api/admin/model-connections/default-deepseek-anthropic")
            assert model_connection.status_code == 200
            model_payload = json.dumps(model_connection.json(), ensure_ascii=False).lower()
            for forbidden in (
                "api_key_secret_id",
                "secret://",
                "ciphertext",
                "nonce",
                "base_url",
                "https://api.deepseek.com/anthropic",
            ):
                assert forbidden not in model_payload
            saved_model_revision = client.put(
                "/api/admin/model-connections/default-deepseek-anthropic/revision",
                json={
                    "expected_revision": 1,
                    "config": {
                        "schema_version": 1,
                        "protocol": "anthropic_compatible",
                        "base_url": "https://api.deepseek.com/anthropic",
                        "model": "deepseek-v4-flash",
                        "default_opus_model": "deepseek-v4-flash",
                        "default_sonnet_model": "deepseek-v4-flash",
                        "default_haiku_model": "deepseek-v4-flash",
                        "subagent_model": "deepseek-v4-flash",
                        "effort_level": "max",
                    },
                },
                headers={
                    **csrf_headers(csrf),
                    "Idempotency-Key": "model-revision-save",
                },
            )
            assert saved_model_revision.status_code == 200, saved_model_revision.text
            saved_payload = json.dumps(saved_model_revision.json(), ensure_ascii=False).lower()
            assert "base_url" not in saved_payload
            assert "https://api.deepseek.com/anthropic" not in saved_payload
            assert (
                client.put(
                    "/api/admin/model-connections/default-deepseek-anthropic/revision",
                    json={
                        "expected_revision": 1,
                        "config": model_connection.json()["connection"]["current_revision"][
                            "config"
                        ],
                    },
                    headers=csrf_headers(csrf),
                ).status_code
                == 422
            )
            assert (
                client.post(
                    "/api/admin/model-connections/default-deepseek-anthropic/credential",
                    json={"expected_revision": 1, "api_key": "not-submitted"},
                    headers={"Idempotency-Key": "model-credential-no-csrf"},
                ).status_code
                == 403
            )

            audits = container.database.execute(
                """
                select event_type, payload_summary from audit_event
                 where event_type in (
                   'agent.definition.created',
                   'business_application.created',
                   'mcp.tool.created'
                 )
                """
            )
            assert len(audits) == 3
            serialized = json.dumps(audits, ensure_ascii=False).lower()
            for forbidden in ("password", "authorization", "secret://", "api_key"):
                assert forbidden not in serialized
    finally:
        container.database.close()
