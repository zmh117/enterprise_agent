from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.bootstrap import Container, build_test_container
from app.main import create_app
from app.modules.job.application.create_agent_job_service import CreateAgentJobCommand
from app.modules.job.infrastructure.execution_audit_repository import (
    ExecutionAuditRepository,
)
from app.shared.config import IdentitySettings, Settings
from backend.tests.helpers import (
    activate_dingtalk_test_application,
    direct_job_permission_service_factory,
)


ADMIN_ID = "user_local_admin"


def _settings() -> Settings:
    return Settings(
        database_dsn="sqlite:///:memory:",
        environment="test",
        identity=IdentitySettings(
            enabled=True,
            web_admin_enabled=True,
            published_agent_runtime_enabled=True,
            test_identity_headers_enabled=True,
            cookie_secure=False,
        ),
    )


def _container() -> Container:
    return build_test_container(
        _settings(),
        migrate=True,
        seed=True,
        permission_service_factory=direct_job_permission_service_factory,
    )


def _headers(username: str) -> dict[str, str]:
    return {"x-admin-user-id": username}


def _active_application(container: Container, code: str) -> dict[str, object]:
    publication = activate_dingtalk_test_application(
        container,
        code=code,
        robot_code=f"robot-{code}",
    )
    application = container.business_application_repository.get_by_code(code)
    return {**application, "publication": publication}


def _topology(container: Container) -> dict[str, str]:
    timestamp = datetime.now(UTC).isoformat()
    container.database.execute(
        """
        insert into platform_environment
          (id, code, display_name, status, created_at, updated_at)
        values ('environment-debug-local', 'local', '本地环境', 'enabled', ?, ?)
        """,
        (timestamp, timestamp),
    )
    container.database.execute(
        """
        insert into platform_base
          (id, environment_id, code, display_name, engine, status,
           created_at, updated_at)
        values ('base-debug-one', 'environment-debug-local', 'base-one',
                '一号基地', 'postgresql', 'enabled', ?, ?)
        """,
        (timestamp, timestamp),
    )
    return {
        "environment_id": "environment-debug-local",
        "base_id": "base-debug-one",
    }


def _grant_role(
    container: Container,
    *,
    code: str,
    user_id: str,
    admin_capability: str = "",
    admin_resource_code: str = "*",
    business_application_id: str = "",
    scope: dict[str, str] | None = None,
) -> None:
    role = container.authorization_center_service.create_role(
        actor_id=ADMIN_ID,
        code=code,
        name=code,
        description="调试查询授权测试",
        purpose_tags=["业务诊断"],
    )["role"]
    if admin_capability:
        container.authorization_center_service.replace_admin_capabilities(
            actor_id=ADMIN_ID,
            role_id=str(role["id"]),
            expected_revision=1,
            bindings=[
                {
                    "capability_code": admin_capability,
                    "resource_code": admin_resource_code,
                }
            ],
            confirmed=True,
            reason="调试查询授权测试",
        )
    if business_application_id:
        container.authorization_center_service.replace_business_access(
            actor_id=ADMIN_ID,
            role_id=str(role["id"]),
            expected_revision=1,
            applications=[
                {
                    "application_id": business_application_id,
                    "tool_identifiers": [],
                    "scopes": [scope] if scope else [],
                }
            ],
            confirmed=True,
            reason="调试查询授权测试",
        )
    container.identity_repository.assign_role(
        user_id=user_id,
        role_id=str(role["id"]),
        assigned_by=ADMIN_ID,
    )


def _create_user(container: Container, username: str) -> dict[str, object]:
    return container.identity_repository.create_user(
        username=username,
        display_name=username,
    )


def _create_debug_job(
    *,
    runtime: Container,
    creator_user_id: str,
    idempotency_key: str,
) -> str:
    # Task 2.2 exercises read authorization only. The application-aware Debug
    # creation path replaces this legacy setup in task 2.3.
    job = runtime.create_agent_job_service.execute(
        CreateAgentJobCommand(
            idempotency_key=f"query-test:{idempotency_key}",
            user_message="检查受保护的调试查询",
            requester_id=ADMIN_ID,
            external_conversation_id=f"debug-query:{idempotency_key}",
            source_channel="debug_api",
            source_connector_id="connector-debug-api",
        )
    )
    job_id = job.id
    runtime.database.execute(
        """
        update agent_job
           set requester_id = ?, internal_user_id = ?
         where id = ?
        """,
        (creator_user_id, creator_user_id, job_id),
    )
    return job_id


