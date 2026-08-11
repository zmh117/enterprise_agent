from __future__ import annotations

import base64
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
from app.shared.migrations import Migrator
from backend.tests.helpers import (
    ensure_active_dingtalk_test_enterprise,
    grant_test_application_access,
)
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


def draft_payload(
    *, route: str = "", mcp_tools: list[str] | None = None
) -> dict[str, object]:
    triggers: list[dict[str, object]] = []
    deliveries: list[dict[str, object]] = []
    if route:
        route = route if ":" in route else f"bot:{route}"
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
        "mcp_tools": mcp_tools or [],
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
        for row in db.execute("select name from sqlite_master where type = 'table'")
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
    migration_names = [path.name for path in sorted(default_migrations_dir().glob("*.sql"))]
    assert migration_names.index("009_admin_web_read_models.sql") < migration_names.index(
        "009a_agent_job_retry_failure_delivery.sql"
    )
    assert migration_names.index(
        "009a_agent_job_retry_failure_delivery.sql"
    ) < migration_names.index("010_business_application_control_plane.sql")
    session_columns = {str(row["name"]) for row in db.execute("pragma table_info(agent_session)")}
    assert {
        "application_publication_id",
        "execution_scope_hash",
        "isolation_key_version",
        "history_read_only",
    } <= session_columns


def test_domain_policies_reject_unsafe_or_unknown_configuration() -> None:
    assert normalize_routing_key("  Default   Room ") == "default room"
    assert (
        validate_execution_policy({"max_turns": 2, "timeout_seconds": 30, "max_tool_calls": 4})[
            "max_turns"
        ]
        == 2
    )
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


