from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.bootstrap import build_test_container
from app.main import create_app
from app.modules.business_application.domain.policies import (
    canonical_json,
    normalize_routing_key,
    reject_dangerous_content,
    snapshot_hash,
    validate_execution_policy,
)
from app.shared.database import Database, default_migrations_dir
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.test_unified_identity_rbac import (
    csrf_headers,
    login,
    unified_settings,
)


def control_plane_settings() -> object:
    return replace(
        unified_settings(),
        feature_business_application_control_plane=True,
    )


def draft_payload(*, route: str = "", capabilities: list[dict[str, object]] | None = None) -> dict[str, object]:
    triggers: list[dict[str, object]] = []
    deliveries: list[dict[str, object]] = []
    if route:
        triggers.append(
            {
                "trigger_type": "dingtalk_private",
                "connector_id": "connector-dingtalk-stream-default",
                "routing_key": route,
                "actor_policy": "CURRENT_SENDER",
                "service_account_user_id": "",
                "enabled": True,
                "config": {
                    "conversation_type": "private",
                    "require_mention": False,
                    "webhook_definition_id": "",
                },
            }
        )
        deliveries.append(
            {
                "delivery_type": "reply_original",
                "connector_id": "connector-dingtalk-stream-default",
                "enabled": True,
                "config": {"target_reference": "", "reply_mode": "original"},
            }
        )
    return {
        "agent_publication_id": "agent_publication_default_v1",
        "workflow_publication_id": "",
        "session_policy": {
            "conversation_mode": "channel",
            "recent_message_limit": 20,
            "retention_days": 30,
            "continuous_conversation_enabled": False,
            "attachments_enabled": False,
        },
        "execution_policy": {
            "max_turns": 12,
            "timeout_seconds": 300,
            "max_tool_calls": 30,
        },
        "triggers": triggers,
        "deliveries": deliveries,
        "capabilities": capabilities or [],
    }


