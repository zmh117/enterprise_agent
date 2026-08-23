from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from app.bootstrap import Container
from app.modules.agent.infrastructure.mcp_tool_registry import ToolRegistry
from app.modules.job.infrastructure.repositories import now_iso
from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST
from app.modules.mcp_audit import McpAuditCoordinator
from app.modules.platform_config.application.governed_resources import (
    ResourceVerificationOutcome,
)
from app.shared.exceptions import ToolPolicyError
from app.services.tool_mcp import (
    JobToolService,
    ToolMcpError,
    ToolRequestIdentity,
    create_app,
)
from backend.tests.helpers import container, prepare_debug_application_access


TOOL_NAME = "get_schema_directory"
TOOL_ARGUMENTS = {
    "environment": "local",
    "base": "debug-base",
    "query": "order",
    "limit": 10,
}


class _PassingMysqlVerifier:
    def verify(self, **_: object) -> ResourceVerificationOutcome:
        return ResourceVerificationOutcome(
            status="PASSED",
            provider_contract_version="mysql_v1",
            checks={"connection": "passed", "readonly": True},
        )


def _publish_database_resource(runtime: Container) -> None:
    platform_config_service = runtime.platform_config_service
    platform_config_service.create_platform_secret(
        {
            "code": "tool_mcp_test_password",
            "value": "test-only-password",
        },
        actor_id="user_local_admin",
    )
    resource_service = platform_config_service.governed_resources
    resource_service.create_resource(
        {
            "code": "tool_mcp_test_database",
            "name": "Tool MCP Test Database",
            "resource_kind": "database",
            "scope_type": "base",
            "environment_code": "local",
            "base_code": "debug-base",
            "provider_type": "mysql",
            "config": {
                "host": "mysql.test.internal",
                "port": 3306,
                "database": "diagnostics",
                "username": "readonly",
            },
            "secret_refs": {
                "password_ref": "secret://platform/tool_mcp_test_password",
            },
        },
        actor_id="user_local_admin",
    )
    resource_service.verify_draft(
        "tool_mcp_test_database",
        actor_id="user_local_admin",
        verifier=_PassingMysqlVerifier(),
    )
    resource_service.publish_draft(
        "tool_mcp_test_database",
        actor_id="user_local_admin",
    )


