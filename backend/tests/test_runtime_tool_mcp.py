from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from app.modules.agent.application.runtime_migration_gate import RuntimeMigrationGate
from app.modules.agent.infrastructure.mcp_tool_registry import ToolRegistry
from app.modules.agent.infrastructure.runtime_tool_token import (
    RuntimeToolTokenError,
    RuntimeToolTokenIssuer,
    RuntimeToolTokenVerifier,
)
from app.services.runtime_tool_mcp import (
    RuntimeToolAuthorizationError,
    RuntimeToolAuthorizer,
    create_app,
)
from app.shared.config import AgentRuntimeSettings
from backend.tests.helpers import container, prepare_debug_application_access


_KEY = b"runtime-tool-mcp-test-signing-key-0000000000000000"


def _runtime_job():
    runtime = container()
    runtime.database.execute(
        """
        insert into permission_policy
          (id, subject_type, subject_code, resource_type, resource_code,
           effect, action, status, priority, revision, created_at, updated_at)
        values
          ('runtime-tool-test-user-tool', 'user', 'user_local_admin',
           'tool', '*', 'allow', 'use', 'enabled', 1, 1,
           CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
          ('runtime-tool-test-user-project', 'user', 'user_local_admin',
           'project', 'default', 'allow', 'use', 'enabled', 1, 1,
           CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        on conflict(id) do nothing
        """
    )
    runtime.create_agent_job_service.runtime_migration_gate = RuntimeMigrationGate(
        AgentRuntimeSettings(typescript_environments=("local",))
    )
    runtime.create_agent_job_service.runtime_environment = "local"
    selection = prepare_debug_application_access(
        runtime,
        application_code="runtime-tool-mcp-application",
        role_code="runtime-tool-mcp-role",
        capabilities=("get_er_context",),
    )
    job, _ = runtime.debug_job_access_service.create_job(
        user_id="user_local_admin",
        display_name="Administrator",
        message="diagnose",
        application_id=selection["application_id"],
        execution_scope_id=selection["execution_scope_id"],
        idempotency_key="runtime-tool-mcp-job",
        correlation_id="runtime-tool-mcp-test",
        environment="local",
    )
    claimed = runtime.agent_repository.claim_job(job.id, "agent-worker-test")
    assert claimed is not None
    authorizer = RuntimeToolAuthorizer(
        repository=runtime.agent_repository,
        tool_registry=ToolRegistry(runtime.tool_service),
        snapshot_service=runtime.builtin_tool_snapshot_service,
        governed_executor=runtime.governed_api_runtime_executor,
    )
    return runtime, claimed, authorizer


def _binding(runtime) -> dict[str, str]:
    definition = ToolRegistry(runtime.tool_service).handler_registry.require(
        "get_er_context",
        "1.0.0",
    )
    return {
        "tool_name": "get_er_context",
        "required_scope": "tool:get_er_context",
        "tool_schema_hash": definition.public_schema_hash,
    }


def _token(runtime, job, *, binding: dict[str, str] | None = None, now=None) -> str:
    selected = binding or _binding(runtime)
    issuer = RuntimeToolTokenIssuer(_KEY, now=now)
    return issuer.issue(
        app_user_id=job.internal_user_id or job.user_id,
        job_id=job.id,
        application_publication_id=job.business_application_publication_id,
        project_code=job.project_code,
        scopes=[selected["required_scope"]],
        tool_bindings=[selected],
        job_timeout_seconds=300,
    )


def test_runtime_tool_authorizer_invokes_only_exact_job_bound_readonly_tool() -> None:
    runtime, job, authorizer = _runtime_job()
    verifier = RuntimeToolTokenVerifier(_KEY)
    token = _token(runtime, job)
    claims = verifier.verify(token)

    catalog = authorizer.catalog(claims)
    assert [item.name for item in catalog] == ["get_er_context"]
    descriptor = catalog[0]
    verifier.verify(
        token,
        required_scope=descriptor.required_scope,
        tool_name=descriptor.name,
        tool_schema_hash=descriptor.schema_hash,
    )
    result = authorizer.invoke(
        claims=claims,
        descriptor=descriptor,
        arguments={"query": "order"},
        correlation_id="runtime-tool-call",
    )

    assert result["security"]["job_bound"] is True
    calls = runtime.agent_repository.list_tool_calls(job.id)
    assert [item["tool_name"] for item in calls] == ["get_er_context"]


