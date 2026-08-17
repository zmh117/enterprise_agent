from __future__ import annotations

import json

import pytest

from app.modules.mcp_audit import McpAuditContext, McpAuditCoordinator, McpAuditError
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.helpers import container, prepare_debug_application_access


def _runtime_job():
    runtime = container()
    selection = prepare_debug_application_access(
        runtime,
        application_code="mcp-audit-application",
        role_code="mcp-audit-role",
        capabilities=("get_er_context",),
    )
    job, _ = runtime.debug_job_access_service.create_job(
        user_id="user_local_admin",
        display_name="Administrator",
        message="diagnose",
        application_id=selection["application_id"],
        execution_scope_id=selection["execution_scope_id"],
        idempotency_key="mcp-audit-job",
        correlation_id="mcp-audit-test",
        environment="local",
    )
    claimed = runtime.agent_repository.claim_job(job.id, "agent-worker-test")
    assert claimed is not None
    return runtime, claimed


def _coordinator_fixture() -> tuple[object, object, McpAuditCoordinator, McpAuditContext]:
    runtime, job = _runtime_job()
    coordinator = McpAuditCoordinator(
        runtime.database,
        max_payload_bytes=4096,
        audit_service=runtime.audit_service,
    )
    context = McpAuditContext(
        correlation_id="mcp-audit-test",
        job_id=job.id,
        session_id=job.session_id,
        invocation_id=f"{job.id}.attempt-{job.retry_count}",
        actor_user_id=job.internal_user_id or job.requester_id,
        server_code="tool-mcp",
        tool_identifier="get_er_context",
        tool_schema_hash="a" * 64,
        agent_publication_id=job.agent_publication_id,
        application_publication_id=job.business_application_publication_id,
    )
    return runtime, job, coordinator, context


def test_coordinator_creates_and_completes_one_exact_fact_tree() -> None:
    runtime, job, coordinator, context = _coordinator_fixture()

    handle = coordinator.begin(context, business_request={"query": "订单"})
    authorization_id = coordinator.append_event(
        handle,
        event_kind="AUTHORIZATION",
        status="SUCCEEDED",
        authorization_decision="ALLOW",
        authorization_reason="business_scope_allowed",
        business_request={"stage": "tool_call"},
    )
    coordinator.complete(
        handle,
        status="SUCCEEDED",
        business_response={"items": [{"name": "订单"}]},
        duration_ms=12,
    )
    # A replay of the same terminal completion is idempotent.
    coordinator.complete(
        handle,
        status="SUCCEEDED",
        business_response={"items": [{"name": "订单"}]},
        duration_ms=12,
    )

    tool_rows = runtime.database.execute(
        "select * from agent_tool_call where job_id = ?",
        (job.id,),
    )
    audit_rows = runtime.database.execute(
        "select * from mcp_operation_audit where mcp_call_id = ? order by event_kind",
        (handle.mcp_call_id,),
    )
    assert len(tool_rows) == 1
    assert tool_rows[0]["id"] == handle.agent_tool_call_id
    assert tool_rows[0]["persisted_by"] == "mcp_server"
    assert tool_rows[0]["tool_origin"] == "mcp"
    assert tool_rows[0]["status"] == "SUCCEEDED"
    assert {row["event_kind"] for row in audit_rows} == {"TOOL", "AUTHORIZATION"}
    assert {row["agent_tool_call_id"] for row in audit_rows} == {handle.agent_tool_call_id}
    child = next(row for row in audit_rows if row["id"] == authorization_id)
    assert child["parent_audit_id"] == handle.root_audit_id
    assert handle.result_meta() == {
        "enterprise-agent/mcp-call-id": handle.mcp_call_id,
        "enterprise-agent/agent-tool-call-id": handle.agent_tool_call_id,
    }


def test_coordinator_rejects_auth_material_before_writing() -> None:
    runtime, job, coordinator, context = _coordinator_fixture()

    with pytest.raises(McpAuditError) as denied:
        coordinator.begin(context, business_request={"authorization": "forbidden"})

    assert denied.value.error_code == "mcp_audit_auth_material_forbidden"
    assert (
        runtime.database.execute_one(
            "select id from agent_tool_call where job_id = ?",
            (job.id,),
        )
        is None
    )

    handle = coordinator.begin(context, business_request={"query": "allowed"})
    with pytest.raises(McpAuditError) as child_denied:
        coordinator.append_event(
            handle,
            event_kind="RESOURCE",
            status="FAILED",
            business_response={"access_token": "forbidden"},
        )
    assert getattr(child_denied.value, "mcp_audit_handle") == handle

    for header_name in (
        "X-MCP-Principal-Token-Ones-Mcp",
        "X-MCP-Principal-Token-Test-Business-Mcp",
        "X-File-Principal-Token",
    ):
        with pytest.raises(McpAuditError) as header_denied:
            coordinator.begin(context, business_request={header_name: "forbidden"})
        assert header_denied.value.error_code == "mcp_audit_auth_material_forbidden"


