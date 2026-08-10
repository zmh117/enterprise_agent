from __future__ import annotations

import json
from dataclasses import replace

from fastapi.testclient import TestClient

from app.bootstrap import build_test_container
from app.main import create_app
from app.shared.config import IdentitySettings
from backend.tests.helpers import test_settings as build_test_settings


def test_resource_form_resolves_opaque_credential_id_only_on_server() -> None:
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
        {"code": "database_password", "purpose": "database", "value": "secret-value"},
        actor_id="user_local_admin",
    )
    app = create_app(settings, container_factory=lambda _: container)
    headers = {
        "x-admin-user-id": "user_local_admin",
        "Idempotency-Key": "database-resource-draft",
    }
    body = {
        "kind": "DATABASE",
        "code": "production_db",
        "name": "Production Database",
        "expected_revision": 0,
        "provider": "postgresql",
        "host": "database.internal",
        "port": 5432,
        "database_name": "operations",
        "schema_name": "public",
        "username": "agent_readonly",
        "credential_id": credential["id"],
        "allowed_tables": ["incident", "service"],
        "max_rows": 200,
        "timeout_seconds": 10,
        "tls": True,
    }

    with TestClient(app) as client:
        candidates = client.get(
            "/api/admin/mcp/resource-credential-candidates",
            headers=headers,
        )
        created = client.post(
            "/api/admin/mcp/resource-drafts",
            headers=headers,
            json=body,
        )
        form = client.get(
            "/api/admin/mcp/resource-forms/production_db",
            headers=headers,
        )
        forged = client.post(
            "/api/admin/mcp/resource-drafts",
            headers={**headers, "Idempotency-Key": "forged-resource-ref"},
            json={**body, "password_ref": "secret://platform/another-secret"},
        )
        stored = container.database.execute_one(
            """
            select manifest_json from mcp_resource_draft
             where resource_id = (select id from mcp_resource where code = 'production_db')
             order by draft_revision desc limit 1
            """
        )

    assert candidates.status_code == created.status_code == form.status_code == 200
    assert candidates.json()["items"][0]["id"] == credential["id"]
    for response in (candidates, created, form):
        assert "secret://" not in response.text
        assert "secret-value" not in response.text
    assert form.json()["form"]["credential_id"] == credential["id"]
    assert forged.status_code == 422

    manifest = json.loads(str(stored["manifest_json"]))
    assert manifest["spec"]["password_ref"] == credential["secret_ref"]