@pytest.mark.parametrize(
    ("field", "value", "error_code"),
    [
        ("sub", "forged-user", "runtime_tool_subject_mismatch"),
        (
            "application_publication_id",
            "forged-application-publication",
            "runtime_tool_application_mismatch",
        ),
        ("project_code", "forged-project", "runtime_tool_project_mismatch"),
    ],
)
def test_runtime_tool_authorizer_rejects_forged_job_facts(
    field: str,
    value: str,
    error_code: str,
) -> None:
    runtime, job, authorizer = _runtime_job()
    claims = RuntimeToolTokenVerifier(_KEY).verify(_token(runtime, job))

    with pytest.raises(RuntimeToolAuthorizationError) as raised:
        authorizer.authorize_request({**claims, field: value})

    assert raised.value.code == error_code


def test_runtime_tool_rejects_schema_scope_resource_and_unmapped_write_bindings() -> None:
    runtime, job, authorizer = _runtime_job()
    verifier = RuntimeToolTokenVerifier(_KEY)
    valid = _binding(runtime)

    wrong_schema = {**valid, "tool_schema_hash": "b" * 64}
    wrong_schema_token = _token(runtime, job, binding=wrong_schema)
    with pytest.raises(RuntimeToolAuthorizationError) as schema_denied:
        authorizer.catalog(verifier.verify(wrong_schema_token))
    assert schema_denied.value.code == "runtime_tool_binding_denied"

    with pytest.raises(RuntimeToolTokenError) as scope_denied:
        verifier.verify(
            _token(runtime, job),
            required_scope="tool:query_database",
        )
    assert scope_denied.value.code == "runtime_tool_scope_denied"

    forged_resource = {**valid, "resource_revision_id": "resource-revision-forged"}
    with pytest.raises(RuntimeToolAuthorizationError) as resource_denied:
        authorizer.catalog(verifier.verify(_token(runtime, job, binding=forged_resource)))
    assert resource_denied.value.code == "runtime_tool_resource_binding_denied"

    write_binding = {
        "tool_name": "write_database",
        "required_scope": "tool:write_database",
        "tool_schema_hash": "c" * 64,
    }
    with pytest.raises(RuntimeToolAuthorizationError) as write_denied:
        authorizer.catalog(verifier.verify(_token(runtime, job, binding=write_binding)))
    assert write_denied.value.code == "runtime_tool_binding_denied"


def test_runtime_tool_rejects_expired_token_and_python_job() -> None:
    runtime, job, authorizer = _runtime_job()
    with pytest.raises(RuntimeToolTokenError) as expired:
        RuntimeToolTokenVerifier(_KEY).verify(_token(runtime, job, now=lambda: 1))
    assert expired.value.code == "runtime_tool_token_expired"

    runtime.database.execute(
        "update agent_job set agent_runtime_kind = 'python-v1' where id = ?",
        (job.id,),
    )
    claims = RuntimeToolTokenVerifier(_KEY).verify(_token(runtime, job))
    with pytest.raises(RuntimeToolAuthorizationError) as runtime_denied:
        authorizer.authorize_request(claims)
    assert runtime_denied.value.code == "runtime_tool_runtime_mismatch"


def test_runtime_tool_http_health_is_public_but_mcp_requires_bearer() -> None:
    runtime, job, authorizer = _runtime_job()
    token = _token(runtime, job)
    app = create_app(
        verifier=RuntimeToolTokenVerifier(_KEY),
        authorizer=authorizer,
        allowed_hosts=("testserver",),
    )

    with TestClient(app) as client:
        health = client.get("/health")
        denied = client.post(
            "/mcp",
            headers={"content-type": "application/json"},
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        headers = {
            "authorization": f"Bearer {token}",
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
        }
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
            headers={**protocol_headers, "x-user-id": "forged-user"},
            json={
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "get_er_context", "arguments": {"query": "order"}},
            },
        )

    assert health.status_code == 200
    assert health.json()["tool_invoked"] is False
    assert denied.status_code == 401
    assert denied.json() == {"error": "runtime_tool_authentication_failed"}
    assert initialized.status_code == 200
    assert initialized.json()["result"]["serverInfo"]["name"] == "Enterprise Runtime Tool MCP"
    assert [item["name"] for item in listed.json()["result"]["tools"]] == ["get_er_context"]
    assert called.status_code == 200
    assert called.json()["result"]["isError"] is False