def test_debug_options_require_login_and_explicit_application_scope() -> None:
    runtime = _container()
    application = _active_application(runtime, "debug-option-application")
    scope = _topology(runtime)
    user = _create_user(runtime, "debug-option-user")
    _grant_role(
        runtime,
        code="debug-option-role",
        user_id=str(user["id"]),
        admin_capability="agent.debug.execute",
        business_application_id=str(application["id"]),
        scope=scope,
    )

    with TestClient(create_app(_settings(), container_factory=lambda _: runtime)) as client:
        unauthenticated = client.get("/api/agent/jobs/_debug-options")
        admin_without_business_role = client.get(
            "/api/agent/jobs/_debug-options",
            headers=_headers("admin"),
        )
        allowed = client.get(
            "/api/agent/jobs/_debug-options",
            headers=_headers("debug-option-user"),
        )

    assert unauthenticated.status_code == 401
    assert admin_without_business_role.status_code == 200
    assert admin_without_business_role.json()["applications"] == []
    assert allowed.status_code == 200
    payload = allowed.json()
    assert payload["default_delivery"] == {"type": "none", "binding_id": ""}
    assert len(payload["applications"]) == 1
    option = payload["applications"][0]
    assert option["id"] == application["id"]
    assert option["publication_id"] == application["publication"]["id"]
    assert option["execution_scopes"] == [
        {
            "id": option["execution_scopes"][0]["id"],
            "scope_key": "local/base-one",
            "environment_id": "environment-debug-local",
            "environment_code": "local",
            "base_id": "base-debug-one",
            "base_code": "base-one",
            "workshop_id": "",
            "workshop_code": "",
            "source_role_codes": ["debug-option-role"],
        }
    ]
    # reply_original depends on an external ingress callback and is therefore
    # intentionally unavailable to an isolated Debug Job.
    assert option["delivery_bindings"] == []
    runtime.database.close()


@pytest.mark.parametrize(
    "suffix",
    ("", "/steps", "/tool-calls", "/deliveries", "/evidence"),
)
def test_debug_queries_hide_existing_job_from_unrelated_user(suffix: str) -> None:
    runtime = _container()
    creator = _create_user(runtime, "debug-query-creator")
    unrelated = _create_user(runtime, "debug-query-unrelated")
    _grant_role(
        runtime,
        code="debug-query-creator-role",
        user_id=str(creator["id"]),
        admin_capability="agent.debug.execute",
    )

    with TestClient(create_app(_settings(), container_factory=lambda _: runtime)) as client:
        job_id = _create_debug_job(
            runtime=runtime,
            creator_user_id=str(creator["id"]),
            idempotency_key=f"creator-{suffix}",
        )
        creator_response = client.get(
            f"/api/agent/jobs/{job_id}{suffix}",
            headers=_headers("debug-query-creator"),
        )
        existing = client.get(
            f"/api/agent/jobs/{job_id}{suffix}",
            headers=_headers("debug-query-unrelated"),
        )
        missing = client.get(
            f"/api/agent/jobs/job_missing{suffix}",
            headers=_headers("debug-query-unrelated"),
        )
        administrator = client.get(
            f"/api/agent/jobs/{job_id}{suffix}",
            headers=_headers("admin"),
        )

    assert creator_response.status_code == 200
    assert administrator.status_code == 200
    assert existing.status_code == 404
    assert missing.status_code == 404
    assert existing.json() == missing.json() == {"detail": "未找到 Agent Job"}
    assert unrelated["id"] != creator["id"]
    runtime.database.close()


def test_job_tool_call_api_projects_exact_runtime_and_mcp_identity() -> None:
    runtime = _container()
    creator = _create_user(runtime, "tool-call-projection-user")
    job_id = _create_debug_job(
        runtime=runtime,
        creator_user_id=str(creator["id"]),
        idempotency_key="tool-call-projection",
    )
    tool_call_id = runtime.agent_repository.add_tool_call(
        job_id=job_id,
        tool_name="get_er_context",
        request_payload={"query": "order"},
        response_summary={"count": 1},
        status="SUCCEEDED",
        duration_ms=4,
        risk_level="low",
        invocation_id=f"{job_id}.attempt-0",
        runtime_tool_call_id="sdk-tool-use-projection",
        tool_origin="mcp",
        server_code="tool-mcp",
        mcp_call_id="mcp-call-projection",
        persisted_by="mcp_server",
    )

    with TestClient(create_app(_settings(), container_factory=lambda _: runtime)) as client:
        response = client.get(
            f"/api/agent/jobs/{job_id}/tool-calls",
            headers=_headers("tool-call-projection-user"),
        )

    assert response.status_code == 200
    tool_calls = response.json()["tool_calls"]
    assert len(tool_calls) == 1
    projected = tool_calls[0]
    assert projected["id"] == tool_call_id
    assert projected["request_payload"] == {"query": "order"}
    assert projected["response_summary"] == {"count": 1}
    assert projected["invocation_id"] == f"{job_id}.attempt-0"
    assert projected["runtime_tool_call_id"] == "sdk-tool-use-projection"
    assert projected["tool_origin"] == "mcp"
    assert projected["server_code"] == "tool-mcp"
    assert projected["mcp_call_id"] == "mcp-call-projection"
    assert projected["persisted_by"] == "mcp_server"
    runtime.database.close()


