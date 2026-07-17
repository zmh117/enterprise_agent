from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.bootstrap import Container, build_test_container
from app.main import create_app
from app.modules.identity.application.legacy_migration import (
    LegacyIdentityMigrationService,
)
from app.modules.platform_config.infrastructure import PlatformConfigRepository
from app.shared.config import IdentitySettings, Settings
from app.shared.exceptions import NonRetryableExecutionError, PermissionDenied
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
            permission_shadow_mode=False,
            cookie_secure=False,
            allowed_origins=(ORIGIN,),
        ),
    )


def unified_container() -> Container:
    return build_test_container(unified_settings(), migrate=True, seed=True)


def login(client: TestClient, username: str = ADMIN_USERNAME, password: str = ADMIN_PASSWORD) -> str:
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
        assert me.json()["user"]["capabilities"] == {
            "users_manage": True,
            "roles_manage": True,
            "identities_manage": True,
            "agent_edit": True,
            "agent_publish": True,
            "audit_read": True,
        }
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

        missing_csrf = client.post(
            "/api/admin/users",
            json={"username": "operator-a", "display_name": "Operator A"},
        )
        assert missing_csrf.status_code == 403

        created = client.post(
            "/api/admin/users",
            headers=csrf_headers(csrf),
            json={
                "username": "operator-a",
                "display_name": "Operator A",
                "password": "operator-a-password",
            },
        )
        assert created.status_code == 200, created.text
        assert "password" not in json.dumps(created.json()).lower()
        assert "argon2" not in json.dumps(created.json()).lower()

        client.cookies.clear()
        forged = client.get(
            "/api/admin/users",
            headers={"x-admin-user-id": ADMIN_ID},
        )
        assert forged.status_code == 401


def test_user_disable_revokes_web_sessions_but_identity_disable_only_blocks_dingtalk() -> None:
    settings = unified_settings()
    container = unified_container()
    app = create_app(settings, container_factory=lambda _: container)

    with TestClient(app) as client:
        login(client)
        identity = container.identity_repository.get_external_identity(
            "identity_local_dingtalk"
        )
        container.identity_service.set_identity_status(
            actor_id=ADMIN_ID,
            identity_id=str(identity["id"]),
            status="disabled",
            expected_revision=int(identity["revision"]),
        )

        denied = container.dingtalk_stream_message_service.handle_callback(
            payload={
                "conversationId": "conversation-disabled-identity",
                "senderStaffId": "local-user",
                "msgId": "message-disabled-identity",
                "text": {"content": "check status"},
            },
            correlation_id="correlation-disabled-identity",
        )
        assert denied.accepted is False
        assert denied.status == "permission_denied"
        assert client.get("/api/auth/me").status_code == 200

        user = container.identity_repository.get_user(ADMIN_ID)
        container.identity_admin_service.update_user(
            actor_id=ADMIN_ID,
            user_id=ADMIN_ID,
            expected_revision=int(user["revision"]),
            display_name=str(user["display_name"]),
            email=str(user["email"]),
            status="disabled",
        )
        assert client.get("/api/auth/me").status_code == 401


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
    with TestClient(
        create_app(settings, container_factory=lambda _: api_container)
    ) as client:
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


