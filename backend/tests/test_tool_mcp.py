from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from app.modules.agent.infrastructure.mcp_tool_registry import ToolRegistry
from app.modules.job.infrastructure.repositories import now_iso
from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST
from app.services.tool_mcp import JobToolService, ToolMcpError, create_app
from backend.tests.helpers import container, prepare_debug_application_access


def _runtime_job(*, capabilities: tuple[str, ...] = ("get_er_context",)):
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
    )
    return runtime, claimed, service


def test_tool_mcp_excludes_tools_owned_by_other_mcp_servers() -> None:
    _runtime, job, service = _runtime_job(
        capabilities=("get_er_context", "ones_work_item_search")
    )

    assert [item.name for item in service.catalog(job.id)] == ["get_er_context"]
    with pytest.raises(ToolMcpError) as denied:
        service.descriptor(job.id, "ones_work_item_search")
    assert denied.value.code == "tool_mcp_tool_denied"


def test_standard_tool_mcp_invokes_job_frozen_readonly_tool_for_both_runtimes() -> None:
    runtime, job, service = _runtime_job()

    catalog = service.catalog(job.id)
    assert [item.name for item in catalog] == ["get_er_context"]
    selected_job, descriptor = service.descriptor(job.id, "get_er_context")
    result = service.invoke(
        job=selected_job,
        descriptor=descriptor,
        arguments={"query": "order"},
        correlation_id="tool-call-1",
    )

    assert result["security"]["trust"] == "untrusted_internal_evidence"
    assert [item["tool_name"] for item in runtime.agent_repository.list_tool_calls(job.id)] == [
        "get_er_context"
    ]

    runtime.database.execute(
        "update agent_job set agent_runtime_kind = 'typescript-v1' where id = ?",
        (job.id,),
    )
    assert [item.name for item in service.catalog(job.id)] == ["get_er_context"]


def test_standard_mcp_http_has_no_auth_protocol_and_rejects_credentials() -> None:
    _runtime, job, service = _runtime_job()
    app = create_app(service, allowed_hosts=("testserver",))
    headers = {
        "content-type": "application/json",
        "accept": "application/json, text/event-stream",
        "x-job-id": job.id,
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
                "params": {"name": "get_er_context", "arguments": {"query": "order"}},
            },
        )

    assert health.status_code == 200
    assert health.json()["server_code"] == "tool-mcp"
    assert credential_rejected.status_code == 400
    assert credential_rejected.json() == {"error": "tool_mcp_credentials_forbidden"}
    assert initialized.status_code == 200
    assert initialized.json()["result"]["serverInfo"]["name"] == "Enterprise Tool MCP"
    assert [item["name"] for item in listed.json()["result"]["tools"]] == ["get_er_context"]
    assert called.status_code == 200
    assert called.json()["result"]["isError"] is False
