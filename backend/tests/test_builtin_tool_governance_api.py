from __future__ import annotations

import json
from uuid import UUID

from fastapi.testclient import TestClient

from app.bootstrap import build_test_container
from app.main import create_app
from app.modules.agent.infrastructure.claude_code_agent_client import (
    TOOL_DEFINITIONS,
)
from app.shared.config import IdentitySettings, Settings


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


def test_builtin_tool_governance_api_full_control_plane_is_bounded_and_idempotent() -> None:
    runtime = build_test_container(_settings(), migrate=True, seed=True)
    app = create_app(_settings(), container_factory=lambda _: runtime)
    headers = {
        "x-admin-user-id": "local-user",
        "x-correlation-id": "builtin-tool-api-test",
    }

    with TestClient(app) as client:
        assert client.get("/api/platform/builtin-tools").status_code == 401
        reconciled = client.post(
            "/api/platform/builtin-tools/reconcile",
            headers=headers,
        )
        listed = client.get(
            "/api/platform/builtin-tools",
            headers=headers,
        )
        verified = client.post(
            "/api/platform/builtin-tools/query_database/verify",
            json={"handler_version": "1.0.0"},
            headers=headers,
        )
        assert verified.status_code == 200, verified.text
        evidence_id = verified.json()["verification"]["id"]
        publish_payload = {
            "handler_version": "1.0.0",
            "verification_id": evidence_id,
            "idempotency_key": "api-publish-query-database-v1",
        }
        published = client.post(
            "/api/platform/builtin-tools/query_database/publish",
            json=publish_payload,
            headers=headers,
        )
        repeated = client.post(
            "/api/platform/builtin-tools/query_database/publish",
            json=publish_payload,
            headers=headers,
        )
        assert published.status_code == repeated.status_code == 200
        release = published.json()["release"]
        detail = client.get(
            "/api/platform/builtin-tools/query_database",
            headers=headers,
        )
        deprecated = client.post(
            f"/api/platform/builtin-tool-releases/{release['id']}/lifecycle",
            json={"status": "DEPRECATED", "reason_code": "API_TEST"},
            headers=headers,
        )
        secret_marker = "must-not-persist-verifier-secret"
        rejected = client.post(
            "/api/platform/builtin-tools/query_database/verify",
            json={
                "handler_version": "1.0.0",
                "password": secret_marker,
            },
            headers={
                **headers,
                "x-correlation-id": "builtin-tool-rejected-test",
            },
        )
        config_audits = runtime.database.execute(
            """
            select * from platform_config_audit
             where entity_type in (
               'handler_registry',
               'builtin_tool_verification',
               'builtin_tool_release'
             )
             order by created_at, id
            """
        )
        release_lifecycle_audits = runtime.database.execute(
            """
            select * from builtin_tool_lifecycle_audit
             where tool_release_id = ?
             order by occurred_at, id
            """,
            (release["id"],),
        )
        denied_audits = runtime.database.execute(
            """
            select * from audit_event
             where event_type = 'admin.builtin_tool.governance.denied'
             order by created_at, id
            """
        )

    assert reconciled.status_code == listed.status_code == 200
    assert reconciled.json() == {
        "summary": {
            "drifted": 0,
            "installed": len(TOOL_DEFINITIONS),
            "missing": 0,
        }
    }
    items = listed.json()["tools"]
    assert len(items) == len(TOOL_DEFINITIONS)
    assert repeated.json()["release"]["id"] == release["id"]
    assert detail.status_code == 200
    tool = detail.json()["tool"]
    assert tool["manifest"]["tool_identifier"] == "query_database"
    assert tool["installation"]["installation_status"] == "INSTALLED"
    assert tool["verifications"][0]["id"] == evidence_id
    assert tool["releases"][0]["id"] == release["id"]
    assert tool["releases"][0]["dependencies"] == {
        "active_agent_publications": 0,
        "active_application_publications": 0,
        "recoverable_jobs": 0,
    }
    assert deprecated.status_code == 200
    assert deprecated.json()["release"]["status"] == "DEPRECATED"
    assert rejected.status_code == 400
    assert rejected.json()["detail"] == {
        "error": {
            "code": "builtin_tool_manual_verification_forbidden",
            "message": "验证结果只能由代码中的固定机器 Verifier 产生",
            "correlation_id": "builtin-tool-rejected-test",
            "retryable": False,
            "details": {
                "operation": "verify",
                "entity_type": "builtin_tool",
                "entity_id": "query_database",
            },
        }
    }

    assert len(config_audits) == 4
    assert {row["action"] for row in config_audits} == {
        "reconcile",
        "verify",
        "publish",
        "deprecated",
    }
    assert {row["actor_id"] for row in config_audits} == {
        "user_local_admin"
    }
    assert {row["correlation_id"] for row in config_audits} == {
        "builtin-tool-api-test"
    }
    parsed_config_audits = [
        {
            **row,
            "before": json.loads(row["before_json"]),
            "after": json.loads(row["after_json"]),
        }
        for row in config_audits
    ]
    verify_audit = next(
        row for row in parsed_config_audits if row["action"] == "verify"
    )
    assert verify_audit["entity_id"] == evidence_id
    assert verify_audit["after"] == {
        "tool_identifier": "query_database",
        "handler_version": "1.0.0",
        "implementation_digest_prefix": release["implementation_digest"][:12],
        "verifier_version": verified.json()["verification"]["verifier_version"],
        "status": "PASSED",
    }
    publish_audit = next(
        row for row in parsed_config_audits if row["action"] == "publish"
    )
    assert publish_audit["entity_id"] == release["id"]
    assert publish_audit["after"] == {
        "tool_identifier": "query_database",
        "release_revision": 1,
        "handler_version": "1.0.0",
        "implementation_digest_prefix": release["implementation_digest"][:12],
        "status": "ACTIVE",
        "verification_id": evidence_id,
    }
    lifecycle_audit = next(
        row
        for row in parsed_config_audits
        if row["action"] == "deprecated"
    )
    assert lifecycle_audit["entity_id"] == release["id"]
    assert lifecycle_audit["after"] == {
        "tool_identifier": "query_database",
        "release_revision": 1,
        "handler_version": "1.0.0",
        "implementation_digest_prefix": release["implementation_digest"][:12],
        "verification_id": evidence_id,
        "status": "DEPRECATED",
        "reason_code": "API_TEST",
    }
    assert [row["reason_code"] for row in release_lifecycle_audits] == [
        "PUBLISHED",
        "API_TEST",
    ]
    assert {row["actor_id"] for row in release_lifecycle_audits} == {
        "user_local_admin"
    }
    assert {row["correlation_id"] for row in release_lifecycle_audits} == {
        "builtin-tool-api-test"
    }

    assert len(denied_audits) == 1
    denied = denied_audits[0]
    assert denied["actor_id"] == "user_local_admin"
    assert denied["status"] == "DENIED"
    denied_payload = json.loads(denied["payload_summary"])
    assert denied_payload["truncated"] is False
    assert json.loads(denied_payload["payload"]) == {
        "operation": "verify",
        "entity_type": "builtin_tool",
        "entity_id": "query_database",
        "error_code": "builtin_tool_manual_verification_forbidden",
        "correlation_id": "builtin-tool-rejected-test",
    }

    combined = (
        listed.text
        + detail.text
        + verified.text
        + published.text
        + rejected.text
        + json.dumps(config_audits, ensure_ascii=False)
        + json.dumps(release_lifecycle_audits, ensure_ascii=False)
        + json.dumps(denied_audits, ensure_ascii=False)
    )
    for forbidden in (
        "implementation_key",
        "password",
        "token_ciphertext",
        "secret_refs",
        "base_url",
        "hostname",
        secret_marker,
    ):
        assert forbidden not in combined.lower()
    runtime.database.close()


def test_builtin_tool_governance_replaces_invalid_correlation_id() -> None:
    runtime = build_test_container(_settings(), migrate=True, seed=True)
    app = create_app(_settings(), container_factory=lambda _: runtime)

    with TestClient(app) as client:
        response = client.post(
            "/api/platform/builtin-tools/reconcile",
            headers={
                "x-admin-user-id": "local-user",
                "x-correlation-id": "bad id",
            },
        )
        audit = runtime.database.execute_one(
            """
            select correlation_id from platform_config_audit
             where entity_type = 'handler_registry' and action = 'reconcile'
            """
        )

    assert response.status_code == 200
    correlation_id = response.headers["x-correlation-id"]
    assert str(UUID(correlation_id)) == correlation_id
    assert audit is not None
    assert audit["correlation_id"] == correlation_id
    runtime.database.close()