def test_application_operator_can_read_attributed_job() -> None:
    runtime = _container()
    application = _active_application(runtime, "debug-operations-application")
    creator = _create_user(runtime, "debug-operations-creator")
    operator = _create_user(runtime, "debug-operations-user")
    _grant_role(
        runtime,
        code="debug-operations-creator-role",
        user_id=str(creator["id"]),
        admin_capability="agent.debug.execute",
    )
    _grant_role(
        runtime,
        code="debug-operations-role",
        user_id=str(operator["id"]),
        admin_capability="applications.activate",
        admin_resource_code=str(application["code"]),
    )

    with TestClient(create_app(_settings(), container_factory=lambda _: runtime)) as client:
        job_id = _create_debug_job(
            runtime=runtime,
            creator_user_id=str(creator["id"]),
            idempotency_key="operations-read",
        )
        runtime.database.execute(
            """
            update agent_job
               set business_application_id = ?,
                   business_application_code = ?
             where id = ?
            """,
            (application["id"], application["code"], job_id),
        )
        response = client.get(
            f"/api/agent/jobs/{job_id}",
            headers=_headers("debug-operations-user"),
        )

    assert response.status_code == 200
    assert response.json()["business_application_code"] == application["code"]
    runtime.database.close()


def test_job_evidence_returns_safe_paginated_model_calls_without_runtime_json() -> None:
    runtime = _container()
    creator = _create_user(runtime, "model-audit-owner")
    _create_user(runtime, "model-audit-unrelated")
    _grant_role(
        runtime,
        code="model-audit-owner-role",
        user_id=str(creator["id"]),
        admin_capability="agent.debug.execute",
    )
    job_id = _create_debug_job(
        runtime=runtime,
        creator_user_id=str(creator["id"]),
        idempotency_key="model-audit-evidence",
    )
    runtime.database.execute(
        "update agent_job set agent_runtime_protocol_version = '1.2' where id = ?",
        (job_id,),
    )
    audit = ExecutionAuditRepository(runtime.database)
    audit.record_runtime_event(
        job_id,
        {
            "protocol_version": "1.2",
            "invocation_id": f"{job_id}.attempt-0",
            "request_digest": "a" * 64,
            "sequence": 1,
            "event_type": "model_call",
            "timestamp": "2026-08-12T00:00:01Z",
            "payload": {
                "model_call_id": "message-safe-1",
                "provider_request_id": "request-safe-1",
                "provider_message_id": "message-safe-1",
                "model_id": "claude-safe-model",
                "status": "SUCCEEDED",
                "started_at": None,
                "completed_at": "2026-08-12T00:00:01Z",
                "duration_ms": None,
                "duration_source": "UNAVAILABLE",
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 2,
                    "cache_creation_input_tokens": None,
                    "cache_read_input_tokens": None,
                },
                "stop_reason": "end_turn",
                "error_code": None,
                "error_summary": None,
                "raw_sdk_message": "must-not-project",
            },
        },
    )
    audit.record_runtime_event(
        job_id,
        {
            "protocol_version": "1.2",
            "invocation_id": f"{job_id}.attempt-0",
            "request_digest": "a" * 64,
            "sequence": 2,
            "event_type": "model_call",
            "timestamp": "2026-08-12T00:00:02Z",
            "payload": {
                "model_call_id": "message-safe-2",
                "provider_request_id": "request-safe-2",
                "provider_message_id": "message-safe-2",
                "model_id": "claude-safe-model",
                "status": "SUCCEEDED",
                "started_at": None,
                "completed_at": "2026-08-12T00:00:02Z",
                "duration_ms": None,
                "duration_source": "UNAVAILABLE",
                "usage": {
                    "input_tokens": 8,
                    "output_tokens": 3,
                    "cache_creation_input_tokens": None,
                    "cache_read_input_tokens": None,
                },
                "stop_reason": "end_turn",
                "error_code": None,
                "error_summary": None,
            },
        },
    )
    audit.rebuild_summary(job_id)

    with TestClient(create_app(_settings(), container_factory=lambda _: runtime)) as client:
        evidence = client.get(
            f"/api/agent/jobs/{job_id}/evidence",
            headers=_headers("model-audit-owner"),
        )
        model_calls = client.get(
            f"/api/agent/jobs/{job_id}/model-calls?limit=1",
            headers=_headers("model-audit-owner"),
        )
        next_page = client.get(
            f"/api/agent/jobs/{job_id}/model-calls?limit=1"
            f"&cursor={model_calls.json()['next_cursor']}",
            headers=_headers("model-audit-owner"),
        )
        hidden = client.get(
            f"/api/agent/jobs/{job_id}/model-calls?limit=1",
            headers=_headers("model-audit-unrelated"),
        )

    assert evidence.status_code == model_calls.status_code == next_page.status_code == 200
    assert hidden.status_code == 404
    assert evidence.json()["execution_summary"]["accounting_status"] == "PARTIAL"
    projected = model_calls.json()["items"][0]
    assert projected["provider_request_id"] == "request-safe-1"
    assert projected["duration_source"] == "UNAVAILABLE"
    assert model_calls.json()["has_more"] is True
    assert next_page.json()["items"][0]["provider_request_id"] == "request-safe-2"
    assert next_page.json()["has_more"] is False
    serialized = str(evidence.json()) + str(model_calls.json()) + str(next_page.json())
    assert "raw_sdk_message" not in serialized
    assert "must-not-project" not in serialized
    assert "runtime_events" not in serialized
    runtime.database.close()
