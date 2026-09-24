"""Independent Inspector -> real project HTTP -> governed synthetic resource."""

from __future__ import annotations

import json
import os
import socket
from urllib.parse import urlparse

import pytest

from backend.tests.support.mcp_inspector import Inspector, InspectorFailure, live_tool_mcp

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_MCP_INSPECTOR_SMOKE") != "1",
    reason="Inspector 集成测试未启用；安装固定依赖后运行 make test-mcp-inspector",
)


@pytest.fixture(scope="module")
def inspector():
    return Inspector.installed()


@pytest.fixture
def target():
    # Lazy imports keep the ordinary suite collectable without the optional MCP extra.
    from app.modules.mcp_tool_runtime.direct_executor import DirectReadOnlyToolExecutor
    from app.modules.mcp_tool_runtime.domain.schema_directory import SchemaColumn, SchemaTable
    from app.modules.mcp_tool_runtime.domain.topology import DatabaseEngine
    from app.modules.mcp_tool_runtime.infrastructure.db.schema_directory import (
        FakeSchemaInspector,
        SchemaInspectorFactory,
    )
    from app.modules.mcp_tool_runtime.resource_resolver import DirectResourceResolver
    from backend.tests.support.runtime import DirectJobTestPermissionService
    from backend.tests.support.tool_mcp import request_headers, runtime_job

    runtime, job, service = runtime_job(allow_direct_jobs=False)
    try:
        assert not isinstance(runtime.permission_service, DirectJobTestPermissionService)
        tables = [SchemaTable("orders_001", [SchemaColumn("id", "bigint", False)])]
        resource = FakeSchemaInspector(tables)
        executor = DirectReadOnlyToolExecutor(
            DirectResourceResolver(
                runtime.database,
                secret_provider=runtime.platform_config_service.secret_provider,
            ),
            limits=runtime.settings.execution,
        )
        executor.schema_inspectors = SchemaInspectorFactory({DatabaseEngine.MYSQL: resource})
        runtime.tool_service.tool_executor = executor
        with live_tool_mcp(service) as url:
            yield runtime, job, resource, tables, url, request_headers(job, "inspector-smoke")
    finally:
        runtime.database.close()


def call_tool(inspector, target, *, tool="get_schema_directory", arguments=None, headers=None):
    from backend.tests.support.tool_mcp import TOOL_ARGUMENTS

    return inspector.call(
        target[4],
        target[5] if headers is None else headers,
        method="tools/call",
        tool=tool,
        arguments=TOOL_ARGUMENTS if arguments is None else arguments,
    )


def assert_audit(target, result):
    runtime, job, *_ = target
    meta = result["_meta"]
    assert set(meta) == {"enterprise-agent/mcp-call-id", "enterprise-agent/agent-tool-call-id"}
    mcp_id = meta["enterprise-agent/mcp-call-id"]
    tool_id = meta["enterprise-agent/agent-tool-call-id"]
    row = runtime.database.execute_one(
        "select mcp_call_id, status from agent_tool_call where job_id = ? and id = ?",
        (job.id, tool_id),
    )
    assert row is not None and row["mcp_call_id"] == mcp_id and row["status"] == "SUCCEEDED"
    rows = runtime.database.execute(
        "select agent_tool_call_id, event_kind, status from mcp_operation_audit "
        "where job_id = ? and mcp_call_id = ?",
        (job.id, mcp_id),
    )
    assert {(row["event_kind"], row["status"]) for row in rows} == {
        ("AUTHORIZATION", "SUCCEEDED"),
        ("RESOURCE", "SUCCEEDED"),
        ("TOOL", "SUCCEEDED"),
    }
    assert all(row["agent_tool_call_id"] == tool_id for row in rows)


def test_connect(inspector, target):
    result = inspector.call(target[4], target[5], method="initialize").success()
    assert result["serverInfo"]["name"] == "Enterprise Tool MCP"
    assert target[2].calls == []


def test_authorized_catalog(inspector, target):
    from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST, mcp_tool_schema_hash

    runtime, job, *_ = target
    tools = inspector.call(target[4], target[5], method="tools/list").success()["tools"]
    assert [tool["name"] for tool in tools] == ["get_schema_directory"]
    snapshot = runtime.mcp_tool_snapshot_service.verify(job.id)["snapshot"]
    selected = [tool for tool in snapshot["tools"] if tool["server_code"] == "tool-mcp"]
    assert {tool["tool_identifier"] for tool in selected} == {"get_schema_directory"}
    for tool in tools:
        actual = mcp_tool_schema_hash(tool["inputSchema"])
        assert actual == MCP_TOOL_MANIFEST[tool["name"]].schema_hash
        assert actual == next(
            t["schema_hash"] for t in selected if t["tool_identifier"] == tool["name"]
        )
    assert target[2].calls == []