def test_coordinator_bounds_payload_and_retention_preserves_agent_tool_fact() -> None:
    runtime, job, coordinator, context = _coordinator_fixture()
    coordinator = McpAuditCoordinator(
        runtime.database,
        max_payload_bytes=1024,
        audit_service=runtime.audit_service,
    )
    handle = coordinator.begin(context, business_request={"query": "a" * 5000})
    coordinator.complete(
        handle,
        status="FAILED",
        error_code="resource_unavailable",
        business_response={"error": "x" * 5000},
        duration_ms=1,
    )
    root = runtime.database.execute_one(
        "select * from mcp_operation_audit where id = ?",
        (handle.root_audit_id,),
    )
    assert root is not None
    assert root["request_truncated"] == 1
    assert root["response_truncated"] == 1
    assert json.loads(str(root["business_request_json"]))["truncated"] is True

    runtime.database.execute(
        "update mcp_operation_audit set created_at = '2000-01-01T00:00:00+00:00' "
        "where mcp_call_id = ?",
        (handle.mcp_call_id,),
    )
    assert coordinator.purge_expired(retention_days=1, batch_size=10) == 1
    assert (
        runtime.database.execute_one(
            "select id from agent_tool_call where id = ?",
            (handle.agent_tool_call_id,),
        )
        is not None
    )


def test_worker_upserts_sdk_started_and_terminal_by_runtime_identity() -> None:
    runtime, job, _coordinator, _context = _coordinator_fixture()
    values = {
        "job_id": job.id,
        "invocation_id": f"{job.id}.attempt-{job.retry_count}",
        "runtime_tool_call_id": "sdk-tool-use-1",
        "tool_origin": "sdk_custom",
        "server_code": None,
        "tool_name": "registered_sdk_tool",
        "request_payload": {"query": "订单"},
        "risk_level": "low",
    }

    started_id = runtime.agent_repository.upsert_runtime_tool_call(
        **values,
        response_summary={},
        status="STARTED",
        duration_ms=0,
    )
    terminal_id = runtime.agent_repository.upsert_runtime_tool_call(
        **values,
        response_summary={"count": 1},
        status="SUCCEEDED",
        duration_ms=8,
    )

    assert terminal_id == started_id
    rows = runtime.database.execute(
        "select * from agent_tool_call where job_id = ? and runtime_tool_call_id = ?",
        (job.id, "sdk-tool-use-1"),
    )
    assert len(rows) == 1
    assert rows[0]["status"] == "SUCCEEDED"
    assert rows[0]["server_code"] is None
    assert (
        runtime.database.execute_one(
            "select id from mcp_operation_audit where agent_tool_call_id = ?",
            (started_id,),
        )
        is None
    )


def test_worker_updates_only_the_exact_server_first_mcp_row() -> None:
    runtime, job, coordinator, context = _coordinator_fixture()
    first = coordinator.begin(context, business_request={"query": "first"})
    second = coordinator.begin(context, business_request={"query": "second"})
    coordinator.complete(
        first,
        status="SUCCEEDED",
        business_response={"value": 1},
        duration_ms=1,
    )
    coordinator.complete(
        second,
        status="SUCCEEDED",
        business_response={"value": 2},
        duration_ms=1,
    )

    linked = runtime.agent_repository.upsert_runtime_tool_call(
        job_id=job.id,
        invocation_id=context.invocation_id,
        runtime_tool_call_id="sdk-mcp-use-2",
        tool_origin="mcp",
        server_code="tool-mcp",
        tool_name="get_er_context",
        request_payload={"available": True},
        response_summary={"available": True},
        status="SUCCEEDED",
        duration_ms=2,
        risk_level="low",
        mcp_call_id=second.mcp_call_id,
        persisted_tool_call_id=second.agent_tool_call_id,
    )

    assert linked == second.agent_tool_call_id
    first_row = runtime.database.execute_one(
        "select runtime_tool_call_id from agent_tool_call where id = ?",
        (first.agent_tool_call_id,),
    )
    second_row = runtime.database.execute_one(
        "select runtime_tool_call_id from agent_tool_call where id = ?",
        (second.agent_tool_call_id,),
    )
    assert first_row == {"runtime_tool_call_id": None}
    assert second_row == {"runtime_tool_call_id": "sdk-mcp-use-2"}

    with pytest.raises(NonRetryableExecutionError):
        runtime.agent_repository.upsert_runtime_tool_call(
            job_id=job.id,
            invocation_id=context.invocation_id,
            runtime_tool_call_id="sdk-mcp-use-wrong",
            tool_origin="mcp",
            server_code="tool-mcp",
            tool_name="get_er_context",
            request_payload={},
            response_summary={},
            status="SUCCEEDED",
            duration_ms=0,
            risk_level="low",
            mcp_call_id=first.mcp_call_id,
            persisted_tool_call_id=second.agent_tool_call_id,
        )
