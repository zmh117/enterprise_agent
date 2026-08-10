from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient

from app.bootstrap import build_test_container
from app.main import create_app
from app.shared.config import IdentitySettings
from backend.tests.helpers import test_settings as build_test_settings


def test_managed_channel_browser_uses_opaque_credential_id() -> None:
    settings = replace(
        build_test_settings(),
        environment="test",
        identity=IdentitySettings(
            enabled=True,
            web_admin_enabled=True,
            test_identity_headers_enabled=True,
            cookie_secure=False,
        ),
    )
    container = build_test_container(settings, migrate=True, seed=True)
    credential = container.platform_config_service.create_platform_secret(
        {"code": "dingtalk_robot_secret", "purpose": "dingtalk", "value": "secret-value"},
        actor_id="user_local_admin",
    )
    enterprise = container.managed_channel_service.create_dingtalk_enterprise(
        name="Browser enterprise",
        actor_id="user_local_admin",
    )
    app = create_app(settings, container_factory=lambda _: container)
    headers = {
        "x-admin-user-id": "user_local_admin",
        "Idempotency-Key": "create-browser-channel",
    }
    body = {
        "expected_revision": 0,
        "name": "Browser robot",
        "client_id": "browser-robot-client-id",
        "credential_id": credential["id"],
        "dingtalk_enterprise_id": enterprise["id"],
        "allow_private_chat": True,
        "allow_group_chat": True,
        "require_group_at": True,
        "enabled": False,
    }

    with TestClient(app) as client:
        candidates = client.get(
            "/api/admin/managed-channels/credential-candidates",
            headers=headers,
        )
        created = client.post(
            "/api/admin/managed-channels/dingtalk-app-robots",
            headers=headers,
            json=body,
        )
        forged = client.post(
            "/api/admin/managed-channels/dingtalk-app-robots",
            headers={**headers, "Idempotency-Key": "forged-channel-secret"},
            json={**body, "client_id": "forged-client", "client_secret": "plaintext"},
        )
        stored = container.database.execute_one(
            "select secret_ref from integration_connector where id = ?",
            (created.json()["channel"]["id"],),
        )

    assert candidates.status_code == created.status_code == 200
    assert credential["id"] in {item["id"] for item in candidates.json()["items"]}
    assert "secret://" not in candidates.text + created.text
    assert "secret-value" not in candidates.text + created.text
    assert stored["secret_ref"] == credential["secret_ref"]
    assert forged.status_code == 422