def _runtime_job(*, capabilities: tuple[str, ...] = (TOOL_NAME,)):
    runtime = container()
    if "ones_work_item_search" in capabilities:
        definition = MCP_TOOL_MANIFEST["ones_work_item_search"]
        next_order = runtime.database.execute_one(
            "select coalesce(max(selection_order), -1) + 1 as value "
            "from agent_publication_mcp_tool where agent_publication_id = ?",
            ("agent_publication_default_v1",),
        )
        assert next_order is not None
        runtime.database.execute(
            """
            insert into agent_publication_mcp_tool
              (agent_publication_id, server_code, tool_identifier, schema_hash,
               model_description, selection_order, created_at)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "agent_publication_default_v1",
                definition.server_code,
                definition.identifier,
                definition.schema_hash,
                definition.description,
                int(next_order["value"]),
                now_iso(),
            ),
        )
    selection = prepare_debug_application_access(
        runtime,
        application_code="tool-mcp-application",
        role_code="tool-mcp-role",
        capabilities=capabilities,
    )
    if TOOL_NAME in capabilities:
        _publish_database_resource(runtime)
    job, _ = runtime.debug_job_access_service.create_job(
        user_id="user_local_admin",
        display_name="Administrator",
        message="diagnose",
        application_id=selection["application_id"],
        execution_scope_id=selection["execution_scope_id"],
        idempotency_key="tool-mcp-job",
        correlation_id="tool-mcp-test",
        environment="local",
    )
    claimed = runtime.agent_repository.claim_job(job.id, "agent-worker-test")
    assert claimed is not None
    service = JobToolService(
        repository=runtime.agent_repository,
        tool_registry=ToolRegistry(runtime.tool_service),
        snapshot_service=runtime.mcp_tool_snapshot_service,
        audit_coordinator=McpAuditCoordinator(
            runtime.database,
            max_payload_bytes=512 * 1024,
            audit_service=runtime.audit_service,
        ),
    )
    return runtime, claimed, service


def _request_identity(job, correlation_id: str) -> ToolRequestIdentity:
    return ToolRequestIdentity(
        invocation_id=f"{job.id}.attempt-{job.retry_count}",
        app_user_id=job.internal_user_id,
        project_code=job.project_code,
        agent_publication_id=job.agent_publication_id,
        application_publication_id=job.business_application_publication_id,
        correlation_id=correlation_id,
    )


def test_tool_mcp_excludes_tools_owned_by_other_mcp_servers() -> None:
    _runtime, job, service = _runtime_job(capabilities=(TOOL_NAME, "ones_work_item_search"))

    assert [item.name for item in service.catalog(job.id)] == [TOOL_NAME]
    with pytest.raises(ToolMcpError) as denied:
        service.descriptor(job.id, "ones_work_item_search")
    assert denied.value.code == "tool_mcp_tool_denied"


def test_standard_tool_mcp_invokes_current_python_job() -> None:
    runtime, job, service = _runtime_job()

    catalog = service.catalog(job.id)
    assert [item.name for item in catalog] == [TOOL_NAME]
    selected_job, descriptor = service.descriptor(job.id, TOOL_NAME)
    result = service.invoke(
        job=selected_job,
        descriptor=descriptor,
        arguments=TOOL_ARGUMENTS,
        request_identity=_request_identity(job, "tool-call-1"),
    )

    assert result.payload["security"]["trust"] == "untrusted_internal_evidence"
    assert [item["tool_name"] for item in runtime.agent_repository.list_tool_calls(job.id)] == [
        TOOL_NAME
    ]


def test_standard_mcp_http_has_no_auth_protocol_and_rejects_credentials() -> None:
    _runtime, job, service = _runtime_job()
    app = create_app(service, allowed_hosts=("testserver",))
    headers = {
        "content-type": "application/json",
        "accept": "application/json, text/event-stream",
        "x-job-id": job.id,
        "x-invocation-id": f"{job.id}.attempt-{job.retry_count}",
        "x-app-user-id": job.internal_user_id,
        "x-project-code": job.project_code,
        "x-agent-publication-id": job.agent_publication_id,
        "x-application-publication-id": job.business_application_publication_id,
        "x-correlation-id": "tool-mcp-http-test",
    }

    with TestClient(app) as client:
        health = client.get("/health")
        credential_rejected = client.post(
            "/mcp",
            headers={**headers, "authorization": "Bearer must-not-exist"},
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        initialized = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "runtime-test", "version": "1"},
                },
            },
        )
        protocol_headers = {**headers, "mcp-protocol-version": "2025-06-18"}
        listed = client.post(
            "/mcp",
            headers=protocol_headers,
            json={"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}},
        )
        called = client.post(
            "/mcp",
            headers=protocol_headers,
            json={
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": TOOL_NAME, "arguments": TOOL_ARGUMENTS},
            },
        )

    assert health.status_code == 200
    assert health.json()["server_code"] == "tool-mcp"
    assert credential_rejected.status_code == 400
    assert credential_rejected.json() == {"error": "tool_mcp_credentials_forbidden"}
    assert initialized.status_code == 200
    assert initialized.json()["result"]["serverInfo"]["name"] == "Enterprise Tool MCP"
    assert [item["name"] for item in listed.json()["result"]["tools"]] == [TOOL_NAME]
    assert called.status_code == 200
    assert called.json()["result"]["isError"] is False
    assert set(called.json()["result"]["_meta"]) == {
        "enterprise-agent/mcp-call-id",
        "enterprise-agent/agent-tool-call-id",
    }
    audit_events = _runtime.database.execute(
        "select event_kind, status from mcp_operation_audit where job_id = ?",
        (job.id,),
    )
    assert {(item["event_kind"], item["status"]) for item in audit_events} == {
        ("AUTHORIZATION", "SUCCEEDED"),
        ("RESOURCE", "SUCCEEDED"),
        ("TOOL", "SUCCEEDED"),
    }


def test_tool_mcp_repeated_same_name_calls_keep_distinct_exact_links() -> None:
    runtime, job, service = _runtime_job()
    selected_job, descriptor = service.descriptor(job.id, TOOL_NAME)

    def invoke(index: int):
        return service.invoke(
            job=selected_job,
            descriptor=descriptor,
            arguments={**TOOL_ARGUMENTS, "query": f"order-{index}"},
            request_identity=_request_identity(job, f"tool-concurrent-{index}"),
        )

    results = [invoke(index) for index in range(2)]

    assert len({item.audit_handle.mcp_call_id for item in results}) == 2
    rows = runtime.database.execute(
        "select id, mcp_call_id from agent_tool_call where job_id = ? order by id",
        (job.id,),
    )
    assert len(rows) == 2
    assert len({row["mcp_call_id"] for row in rows}) == 2
    audits = runtime.database.execute(
        "select mcp_call_id, agent_tool_call_id, event_kind "
        "from mcp_operation_audit where job_id = ?",
        (job.id,),
    )
    mapping = {
        row["mcp_call_id"]: row["agent_tool_call_id"]
        for row in audits
        if row["event_kind"] == "TOOL"
    }
    assert len(mapping) == 2
    assert len(set(mapping.values())) == 2


def test_tool_mcp_audit_failure_closes_before_tool_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _runtime, job, service = _runtime_job()
    selected_job, descriptor = service.descriptor(job.id, TOOL_NAME)
    executed = False

    def reject_audit(*_args, **_kwargs):
        raise ToolPolicyError(
            "audit unavailable",
            safe_message="MCP 操作审计不可用",
            error_code="mcp_audit_unavailable",
        )

    def execute_tool(**_kwargs):
        nonlocal executed
        executed = True
        raise AssertionError("tool must not execute")

    monkeypatch.setattr(service.audit_coordinator, "begin", reject_audit)
    monkeypatch.setattr(service.tool_registry, "call", execute_tool)

    with pytest.raises(ToolPolicyError) as raised:
        service.invoke(
            job=selected_job,
            descriptor=descriptor,
            arguments=TOOL_ARGUMENTS,
            request_identity=_request_identity(job, "tool-audit-down"),
        )

    assert raised.value.error_code == "mcp_audit_unavailable"
    assert executed is False