def test_success_and_audit(inspector, target):
    result = call_tool(inspector, target).success()
    assert result["isError"] is False
    payload = result["structuredContent"]
    assert payload == json.loads(result["content"][0]["text"])
    assert payload["data"]["tables"] == [table.to_dict() for table in target[3]]
    assert payload["security"]["trust"] == "untrusted_internal_evidence"
    assert target[2].calls == [
        {
            "environment": "local",
            "base": "debug-base",
            "workshop": None,
            "query": "order",
            "after_table": "",
        }
    ]
    assert_audit(target, result)


def test_repeated_calls(inspector, target):
    from backend.tests.support.tool_mcp import TOOL_ARGUMENTS

    results = [
        call_tool(inspector, target, arguments={**TOOL_ARGUMENTS, "query": query}).success()
        for query in ("001", "order")
    ]
    assert len({item["_meta"]["enterprise-agent/mcp-call-id"] for item in results}) == 2
    assert len({item["_meta"]["enterprise-agent/agent-tool-call-id"] for item in results}) == 2
    assert len(target[0].run_audit_repository.list_tool_calls(target[1].id)) == 2
    assert len(target[2].calls) == 2
    assert [call["query"] for call in target[2].calls] == ["001", "order"]
    for result in results:
        assert_audit(target, result)


def test_invalid_arguments(inspector, target):
    from backend.tests.support.tool_mcp import TOOL_ARGUMENTS

    result = call_tool(inspector, target, arguments={**TOOL_ARGUMENTS, "limit": 51})
    assert result.returncode == 5
    assert result.error and result.error["code"] == "tool_is_error"
    assert result.result["isError"] is True
    assert result.result["structuredContent"]["error_code"] == "mcp_schema_directory_input_invalid"
    assert target[2].calls == []
    rows = target[0].run_audit_repository.list_tool_calls(target[1].id)
    assert len(rows) == 1 and rows[0]["status"] == "DENIED"


def test_excluded_tool(inspector, target):
    tools = inspector.call(target[4], target[5], method="tools/list").success()["tools"]
    assert "query_database" not in {tool["name"] for tool in tools}
    result = call_tool(inspector, target, tool="query_database", arguments={})
    assert result.returncode == 5
    assert result.error and result.error["code"] == "tool_not_found"
    assert "not found" in result.error["message"]
    assert result.result is None  # Inspector refuses a tool absent from tools/list.
    assert target[2].calls == []
    assert target[0].run_audit_repository.list_tool_calls(target[1].id) == []


def test_missing_execution_header(inspector, target):
    headers = dict(target[5])
    del headers["x-invocation-id"]
    result = call_tool(inspector, target, headers=headers)
    assert result.returncode == 5
    assert result.error and result.error["code"] == "tool_is_error"
    assert result.result["isError"] is True
    assert result.result["structuredContent"]["error_code"] == "tool_mcp_context_missing"
    assert target[2].calls == []
    assert target[0].run_audit_repository.list_tool_calls(target[1].id) == []


def test_forbidden_authorization(inspector, target):
    result = call_tool(
        inspector,
        target,
        headers={
            **target[5],
            "authorization": "Bearer inspector-fixed-fake-value",
        },
    )
    assert result.returncode == 1
    assert result.error and result.error["code"] == "error"
    assert result.error["status"] == 400
    assert "tool_mcp_credentials_forbidden" in result.error["message"]
    assert result.result is None
    assert target[2].calls == []
    assert target[0].run_audit_repository.list_tool_calls(target[1].id) == []


def test_connection_failure_is_not_denial(inspector):
    # Reserve a loopback port without listening: no unrelated service can grab it.
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        url = f"http://127.0.0.1:{listener.getsockname()[1]}/mcp"
        result = inspector.call(url, {}, method="initialize")
    assert result.returncode == 4
    assert result.error and result.error["code"] == "unreachable"
    assert result.result is None
    with pytest.raises(InspectorFailure, match="未返回预期成功结果"):
        result.success()


def test_inspector_total_timeout(inspector):
    # Accept TCP handshakes but never answer HTTP, so the outer deadline must reap Node.
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        url = f"http://127.0.0.1:{listener.getsockname()[1]}/mcp"
        with pytest.raises(InspectorFailure, match="调用超时"):
            inspector.call(url, {}, method="initialize", timeout=0.5)


def test_live_server_port_and_database_close_after_assertion():
    from backend.tests.support.tool_mcp import runtime_job

    runtime, _, service = runtime_job(allow_direct_jobs=False)
    try:
        with pytest.raises(AssertionError, match="synthetic assertion"):
            with live_tool_mcp(service) as url:
                port = urlparse(url).port
                raise AssertionError("synthetic assertion")
        with socket.socket() as probe:
            assert probe.connect_ex(("127.0.0.1", port)) != 0
    finally:
        runtime.database.close()

    assert runtime.database.pool_snapshot().opened == 0
    assert runtime.database.pool_snapshot().checked_out == 0