@pytest.mark.parametrize("legacy_mode", ["actor", "application"])
def test_new_drafts_reject_legacy_shared_session_modes(legacy_mode: str) -> None:
    container = build_test_container(control_plane_settings(), migrate=True, seed=True)
    application = container.business_application_service.create(
        actor_id="user_local_admin",
        code=f"reject-{legacy_mode}-session",
        name=f"reject {legacy_mode} session",
        description="legacy mode must stay history-only",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    payload = draft_payload()
    session_policy = dict(payload["session_policy"])
    session_policy["conversation_mode"] = legacy_mode
    payload["session_policy"] = session_policy

    with pytest.raises(NonRetryableExecutionError) as rejected:
        container.business_application_service.save_draft(
            actor_id="user_local_admin",
            code=str(application["code"]),
            expected_revision=int(application["revision"]),
            payload=payload,
        )
    assert rejected.value.error_code == "validation_failed"
    assert rejected.value.field_errors == [
        {
            "field": "session_policy.conversation_mode",
            "message": "仅支持按渠道会话；旧按主体/按应用模式只可查看历史",
        }
    ]


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
    assert (
        len(container.business_application_repository.list_revisions(str(application["id"]))) == 2
    )
    assert first["revision"] == 2

    ordered_payload = draft_payload(
        mcp_tools=["get_business_flow_context", "get_er_context"]
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
    assert [item["tool_identifier"] for item in ordered["mcp_tools"]] == [
        "get_business_flow_context",
        "get_er_context",
    ]


def test_publish_activate_resolve_rollback_and_deactivate_do_not_touch_data_plane() -> None:
    container = build_test_container(control_plane_settings(), migrate=True, seed=True)
    before = {
        "jobs": container.database.execute_one("select count(*) as count from agent_job")["count"],
        "sessions": container.database.execute_one("select count(*) as count from agent_session")[
            "count"
        ],
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
    assert (
        len(container.business_application_repository.list_publications(str(application["id"])))
        == 1
    )
    first = container.business_application_service.activate(
        actor_id="user_local_admin",
        code="lifecycle-test",
        environment="local",
        publication_id=str(first_publication["id"]),
        expected_revision=0,
    )
    resolved = container.business_application_resolver.resolve_trigger(
        "local",
        "dingtalk_private",
        "connector-dingtalk-stream-default",
        " BOT:ROOM-A ",
    )
    assert first["runtime_wired"] is True
    assert first["runtime_status"] == "wired"
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
        environment="local",
        publication_id=str(second_publication["id"]),
        expected_revision=int(first["revision"]),
    )
    rolled_back = container.business_application_service.activate(
        actor_id="user_local_admin",
        code="lifecycle-test",
        environment="local",
        publication_id=str(first_publication["id"]),
        expected_revision=int(second["revision"]),
    )
    stopped = container.business_application_service.deactivate(
        actor_id="user_local_admin",
        code="lifecycle-test",
        environment="local",
        expected_revision=int(rolled_back["revision"]),
    )
    assert stopped["active"] is False
    with pytest.raises(NonRetryableExecutionError) as missing:
        container.business_application_resolver.resolve_active("lifecycle-test", "local")
    assert missing.value.error_code == "business_application_configuration_error"
    assert before == {
        "jobs": container.database.execute_one("select count(*) as count from agent_job")["count"],
        "sessions": container.database.execute_one("select count(*) as count from agent_session")[
            "count"
        ],
    }
    assert application["runtime_wired"] is False


def test_local_only_migration_removes_nonlocal_runtime_pointers_but_preserves_history() -> None:
    container = build_test_container(control_plane_settings(), migrate=True, seed=True)
    application, _revision, publication = create_draft_publish(
        container,
        "local-only-cleanup",
        route="cleanup-bot",
    )
    local_deployment = container.business_application_service.activate(
        actor_id="user_local_admin",
        code="local-only-cleanup",
        environment="local",
        publication_id=str(publication["id"]),
        expected_revision=0,
    )
    container.database.execute(
        """
        insert into business_application_deployment (
          id, application_id, environment, publication_id, active, revision,
          activated_by, activated_at, deactivated_by, deactivated_at, updated_at
        ) values (?, ?, 'test', ?, 1, 1, 'legacy-admin', ?, '', null, ?)
        """,
        (
            "deployment-nonlocal-test",
            application["id"],
            publication["id"],
            "2026-07-24T00:00:00+00:00",
            "2026-07-24T00:00:00+00:00",
        ),
    )
    container.database.execute(
        """
        insert into business_application_active_route (
          id, deployment_id, application_id, publication_id, environment,
          trigger_type, connector_id, normalized_routing_key, created_at
        ) values (?, ?, ?, ?, 'test', 'dingtalk_private', ?, ?, ?)
        """,
        (
            "route-nonlocal-test",
            "deployment-nonlocal-test",
            application["id"],
            publication["id"],
            "connector-dingtalk-stream-default",
            "bot:cleanup-bot",
            "2026-07-24T00:00:00+00:00",
        ),
    )

    container.database.execute_script(
        (default_migrations_dir() / "012_business_application_local_only.sql").read_text()
    )

    deployments = container.database.execute(
        """
        select id, environment
          from business_application_deployment
         where application_id = ?
         order by environment
        """,
        (application["id"],),
    )
    routes = container.database.execute(
        """
        select deployment_id, environment
          from business_application_active_route
         where application_id = ?
         order by environment
        """,
        (application["id"],),
    )
    assert deployments == [{"id": local_deployment["id"], "environment": "local"}]
    assert routes == [{"deployment_id": local_deployment["id"], "environment": "local"}]
    assert (
        container.database.execute_one(
            "select count(*) as count from business_application_publication where id = ?",
            (publication["id"],),
        )["count"]
        == 1
    )


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
        environment="local",
        publication_id=str(first_publication["id"]),
        expected_revision=0,
    )

    current = container.business_application_resolver.resolve_trigger(
        "local",
        "dingtalk_private",
        "connector-dingtalk-stream-default",
        "bot:session-room",
    )
    policy = current["publication"]["snapshot"]["session_policy"]
    assert policy["continuous_conversation_enabled"] is True
    assert policy["attachments_enabled"] is True

    latest = container.business_application_repository.get_by_code("session-policy-test")
    service.save_draft(
        actor_id="user_local_admin",
        code="session-policy-test",
        expected_revision=int(latest["revision"]),
        payload=draft_payload(route="session-room"),
    )
    unchanged = container.business_application_resolver.resolve_trigger(
        "local",
        "dingtalk_private",
        "connector-dingtalk-stream-default",
        "bot:session-room",
    )
    assert unchanged["publication"]["id"] == first_publication["id"]
    assert (
        unchanged["publication"]["snapshot"]["session_policy"]["continuous_conversation_enabled"]
        is True
    )


def test_active_business_application_policy_controls_live_channel_sessions() -> None:
    container = build_test_container(control_plane_settings(), migrate=True, seed=True)
    ensure_active_dingtalk_test_enterprise(container)
    service = container.business_application_service
    application = service.create(
        actor_id="user_local_admin",
        code="live-session-policy",
        name="Live Session Policy",
        description="",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    payload = draft_payload(route="bot:test-robot-code")
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
        environment="local",
        publication_id=str(publication["id"]),
        expected_revision=0,
    )
    grant_test_application_access(
        container,
        application_id=str(application["id"]),
        role_code="live-session-runtime-reader",
    )

    first = container.dingtalk_stream_message_service.handle_callback(
        payload={
            "conversationId": "conversation-policy-runtime",
            "senderStaffId": "local-user",
            "senderCorpId": "corp-test-enterprise",
            "chatbotCorpId": "corp-test-enterprise",
            "msgId": "policy-message-1",
            "robotCode": "test-robot-code",
            "sessionWebhook": "https://oapi.dingtalk.com/robot/sendBySession",
            "text": {"content": "first"},
        },
        correlation_id="policy-correlation-1",
    )
    second = container.dingtalk_stream_message_service.handle_callback(
        payload={
            "conversationId": "conversation-policy-runtime",
            "senderStaffId": "local-user",
            "senderCorpId": "corp-test-enterprise",
            "chatbotCorpId": "corp-test-enterprise",
            "msgId": "policy-message-2",
            "robotCode": "test-robot-code",
            "sessionWebhook": "https://oapi.dingtalk.com/robot/sendBySession",
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
    application, _revision, publication = create_draft_publish(container, "resolver-integrity-test")
    deployment = container.business_application_service.activate(
        actor_id="user_local_admin",
        code="resolver-integrity-test",
        environment="local",
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
        container.business_application_resolver.resolve_active("resolver-integrity-test", "local")
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
        container.business_application_resolver.resolve_active("resolver-integrity-test", "local")
    assert hash_error.value.error_code == "business_application_configuration_error"

    container.database.execute(
        "update business_application set status = 'disabled' where id = ?",
        (application["id"],),
    )
    with pytest.raises(NonRetryableExecutionError) as lifecycle_error:
        container.business_application_resolver.resolve_active("resolver-integrity-test", "local")
    assert lifecycle_error.value.error_code == "business_application_configuration_error"


def test_activation_route_projection_rejects_conflicting_application() -> None:
    container = build_test_container(control_plane_settings(), migrate=True, seed=True)
    _, _, first_publication = create_draft_publish(container, "route-owner-a", route="same-room")
    _, _, second_publication = create_draft_publish(container, "route-owner-b", route="same-room")
    container.business_application_service.activate(
        actor_id="user_local_admin",
        code="route-owner-a",
        environment="local",
        publication_id=str(first_publication["id"]),
        expected_revision=0,
    )
    with pytest.raises(NonRetryableExecutionError) as conflict:
        container.business_application_service.activate(
            actor_id="user_local_admin",
            code="route-owner-b",
            environment="local",
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


def test_mcp_tool_catalog_lists_manifest_tools_and_enforces_agent_binding() -> None:
    container = build_test_container(control_plane_settings(), migrate=True, seed=True)
    service = container.business_application_service
    application = service.create(
        actor_id="user_local_admin",
        code="mcp-tool-catalog-test",
        name="MCP Tool Catalog Test",
        description="",
        project_code="default",
        owner_user_id="user_local_admin",
    )

    catalog = service.catalog(
        actor_id="user_local_admin",
        code="mcp-tool-catalog-test",
    )
    catalog_agents = {(item["code"], item["runtime_kind"]) for item in catalog["agents"]}
    assert ("default-diagnostic-agent", "python-v1") in catalog_agents
    assert ("typescript-diagnostic-agent", "typescript-v1") in catalog_agents
    python_tools = {
        item["tool_identifier"]
        for item in catalog["mcp_tools_by_agent_publication"][
            "agent_publication_default_v1"
        ]
    }
    assert {"get_schema_directory", "query_database"} <= python_tools

    valid_revision = service.save_draft(
        actor_id="user_local_admin",
        code="mcp-tool-catalog-test",
        expected_revision=int(application["revision"]),
        payload=draft_payload(mcp_tools=["get_schema_directory"]),
    )
    validated = service.validate(
        actor_id="user_local_admin",
        code="mcp-tool-catalog-test",
        revision_id=str(valid_revision["id"]),
    )
    assert validated["validation"] == {"valid": True, "errors": []}

    with pytest.raises(NonRetryableExecutionError) as invalid:
        service.save_draft(
            actor_id="user_local_admin",
            code="mcp-tool-catalog-test",
            expected_revision=int(valid_revision["revision"]),
            payload=draft_payload(mcp_tools=["unbound_readonly"]),
        )
    assert invalid.value.field_errors == [
        {
            "field": "mcp_tools.0",
            "message": "所选 MCP Tool 不在 Agent 发布范围内或 Schema 已变化",
        }
    ]


def test_catalog_http_contract_only_exposes_runtime_kind_for_agents() -> None:
    settings = control_plane_settings()
    container = build_test_container(settings, migrate=True, seed=True)
    container.business_application_service.create(
        actor_id="user_local_admin",
        code="catalog-runtime-contract",
        name="Catalog Runtime Contract",
        description="",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    app = create_app(settings, container_factory=lambda _: container)

    with TestClient(app) as client:
        login(client)
        response = client.get("/api/admin/business-applications/catalog-runtime-contract/catalog")

    assert response.status_code == 200
    catalog = response.json()
    assert {item["runtime_kind"] for item in catalog["agents"]} == {
        "python-v1",
        "typescript-v1",
    }
    assert catalog["connectors"]
    assert catalog["mcp_tools_by_agent_publication"]
    assert all("runtime_kind" not in item for item in catalog["connectors"])
    assert all(
        "runtime_kind" not in item
        for tools in catalog["mcp_tools_by_agent_publication"].values()
        for item in tools
    )


def test_application_agent_reference_fails_closed_on_runtime_or_hash_tampering() -> None:
    container = build_test_container(control_plane_settings(), migrate=True, seed=True)
    service = container.business_application_service
    application = service.create(
        actor_id="user_local_admin",
        code="agent-runtime-integrity-test",
        name="Agent Runtime Integrity Test",
        description="",
        project_code="default",
        owner_user_id="user_local_admin",
    )
    catalog = service.catalog(
        actor_id="user_local_admin",
        code="agent-runtime-integrity-test",
    )
    typescript = next(item for item in catalog["agents"] if item["runtime_kind"] == "typescript-v1")
    payload = draft_payload()
    payload["agent_publication_id"] = typescript["id"]
    revision = service.save_draft(
        actor_id="user_local_admin",
        code="agent-runtime-integrity-test",
        expected_revision=int(application["revision"]),
        payload=payload,
    )

    container.database.execute(
        "update agent_publication set config_hash = 'tampered' where id = ?",
        (typescript["id"],),
    )
    validated = service.validate(
        actor_id="user_local_admin",
        code="agent-runtime-integrity-test",
        revision_id=str(revision["id"]),
    )

    assert validated["validation"]["valid"] is False
    assert validated["validation"]["errors"] == [
        {"field": "agent_publication_id", "message": "组件不可用"}
    ]


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
        hidden = client.get("/api/admin/business-applications/private-application")
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
    assert (
        db.execute_one("select count(*) as count from business_application_deployment")["count"]
        == 0
    )


def test_local_seed_and_default_application_cli_are_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.cli.seed_default_business_application import main

    database_path = tmp_path / "control-plane-seed.db"
    master_key_path = tmp_path / "app-config-master-key"
    encoded_key = base64.urlsafe_b64encode(b"x" * 32).decode().rstrip("=")
    master_key_path.write_text(
        f"EA_MASTER_KEY_V1:{encoded_key}\n",
        encoding="utf-8",
    )
    master_key_path.chmod(0o400)
    monkeypatch.setenv("DATABASE_DSN", f"sqlite:///{database_path}")
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("APP_CONFIG_MASTER_KEY_FILE", str(master_key_path))
    monkeypatch.setenv("FEATURE_UNIFIED_IDENTITY", "true")
    monkeypatch.setenv("FEATURE_WEB_ADMIN", "true")
    monkeypatch.setenv("FEATURE_BUSINESS_APPLICATION_CONTROL_PLANE", "true")
    migration_database = Database(f"sqlite:///{database_path}")
    try:
        Migrator(
            migration_database,
            default_migrations_dir(),
            migrator_build="test-cli",
        ).run()
    finally:
        migration_database.close()
    assert main() == 0
    assert main() == 0
    db = Database(f"sqlite:///{database_path}")
    try:
        assert (
            db.execute_one(
                """
            select count(*) as count from business_application
             where code = 'default-diagnostic-application'
            """
            )["count"]
            == 1
        )
        assert (
            db.execute_one("select count(*) as count from business_application_deployment")["count"]
            == 0
        )
    finally:
        db.close()
