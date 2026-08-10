from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient

from app.bootstrap import build_test_container
from app.main import create_app
from app.shared.config import IdentitySettings
from backend.tests.helpers import test_settings as build_test_settings


def test_browser_credential_dto_never_exposes_internal_secret_reference() -> None:
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
    created = container.platform_config_service.create_platform_secret(
        {"code": "browser_safe_credential", "purpose": "test", "value": "secret-value"},
        actor_id="user_local_admin",
    )
    assert created["secret_ref"].startswith("secret://platform/")
    try:
        with TestClient(create_app(settings, container_factory=lambda _: container)) as client:
            headers = {"x-admin-user-id": "user_local_admin"}
            listed = client.get("/api/platform/secrets", headers=headers)
            detail = client.get(
                "/api/platform/secrets/browser_safe_credential", headers=headers
            )
            assert listed.status_code == detail.status_code == 200
            projections = [*listed.json()["secrets"], detail.json()["secret"]]
            for projection in projections:
                assert set(projection).isdisjoint(
                    {
                        "secret_ref",
                        "ref",
                        "value",
                        "ciphertext",
                        "nonce",
                        "tag",
                        "authentication_tag",
                        "key_id",
                        "master_key",
                    }
                )
    finally:
        container.database.close()
