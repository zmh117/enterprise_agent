from __future__ import annotations

from io import BytesIO
import json
from unittest.mock import Mock
from urllib.parse import parse_qs, urlparse

import pytest
from starlette.testclient import TestClient

from app.modules.mcp_tool_runtime.direct_executor import DirectReadOnlyToolExecutor
from app.modules.mcp_tool_runtime.resource_resolver import DirectResourceResolver
from app.modules.mcp_tool_runtime.domain.schema_directory import SchemaColumn, SchemaTable
from app.modules.mcp_tool_runtime.domain.topology import DatabaseEngine
from app.modules.mcp_tool_runtime.infrastructure.db.schema_directory import (
    FakeSchemaInspector,
    SchemaInspectorFactory,
)
from app.modules.mcp_tool_runtime.schema_cursor_store import SchemaPaginationCursorStore
from app.modules.mcp_tool_runtime.infrastructure.loki_gateway import HttpLokiClient
from app.modules.platform_config.application.governed_resources import (
    ResourceVerificationOutcome,
)
from app.shared.exceptions import AppError, NonRetryableExecutionError, ToolPolicyError
from app.services.tool_mcp import (
    ToolMcpError,
    create_app,
)


from backend.tests.support.tool_mcp import (
    TOOL_ARGUMENTS,
    TOOL_NAME,
    request_identity as _request_identity,
    runtime_job as _runtime_job,
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


@pytest.fixture
def paged_schema_runtime():
    runtime, job, service = _runtime_job()
    secret_provider = Mock()
    secret_provider.resolve.return_value = "test-only-password"
    executor = DirectReadOnlyToolExecutor(
        DirectResourceResolver(runtime.database, secret_provider=secret_provider),
        limits=runtime.settings.execution,
    )
    inspector = FakeSchemaInspector(
        [SchemaTable(f"orders_{i:03d}", [SchemaColumn("id", "bigint", False)]) for i in range(151)]
    )
    executor.schema_inspectors = SchemaInspectorFactory({DatabaseEngine.MYSQL: inspector})
    runtime.tool_service.tool_executor = executor
    yield runtime, job, service, inspector
    runtime.database.close()


def _schema_page(job, service, **overrides):
    selected_job, descriptor = service.descriptor(job.id, TOOL_NAME)
    return service.invoke(
        job=selected_job,
        descriptor=descriptor,
        arguments={**TOOL_ARGUMENTS, "limit": 50, **overrides},
        request_identity=_request_identity(job, "schema-pagination-test"),
    )


def test_schema_mcp_four_pages_expose_only_short_cursors_and_keep_exact_positions(
    paged_schema_runtime,
):
    runtime, job, service, inspector = paged_schema_runtime
    cursor = ""
    collected = []
    for page in range(4):
        result = _schema_page(job, service, cursor=cursor)
        data = result.payload["data"]
        collected.extend(item["name"] for item in data["tables"])
        cursor = data["next_cursor"]
        if page < 3:
            assert len(cursor) == 19 and cursor.startswith("pg_")
            original = runtime.tool_service.schema_cursor_store.resolve(
                job_id=job.id, reference=cursor
            )
            assert original not in json.dumps(result.payload)
            # Discard the store instance between requests; no in-memory cache is required.
            runtime.tool_service.schema_cursor_store = SchemaPaginationCursorStore(runtime.database)
        else:
            assert cursor == "" and data["has_more"] is False
    assert collected == [f"orders_{i:03d}" for i in range(151)]
    assert [call["after_table"] for call in inspector.calls] == [
        "",
        "orders_049",
        "orders_099",
        "orders_149",
    ]


def test_schema_mcp_legacy_cursor_continues_but_issues_short_cursor(paged_schema_runtime):
    runtime, job, service, inspector = paged_schema_runtime
    first = _schema_page(job, service)
    original = runtime.tool_service.schema_cursor_store.resolve(
        job_id=job.id,
        reference=first.payload["data"]["next_cursor"],
    )
    second = _schema_page(job, service, cursor=original)
    assert inspector.calls[-1]["after_table"] == "orders_049"
    assert len(second.payload["data"]["next_cursor"]) == 19


@pytest.mark.parametrize(
    "case", ["typo", "query", "revision", "authorization", "storage", "corrupt_original"]
)
def test_schema_mcp_short_cursor_keeps_fail_closed_checks(paged_schema_runtime, case, monkeypatch):
    runtime, job, service, inspector = paged_schema_runtime
    first = _schema_page(job, service)
    cursor = first.payload["data"]["next_cursor"]
    args = {"cursor": cursor}
    expected = "mcp_pagination_cursor_invalid"
    if case == "typo":
        args["cursor"] = cursor[:-1] + ("0" if cursor[-1] != "0" else "1")
    elif case == "query":
        args["query"] = "different"
    elif case == "revision":
        runtime.database.execute(
            "update platform_resource_revision set content_hash = ? where resource_id = "
            "(select id from platform_resource where code = ?)",
            ("d" * 64, "tool_mcp_test_database"),
        )
        expected = "mcp_pagination_cursor_stale"
    elif case == "authorization":
        from app.shared.exceptions import PermissionDenied

        denied = PermissionDenied("synthetic revoked grant", safe_message="当前授权已撤销")
        monkeypatch.setattr(
            runtime.business_authorization_service, "require", Mock(side_effect=denied)
        )
        expected = denied.error_code
    elif case == "corrupt_original":
        runtime.database.execute(
            "update mcp_schema_pagination_cursor set original_cursor = ? where job_id = ? and reference = ?",
            ("malformed-original", job.id, cursor),
        )
    else:
        runtime.database.execute("drop table mcp_schema_pagination_cursor")
        expected = "mcp_pagination_store_unavailable"
    with pytest.raises(AppError) as error:
        _schema_page(job, service, **args)
    assert error.value.error_code == expected
    assert len(inspector.calls) == 1  # Never query Provider with an invalid continuation.


def test_schema_mcp_cannot_report_pagination_success_when_state_cannot_be_saved(
    paged_schema_runtime,
):
    runtime, job, service, _ = paged_schema_runtime
    runtime.database.execute("drop table mcp_schema_pagination_cursor")
    with pytest.raises(NonRetryableExecutionError) as error:
        _schema_page(job, service)
    assert error.value.error_code == "mcp_pagination_store_unavailable"
    assert runtime.agent_repository.list_tool_calls(job.id)[-1]["status"] == "FAILED"


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


def test_loki_invalid_label_keeps_specific_error_in_mcp_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = "diagnose_loki_label_values"
    runtime, job, service = _runtime_job(capabilities=(tool,))
    try:
        selected_job, descriptor = service.descriptor(job.id, tool)

        def forbidden_provider(**_kwargs):
            raise AssertionError("Invalid label must not reach the provider")

        monkeypatch.setattr(runtime.tool_service.tool_executor, tool, forbidden_provider)
        with pytest.raises(ToolPolicyError) as error:
            service.invoke(
                job=selected_job,
                descriptor=descriptor,
                arguments={"environment": "local", "base": "debug-base", "label": "app\n"},
                request_identity=_request_identity(job, "loki-invalid-label"),
            )
        assert error.value.error_code == "loki_label_invalid"
        assert "标签名" in error.value.safe_message
        row = runtime.database.execute_one(
            "select status, error_code from mcp_operation_audit where id = ?",
            (error.value.mcp_audit_handle.root_audit_id,),
        )
        assert row is not None and row["status"] == "DENIED"
        assert row["error_code"] == "loki_label_invalid"
    finally:
        runtime.database.close()


@pytest.mark.parametrize(
    "tool",
    ["query_loki", "diagnose_loki_probe", "diagnose_loki_labels", "diagnose_loki_label_values"],
)
def test_loki_job_uses_published_fixed_scope_with_custom_labels(
    tool: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, job, service = _runtime_job(capabilities=(tool,))
    requests = []
    fixed = {"customer": "A", "workshop": "GL001"}

    class Verifier:
        def verify(self, **_kwargs):
            return ResourceVerificationOutcome(
                status="PASSED", provider_contract_version="loki_v1", checks={"connection": True}
            )

    def fetch(request, timeout):
        requests.append(request)
        if urlparse(request.full_url).path.endswith("/series"):
            body = {
                "status": "success",
                "data": [{**fixed, "app": "mes-run", "logtype": "error", "custom_label": "v1"}],
            }
        else:
            body = {"status": "success", "data": {"resultType": "streams", "result": []}}
        return BytesIO(json.dumps(body).encode())

    try:
        resources = runtime.platform_config_service.governed_resources
        resources.create_resource(
            {
                "code": "loki_scoped_test",
                "name": "范围隔离测试",
                "resource_kind": "loki",
                "scope_type": "environment",
                "environment_code": "local",
                "provider_type": "loki",
                "config": {
                    "base_url": "http://loki.test:3100",
                    "tenant_id": "test-tenant",
                    "timeout_seconds": 5,
                    "max_minutes": 60,
                    "max_lines": 100,
                    "max_response_bytes": 65536,
                },
                "secret_refs": {},
                "scope_bindings": [
                    {
                        "environment_code": "local",
                        "base_code": "debug-base",
                        "selector_conditions": fixed,
                    }
                ],
            },
            actor_id="user_local_admin",
        )
        resources.verify_draft("loki_scoped_test", actor_id="user_local_admin", verifier=Verifier())
        resources.publish_draft("loki_scoped_test", actor_id="user_local_admin")
        client = HttpLokiClient(
            max_minutes=60, max_lines=100, max_response_chars=8000, urlopen_func=fetch
        )
        secrets = Mock()
        executor = DirectReadOnlyToolExecutor(
            DirectResourceResolver(runtime.database, secret_provider=secrets),
            limits=runtime.settings.execution,
        )
        monkeypatch.setattr(runtime.tool_service, "tool_executor", executor)
        monkeypatch.setattr(executor, "_loki", lambda _resource: client)
        selected_job, descriptor = service.descriptor(job.id, tool)
        args = {"environment": "local", "base": "debug-base", "limit": 10}
        if tool in ("query_loki", "diagnose_loki_probe"):
            args["selector"] = {"custom_label": "v1", "logtype": "error"}
        elif tool == "diagnose_loki_label_values":
            args["label"] = "custom_label"
        result = service.invoke(
            job=selected_job,
            descriptor=descriptor,
            arguments=args,
            request_identity=_request_identity(job, "loki-scoped-job"),
        )
        assert result.payload["metadata"]["resource_code"] == "loki_scoped_test"
        assert result.payload["metadata"]["resource_revision_id"]
        assert len(requests) == 1
        secrets.resolve.assert_not_called()
        params = parse_qs(urlparse(requests[0].full_url).query)
        expression = params.get("query", params.get("match[]"))[0]
        assert 'customer="A"' in expression and 'workshop="GL001"' in expression
        row = runtime.database.execute_one(
            "select status from mcp_operation_audit where id = ?",
            (result.audit_handle.root_audit_id,),
        )
        assert row is not None and row["status"] == "SUCCEEDED"
        if tool in ("query_loki", "diagnose_loki_probe"):
            with pytest.raises(ToolPolicyError) as error:
                service.invoke(
                    job=selected_job,
                    descriptor=descriptor,
                    arguments={**args, "selector": {"customer": "B"}},
                    request_identity=_request_identity(job, "loki-scope-conflict"),
                )
            assert error.value.error_code == "loki_fixed_label_conflict"
            assert len(requests) == 1
            row = runtime.database.execute_one(
                "select status, error_code from mcp_operation_audit where id = ?",
                (error.value.mcp_audit_handle.root_audit_id,),
            )
            assert row is not None and row["status"] == "DENIED"
            assert row["error_code"] == "loki_fixed_label_conflict"
    finally:
        runtime.database.close()
