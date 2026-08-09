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
        # The lightweight portal intentionally exposes no retired admin powers.
        assert not any(me.json()["user"]["capabilities"].values())
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