def test_trusted_dingtalk_binding_tenant_isolation_conflict_and_unknown_fail_closed() -> None:
    container = unified_container()
    first = container.identity_repository.create_user(
        username="tenant-user-a", display_name="Tenant User A"
    )
    second = container.identity_repository.create_user(
        username="tenant-user-b", display_name="Tenant User B"
    )

    bound = container.identity_service.bind_dingtalk(
        actor_id=ADMIN_ID,
        user_id=str(first["id"]),
        expected_user_revision=int(first["revision"]),
        tenant_code="default",
        external_subject_id="staff-shared",
        connector_id="connector-dingtalk-stream-default",
    )
    assert bound["user_id"] == first["id"]

    with pytest.raises(NonRetryableExecutionError) as conflict:
        container.identity_service.bind_dingtalk(
            actor_id=ADMIN_ID,
            user_id=str(second["id"]),
            expected_user_revision=int(second["revision"]),
            tenant_code="default",
            external_subject_id="staff-shared",
            connector_id="connector-dingtalk-stream-default",
        )
    assert conflict.value.error_code == "identity_conflict"

    with pytest.raises(PermissionDenied):
        container.identity_service.bind_dingtalk(
            actor_id=ADMIN_ID,
            user_id=str(second["id"]),
            expected_user_revision=int(second["revision"]),
            tenant_code="tenant-b",
            external_subject_id="staff-shared",
            connector_id="connector-dingtalk-stream-default",
        )

    container.database.execute(
        """
        insert into integration_connector
          (id, connector_type, name, base_url, enabled, metadata,
           allow_ingress, allow_delivery, created_at, updated_at)
        values (?, 'dingtalk_enterprise_stream', ?, '', 1, ?, 1, 0,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        (
            "connector-dingtalk-stream-tenant-b",
            "tenant-b-stream",
            '{"tenant_code":"tenant-b"}',
        ),
    )
    isolated = container.identity_service.bind_dingtalk(
        actor_id=ADMIN_ID,
        user_id=str(second["id"]),
        expected_user_revision=int(second["revision"]),
        tenant_code="tenant-b",
        external_subject_id="staff-shared",
        connector_id="connector-dingtalk-stream-tenant-b",
    )
    assert isolated["user_id"] == second["id"]

    before_jobs = container.agent_repository.count_rows("agent_job")
    before_queue = len(container.message_bus.jobs) if container.message_bus else 0
    denied = container.dingtalk_stream_message_service.handle_callback(
        payload={
            "conversationId": "conversation-unknown",
            "senderStaffId": "unknown-staff",
            "msgId": "message-unknown",
            "text": {"content": "check status"},
        },
        correlation_id="correlation-unknown",
    )
    assert denied.accepted is False
    assert denied.ack_status == "OK"
    assert container.agent_repository.count_rows("agent_job") == before_jobs
    assert (len(container.message_bus.jobs) if container.message_bus else 0) == before_queue

    secret_marker = "https://secret.example/session-webhook"
    container.dingtalk_stream_message_service.handle_callback(
        payload={
            "conversationId": "conversation-sensitive",
            "senderStaffId": "unknown-staff",
            "msgId": "message-sensitive",
            "sessionWebhook": secret_marker,
            "accessToken": "super-sensitive-token",
            "text": {"content": "check status"},
        },
        correlation_id="correlation-sensitive",
    )
    audit_text = json.dumps(
        container.database.execute("select payload_summary from audit_event"),
        ensure_ascii=False,
    )
    assert secret_marker not in audit_text
    assert "super-sensitive-token" not in audit_text


def test_rbac_deny_wins_disabled_role_and_platform_scope_are_enforced() -> None:
    container = unified_container()
    repository = container.identity_repository
    user = repository.create_user(username="diagnostic-user", display_name="Diagnostic User")
    role = repository.create_role(code="diagnostic-reader", name="Diagnostic Reader")
    membership = repository.assign_role(
        user_id=str(user["id"]), role_id=str(role["id"]), expected_revision=0
    )
    repository.upsert_policy(
        policy_id="policy-diagnostic-reader-tool",
        subject_type="role",
        subject_code="diagnostic-reader",
        resource_type="tool",
        resource_code="query_database",
        action="use",
        effect="allow",
        expected_revision=0,
    )
    allowed = container.authorization_evaluator.decide(
        user_id=str(user["id"]),
        resource_type="tool",
        resource_code="query_database",
        action="use",
    )
    assert allowed.allowed is True

    repository.upsert_policy(
        policy_id="policy-diagnostic-user-deny",
        subject_type="user",
        subject_code=str(user["id"]),
        resource_type="tool",
        resource_code="query_database",
        action="use",
        effect="deny",
        priority=1,
        expected_revision=0,
    )
    denied = container.authorization_evaluator.decide(
        user_id=str(user["id"]),
        resource_type="tool",
        resource_code="query_database",
        action="use",
    )
    assert denied.allowed is False
    assert denied.reason == "explicit_deny"
    assert "password" not in json.dumps(denied.trace).lower()

    with pytest.raises(NonRetryableExecutionError):
        repository.assign_role(
            user_id=str(user["id"]),
            role_id=str(role["id"]),
            expected_revision=int(membership["revision"]) - 1,
        )

    scope_user = repository.create_user(username="scope-user", display_name="Scope User")
    scope_role = repository.create_role(code="scope-reader", name="Scope Reader")
    repository.assign_role(
        user_id=str(scope_user["id"]), role_id=str(scope_role["id"]), expected_revision=0
    )
    topology = PlatformConfigRepository(container.database)
    topology.upsert_environment(code="prod")
    topology.upsert_base(environment_code="prod", code="base-a", engine="postgresql")
    topology.upsert_base(environment_code="prod", code="base-b", engine="postgresql")
    topology.upsert_workshop(
        environment_code="prod", base_code="base-a", code="ws-denied"
    )
    topology.upsert_access_grant(
        subject_type="role",
        subject_code="scope-reader",
        effect="allow",
        environment_code="prod",
        base_code="base-a",
        tool_scope=["query_database"],
    )
    topology.upsert_access_grant(
        subject_type="role",
        subject_code="scope-reader",
        effect="deny",
        environment_code="prod",
        base_code="base-a",
        workshop_code="ws-denied",
        tool_scope=["query_database"],
        priority=1,
    )
    evaluator = container.authorization_evaluator
    assert evaluator.decide_platform_scope(
        user_id=str(scope_user["id"]),
        environment="prod",
        base="base-a",
        tool_name="query_database",
    ).allowed
    denied_workshop = evaluator.decide_platform_scope(
        user_id=str(scope_user["id"]),
        environment="prod",
        base="base-a",
        workshop="ws-denied",
        tool_name="query_database",
    )
    assert denied_workshop.allowed is False
    assert denied_workshop.reason == "explicit_scope_deny"
    assert not evaluator.decide_platform_scope(
        user_id=str(scope_user["id"]),
        environment="prod",
        base="base-b",
        tool_name="query_database",
    ).allowed

    repository.update_role(
        str(scope_role["id"]),
        expected_revision=int(scope_role["revision"]),
        name=str(scope_role["name"]),
        description=str(scope_role["description"]),
        status="disabled",
    )
    assert not evaluator.decide_platform_scope(
        user_id=str(scope_user["id"]),
        environment="prod",
        base="base-a",
        tool_name="query_database",
    ).allowed


def test_legacy_reconciliation_dry_run_is_read_only_and_ambiguous_subject_is_not_copied() -> None:
    container = unified_container()
    repository = container.identity_repository
    unique_user = repository.create_user(username="legacy-unique", display_name="Legacy Unique")
    repository.bind_external_identity(
        user_id=str(unique_user["id"]),
        provider="dingtalk",
        tenant_code="tenant-unique",
        external_subject_id="legacy-staff-unique",
        connector_id="legacy-test-connector",
    )
    repository.upsert_policy(
        policy_id="legacy-policy-unique",
        subject_type="user",
        subject_code="legacy-staff-unique",
        resource_type="project",
        resource_code="default",
        action="use",
        effect="allow",
        expected_revision=0,
    )

    ambiguous_a = repository.create_user(username="legacy-a", display_name="Legacy A")
    ambiguous_b = repository.create_user(username="legacy-b", display_name="Legacy B")
    for user, tenant in ((ambiguous_a, "tenant-a"), (ambiguous_b, "tenant-b")):
        repository.bind_external_identity(
            user_id=str(user["id"]),
            provider="dingtalk",
            tenant_code=tenant,
            external_subject_id="legacy-staff-ambiguous",
            connector_id=f"legacy-{tenant}",
        )
    repository.upsert_policy(
        policy_id="legacy-policy-ambiguous",
        subject_type="user",
        subject_code="legacy-staff-ambiguous",
        resource_type="project",
        resource_code="default",
        action="use",
        effect="allow",
        expected_revision=0,
    )

    migration = LegacyIdentityMigrationService(repository)
    before_audit = container.agent_repository.count_rows("identity_migration_audit")
    before_policies = container.agent_repository.count_rows("permission_policy")
    dry_run = migration.reconcile(apply=False)
    assert container.agent_repository.count_rows("identity_migration_audit") == before_audit
    assert container.agent_repository.count_rows("permission_policy") == before_policies
    statuses = {
        item["legacy_subject_code"]: item["status"] for item in dry_run["subjects"]
    }
    assert statuses["legacy-staff-unique"] == "ready"
    assert statuses["legacy-staff-ambiguous"] == "ambiguous"

    migration.reconcile(apply=True)
    copied = container.database.execute_one(
        """
        select id from permission_policy
        where subject_type = 'user' and subject_code = ?
          and resource_type = 'project' and resource_code = 'default'
        """,
        (unique_user["id"],),
    )
    assert copied is not None
    for user in (ambiguous_a, ambiguous_b):
        assert container.database.execute_one(
            "select id from permission_policy where subject_type = 'user' and subject_code = ?",
            (user["id"],),
        ) is None


def test_admin_api_revision_conflicts_and_typed_agent_draft_errors() -> None:
    settings = unified_settings()
    container = unified_container()
    app = create_app(settings, container_factory=lambda _: container)

    with TestClient(app) as client:
        assert client.get("/api/platform/secrets").status_code == 401
        csrf = login(client)
        headers = csrf_headers(csrf)
        assert client.get("/api/platform/secrets").status_code == 200
        created = client.post(
            "/api/admin/roles",
            headers=headers,
            json={"code": "api-role", "name": "API Role"},
        )
        assert created.status_code == 200
        role = created.json()["role"]
        first = client.put(
            f"/api/admin/roles/{role['id']}",
            headers=headers,
            json={
                "expected_revision": role["revision"],
                "name": "API Role Updated",
                "description": "",
                "status": "enabled",
            },
        )
        assert first.status_code == 200
        stale = client.put(
            f"/api/admin/roles/{role['id']}",
            headers=headers,
            json={
                "expected_revision": role["revision"],
                "name": "Stale",
                "description": "",
                "status": "enabled",
            },
        )
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "revision_conflict"

        raw_security_field = client.put(
            "/api/admin/agents/default-diagnostic-agent/draft",
            headers=headers,
            json={
                "expected_revision": 1,
                "config": {
                    "business_role": "Diagnostic Agent",
                    "business_instructions": "Use evidence.",
                    "model_policy": {
                        "model": "claude-sonnet-4-20250514",
                        "api_key": "must-not-be-accepted",
                    },
                    "execution": {"max_turns": 12, "timeout_seconds": 300},
                    "tools": ["get_er_context"],
                    "skills": [],
                    "routing": {"project_code": "default"},
                    "channels": {
                        "ingress": ["connector-dingtalk-stream-default"],
                        "delivery": ["connector-dingtalk-enterprise-default"],
                    },
                },
            },
        )
        assert raw_security_field.status_code == 422
        assert "must-not-be-accepted" not in raw_security_field.text