def create_draft_publish(
    container: object, code: str, *, route: str = ""
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    service = container.business_application_service
    application = service.create(
        actor_id="user_local_admin",
        code=code,
        name=f"{code} name",
        description="safe",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    revision = service.save_draft(
        actor_id="user_local_admin",
        code=code,
        expected_revision=int(application["revision"]),
        payload=draft_payload(route=route),
    )
    validated = service.validate(
        actor_id="user_local_admin",
        code=code,
        revision_id=str(revision["id"]),
    )
    assert validated["validation"] == {"valid": True, "errors": []}
    publication = service.publish(
        actor_id="user_local_admin",
        code=code,
        revision_id=str(revision["id"]),
    )
    return application, revision, publication


def test_migration_is_repeatable_and_constraints_are_enforced() -> None:
    db = Database("sqlite:///:memory:")
    db.run_migrations(default_migrations_dir())
    db.run_migrations(default_migrations_dir())
    tables = {
        str(row["name"])
        for row in db.execute(
            "select name from sqlite_master where type = 'table'"
        )
    }
    assert {
        "business_application",
        "business_application_revision",
        "business_application_publication",
        "business_application_deployment",
        "business_application_active_route",
    } <= tables
    with pytest.raises(Exception):
        db.execute(
            """
            insert into business_application
              (id, code, name, project_code, status, revision,
               created_by, created_at, updated_at)
            values ('bad', 'bad', 'Bad', 'default', 'unknown', 1, 'actor', 'now', 'now')
            """
        )
    with pytest.raises(Exception):
        db.execute(
            """
            insert into business_application_revision
              (id, application_id, revision, created_by, created_at, updated_at)
            values ('orphan', 'missing', 1, 'actor', 'now', 'now')
            """
        )
    migration_names = [
        path.name for path in sorted(default_migrations_dir().glob("*.sql"))
    ]
    assert migration_names.index("009_admin_web_read_models.sql") < migration_names.index(
        "009_agent_job_retry_failure_delivery.sql"
    )
    assert migration_names.index("009_agent_job_retry_failure_delivery.sql") < migration_names.index(
        "010_business_application_control_plane.sql"
    )


def test_domain_policies_reject_unsafe_or_unknown_configuration() -> None:
    assert normalize_routing_key("  Default   Room ") == "default room"
    assert validate_execution_policy(
        {"max_turns": 2, "timeout_seconds": 30, "max_tool_calls": 4}
    )["max_turns"] == 2
    with pytest.raises(NonRetryableExecutionError):
        validate_execution_policy(
            {
                "max_turns": 2,
                "timeout_seconds": 30,
                "max_tool_calls": 4,
                "unknown": True,
            }
        )
    with pytest.raises(NonRetryableExecutionError) as unsafe:
        reject_dangerous_content({"password": "must-not-be-reflected"})
    assert "must-not-be-reflected" not in unsafe.value.safe_message
    left = {"b": 2, "a": {"z": None, "list": [2, 1]}}
    right = {"a": {"list": [2, 1], "z": None}, "b": 2}
    assert canonical_json(left) == canonical_json(right)
    assert snapshot_hash(left) == snapshot_hash(right)


def test_repository_is_append_only_and_enforces_revision_conflicts() -> None:
    container = build_test_container(control_plane_settings(), migrate=True, seed=True)
    service = container.business_application_service
    application = service.create(
        actor_id="user_local_admin",
        code="revision-test",
        name="Revision Test",
        description="",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    first = service.save_draft(
        actor_id="user_local_admin",
        code="revision-test",
        expected_revision=int(application["revision"]),
        payload=draft_payload(),
    )
    with pytest.raises(NonRetryableExecutionError) as conflict:
        service.save_draft(
            actor_id="user_local_admin",
            code="revision-test",
            expected_revision=int(application["revision"]),
            payload=draft_payload(),
        )
    assert conflict.value.error_code == "revision_conflict"
    assert len(
        container.business_application_repository.list_revisions(
            str(application["id"])
        )
    ) == 2
    assert first["revision"] == 2

    ordered_payload = draft_payload(
        capabilities=[
            {
                "capability_code": "first-capability",
                "version_constraint": "1",
                "enabled": True,
            },
            {
                "capability_code": "second-capability",
                "version_constraint": "2",
                "enabled": False,
            },
        ]
    )
    ordered_payload["triggers"] = [
        {
            "trigger_type": "dingtalk_private",
            "connector_id": "connector-dingtalk-stream-default",
            "routing_key": route,
            "actor_policy": "CURRENT_SENDER",
            "service_account_user_id": "",
            "enabled": True,
            "config": {
                "conversation_type": "private",
                "require_mention": False,
                "webhook_definition_id": "",
            },
        }
        for route in ("first-route", "second-route")
    ]
    ordered = service.save_draft(
        actor_id="user_local_admin",
        code="revision-test",
        expected_revision=int(first["revision"]),
        payload=ordered_payload,
    )
    assert [item["binding_order"] for item in ordered["triggers"]] == [0, 1]
    assert [item["routing_key"] for item in ordered["triggers"]] == [
        "first-route",
        "second-route",
    ]
    assert [item["capability_code"] for item in ordered["capabilities"]] == [
        "first-capability",
        "second-capability",
    ]


def test_publish_activate_resolve_rollback_and_deactivate_do_not_touch_data_plane() -> None:
    container = build_test_container(control_plane_settings(), migrate=True, seed=True)
    before = {
        "jobs": container.database.execute_one("select count(*) as count from agent_job")["count"],
        "sessions": container.database.execute_one(
            "select count(*) as count from agent_session"
        )["count"],
    }
    application, first_revision, first_publication = create_draft_publish(
        container, "lifecycle-test", route="room-a"
    )
    repeated_publication = container.business_application_service.publish(
        actor_id="user_local_admin",
        code="lifecycle-test",
        revision_id=str(first_revision["id"]),
    )
    assert repeated_publication["id"] == first_publication["id"]
    assert len(
        container.business_application_repository.list_publications(
            str(application["id"])
        )
    ) == 1
    first = container.business_application_service.activate(
        actor_id="user_local_admin",
        code="lifecycle-test",
        environment="test",
        publication_id=str(first_publication["id"]),
        expected_revision=0,
    )
    resolved = container.business_application_resolver.resolve_trigger(
        "test",
        "dingtalk_private",
        "connector-dingtalk-stream-default",
        " ROOM-A ",
    )
    assert first["runtime_wired"] is False
    assert resolved["publication"]["id"] == first_publication["id"]

    latest = container.business_application_repository.get_by_code("lifecycle-test")
    second_revision = container.business_application_service.save_draft(
        actor_id="user_local_admin",
        code="lifecycle-test",
        expected_revision=int(latest["revision"]),
        payload=draft_payload(route="room-a"),
    )
    second_publication = container.business_application_service.publish(
        actor_id="user_local_admin",
        code="lifecycle-test",
        revision_id=str(second_revision["id"]),
    )
    second = container.business_application_service.activate(
        actor_id="user_local_admin",
        code="lifecycle-test",
        environment="test",
        publication_id=str(second_publication["id"]),
        expected_revision=int(first["revision"]),
    )
    rolled_back = container.business_application_service.activate(
        actor_id="user_local_admin",
        code="lifecycle-test",
        environment="test",
        publication_id=str(first_publication["id"]),
        expected_revision=int(second["revision"]),
    )
    stopped = container.business_application_service.deactivate(
        actor_id="user_local_admin",
        code="lifecycle-test",
        environment="test",
        expected_revision=int(rolled_back["revision"]),
    )
    assert stopped["active"] is False
    with pytest.raises(NonRetryableExecutionError) as missing:
        container.business_application_resolver.resolve_active("lifecycle-test", "test")
    assert missing.value.error_code == "business_application_configuration_error"
    assert before == {
        "jobs": container.database.execute_one("select count(*) as count from agent_job")["count"],
        "sessions": container.database.execute_one(
            "select count(*) as count from agent_session"
        )["count"],
    }
    assert application["runtime_wired"] is False


def test_only_published_session_policy_is_visible_to_runtime_resolver() -> None:
    container = build_test_container(control_plane_settings(), migrate=True, seed=True)
    service = container.business_application_service
    application = service.create(
        actor_id="user_local_admin",
        code="session-policy-test",
        name="Session Policy Test",
        description="",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    first_payload = draft_payload(route="session-room")
    first_payload["session_policy"] = {
        "conversation_mode": "channel",
        "recent_message_limit": 20,
        "retention_days": 30,
        "continuous_conversation_enabled": True,
        "attachments_enabled": True,
    }
    first_revision = service.save_draft(
        actor_id="user_local_admin",
        code="session-policy-test",
        expected_revision=int(application["revision"]),
        payload=first_payload,
    )
    first_publication = service.publish(
        actor_id="user_local_admin",
        code="session-policy-test",
        revision_id=str(first_revision["id"]),
    )
    service.activate(
        actor_id="user_local_admin",
        code="session-policy-test",
        environment="test",
        publication_id=str(first_publication["id"]),
        expected_revision=0,
    )

    current = container.business_application_resolver.resolve_trigger(
        "test",
        "dingtalk_private",
        "connector-dingtalk-stream-default",
        "session-room",
    )
    policy = current["publication"]["snapshot"]["session_policy"]
    assert policy["continuous_conversation_enabled"] is True
    assert policy["attachments_enabled"] is True

    latest = container.business_application_repository.get_by_code(
        "session-policy-test"
    )
    service.save_draft(
        actor_id="user_local_admin",
        code="session-policy-test",
        expected_revision=int(latest["revision"]),
        payload=draft_payload(route="session-room"),
    )
    unchanged = container.business_application_resolver.resolve_trigger(
        "test",
        "dingtalk_private",
        "connector-dingtalk-stream-default",
        "session-room",
    )
    assert unchanged["publication"]["id"] == first_publication["id"]
    assert unchanged["publication"]["snapshot"]["session_policy"][
        "continuous_conversation_enabled"
    ] is True


def test_active_business_application_policy_controls_live_channel_sessions() -> None:
    container = build_test_container(control_plane_settings(), migrate=True, seed=True)
    service = container.business_application_service
    application = service.create(
        actor_id="user_local_admin",
        code="live-session-policy",
        name="Live Session Policy",
        description="",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    payload = draft_payload(route="conversation-policy-runtime")
    payload["session_policy"] = {
        "conversation_mode": "channel",
        "recent_message_limit": 20,
        "retention_days": 30,
        "continuous_conversation_enabled": True,
        "attachments_enabled": False,
    }
    revision = service.save_draft(
        actor_id="user_local_admin",
        code="live-session-policy",
        expected_revision=int(application["revision"]),
        payload=payload,
    )
    publication = service.publish(
        actor_id="user_local_admin",
        code="live-session-policy",
        revision_id=str(revision["id"]),
    )
    service.activate(
        actor_id="user_local_admin",
        code="live-session-policy",
        environment="test",
        publication_id=str(publication["id"]),
        expected_revision=0,
    )

    first = container.dingtalk_stream_message_service.handle_callback(
        payload={
            "conversationId": "conversation-policy-runtime",
            "senderStaffId": "local-user",
            "msgId": "policy-message-1",
            "text": {"content": "first"},
        },
        correlation_id="policy-correlation-1",
    )
    second = container.dingtalk_stream_message_service.handle_callback(
        payload={
            "conversationId": "conversation-policy-runtime",
            "senderStaffId": "local-user",
            "msgId": "policy-message-2",
            "text": {"content": "second"},
        },
        correlation_id="policy-correlation-2",
    )

    assert first.accepted is True
    assert second.accepted is True
    first_job = container.agent_repository.get_job(first.job_id)
    second_job = container.agent_repository.get_job(second.job_id)
    assert first_job.session_id == second_job.session_id
    assert first_job.agent_publication_id == "agent_publication_default_v1"


def test_resolver_fails_closed_for_lifecycle_schema_and_hash_errors() -> None:
    container = build_test_container(control_plane_settings(), migrate=True, seed=True)
    application, _revision, publication = create_draft_publish(
        container, "resolver-integrity-test"
    )
    deployment = container.business_application_service.activate(
        actor_id="user_local_admin",
        code="resolver-integrity-test",
        environment="test",
        publication_id=str(publication["id"]),
        expected_revision=0,
    )
    assert deployment["active"] is True

    container.database.execute(
        """
        update business_application_publication
           set schema_version = 99
         where id = ?
        """,
        (publication["id"],),
    )
    with pytest.raises(NonRetryableExecutionError) as schema_error:
        container.business_application_resolver.resolve_active(
            "resolver-integrity-test", "test"
        )
    assert schema_error.value.error_code == "business_application_configuration_error"

    container.database.execute(
        """
        update business_application_publication
           set schema_version = 1, config_hash = 'tampered'
         where id = ?
        """,
        (publication["id"],),
    )
    with pytest.raises(NonRetryableExecutionError) as hash_error:
        container.business_application_resolver.resolve_active(
            "resolver-integrity-test", "test"
        )
    assert hash_error.value.error_code == "business_application_configuration_error"

    container.database.execute(
        "update business_application set status = 'disabled' where id = ?",
        (application["id"],),
    )
    with pytest.raises(NonRetryableExecutionError) as lifecycle_error:
        container.business_application_resolver.resolve_active(
            "resolver-integrity-test", "test"
        )
    assert lifecycle_error.value.error_code == "business_application_configuration_error"


def test_activation_route_projection_rejects_conflicting_application() -> None:
    container = build_test_container(control_plane_settings(), migrate=True, seed=True)
    _, _, first_publication = create_draft_publish(
        container, "route-owner-a", route="same-room"
    )
    _, _, second_publication = create_draft_publish(
        container, "route-owner-b", route="same-room"
    )
    container.business_application_service.activate(
        actor_id="user_local_admin",
        code="route-owner-a",
        environment="test",
        publication_id=str(first_publication["id"]),
        expected_revision=0,
    )
    with pytest.raises(NonRetryableExecutionError) as conflict:
        container.business_application_service.activate(
            actor_id="user_local_admin",
            code="route-owner-b",
            environment="test",
            publication_id=str(second_publication["id"]),
            expected_revision=0,
        )
    assert conflict.value.error_code == "route_conflict"
    assert (
        container.business_application_repository.get_deployment(
            str(second_publication["application_id"]), "test"
        )
        is None
    )


def test_capability_can_be_drafted_but_blocks_validation_and_publication() -> None:
    container = build_test_container(control_plane_settings(), migrate=True, seed=True)
    service = container.business_application_service
    application = service.create(
        actor_id="user_local_admin",
        code="capability-test",
        name="Capability Test",
        description="",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    revision = service.save_draft(
        actor_id="user_local_admin",
        code="capability-test",
        expected_revision=int(application["revision"]),
        payload=draft_payload(
            capabilities=[
                {
                    "capability_code": "order-query-detail",
                    "version_constraint": "1.x",
                    "enabled": True,
                }
            ]
        ),
    )
    validated = service.validate(
        actor_id="user_local_admin",
        code="capability-test",
        revision_id=str(revision["id"]),
    )
    assert validated["validation"]["valid"] is False
    assert "Capability" in str(validated["validation"]["errors"])
    with pytest.raises(NonRetryableExecutionError) as invalid:
        service.publish(
            actor_id="user_local_admin",
            code="capability-test",
            revision_id=str(revision["id"]),
        )
    assert invalid.value.error_code == "validation_failed"


def test_admin_api_enforces_feature_auth_csrf_unknown_fields_and_conflict() -> None:
    enabled = control_plane_settings()
    container = build_test_container(enabled, migrate=True, seed=True)
    app = create_app(enabled, container_factory=lambda _: container)
    with TestClient(app) as client:
        assert client.get("/api/admin/business-applications").status_code == 401
        csrf = login(client)
        no_csrf = client.post(
            "/api/admin/business-applications",
            json={
                "code": "api-test",
                "name": "API Test",
                "project_code": "default",
            },
        )
        unknown = client.post(
            "/api/admin/business-applications",
            headers=csrf_headers(csrf),
            json={
                "code": "api-test",
                "name": "API Test",
                "project_code": "default",
                "database_url": "not-accepted",
            },
        )
        created = client.post(
            "/api/admin/business-applications",
            headers=csrf_headers(csrf),
            json={
                "code": "api-test",
                "name": "API Test",
                "project_code": "default",
            },
        )
        update_payload = {
            "expected_revision": 1,
            "name": "Updated",
            "description": "",
            "project_code": "default",
            "owner_user_id": "",
            "status": "enabled",
        }
        updated = client.put(
            "/api/admin/business-applications/api-test",
            headers=csrf_headers(csrf),
            json=update_payload,
        )
        stale = client.put(
            "/api/admin/business-applications/api-test",
            headers=csrf_headers(csrf),
            json=update_payload,
        )
        listed = client.get("/api/admin/business-applications")
    assert no_csrf.status_code == 403
    assert unknown.status_code == 422
    assert created.status_code == 200, created.text
    assert updated.status_code == 200
    assert stale.status_code == 409
    assert stale.json()["detail"]["current_revision"] == 2
    assert listed.status_code == 200
    assert listed.json()["items"][0]["code"] == "api-test"
    assert "password" not in str(listed.json()).lower()

    disabled = replace(enabled, feature_business_application_control_plane=False)
    disabled_container = build_test_container(disabled, migrate=True, seed=True)
    disabled_app = create_app(disabled, container_factory=lambda _: disabled_container)
    with TestClient(disabled_app) as client:
        login(client)
        response = client.get("/api/admin/business-applications")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "business_application_control_plane_disabled"


def test_admin_api_prevents_enumeration_and_denies_unprivileged_writes() -> None:
    settings = control_plane_settings()
    container = build_test_container(settings, migrate=True, seed=True)
    container.business_application_service.create(
        actor_id="user_local_admin",
        code="private-application",
        name="Private Application",
        description="",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    container.identity_admin_service.create_user(
        actor_id="user_local_admin",
        username="business-app-restricted",
        display_name="Business App Restricted",
        email="",
        password="restricted-local-test-password",
    )
    app = create_app(settings, container_factory=lambda _: container)
    with TestClient(app) as client:
        csrf = login(
            client,
            username="business-app-restricted",
            password="restricted-local-test-password",
        )
        listed = client.get("/api/admin/business-applications")
        hidden = client.get(
            "/api/admin/business-applications/private-application"
        )
        forbidden = client.post(
            "/api/admin/business-applications",
            headers=csrf_headers(csrf),
            json={
                "code": "forbidden-create",
                "name": "Forbidden Create",
                "project_code": "default",
            },
        )
    assert listed.status_code == 200
    assert listed.json()["items"] == []
    assert hidden.status_code == 404
    assert forbidden.status_code == 403
    assert "private-application" not in str(hidden.json())


def test_seed_cli_exists_and_production_migration_does_not_activate() -> None:
    assert Path("backend/app/cli/seed_default_business_application.py").exists()
    db = Database("sqlite:///:memory:")
    db.run_migrations(default_migrations_dir())
    assert db.execute_one(
        "select count(*) as count from business_application_deployment"
    )["count"] == 0


def test_local_seed_and_default_application_cli_are_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.cli.seed_default_business_application import main

    database_path = tmp_path / "control-plane-seed.db"
    monkeypatch.setenv("DATABASE_DSN", f"sqlite:///{database_path}")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("FEATURE_UNIFIED_IDENTITY", "true")
    monkeypatch.setenv("FEATURE_WEB_ADMIN", "true")
    monkeypatch.setenv("FEATURE_BUSINESS_APPLICATION_CONTROL_PLANE", "true")
    assert main() == 0
    assert main() == 0
    db = Database(f"sqlite:///{database_path}")
    assert db.execute_one(
        """
        select count(*) as count from business_application
         where code = 'default-diagnostic-application'
        """
    )["count"] == 1
    assert db.execute_one(
        "select count(*) as count from business_application_deployment"
    )["count"] == 0
