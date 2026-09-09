from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator
from mcp import types

from app.python_runtime.job_sandbox import JobSandboxError, JobSandboxManager
from app.python_runtime.ones_result_bridge import OnesResultBridge, materialize_result
from app.shared.ones_tool_contracts import ONES_COLLECTED_LIST_FIELDS, ONES_TOOL_CONTRACTS
from app.shared.tool_contract import tool_schema_hash
from services.ones_mcp_server.errors import OnesMcpError
from services.ones_mcp_server.provider.graphql.collection import collect_pages
from services.ones_mcp_server.provider.graphql.operations.normalization import page_items
from tests.test_ones_mcp_runtime import _fixture, _PagingGraphql, _normalized_project_page


@pytest.mark.parametrize("ending", ["success", "failure", "cancel", "timeout"])
def test_runtime_ones_only_job_reads_result_and_cleans_on_every_exit(tmp_path, ending):
    from app.modules.agent.domain.runtime import (
        AgentExecutionContext,
        AgentRunRequest,
        McpRuntimeBinding,
    )
    from app.modules.model_connection.domain import ModelRuntimeBinding
    from app.python_runtime.claude_client import ClaudeSdk
    from app.python_runtime.mcp_config import FixedMcpClaudeSdkClient
    from app.shared.exceptions import AppError
    from backend.tests.support.runtime import test_settings

    name = "ones_search_projects"
    contract = ONES_TOOL_CONTRACTS[name]
    captured = {}
    cancel = threading.Event()

    class Session:
        async def initialize(self):
            pass

        async def list_tools(self, **kwargs):
            return types.ListToolsResult(
                tools=[
                    types.Tool.model_validate({"name": name, "inputSchema": contract.input_schema})
                ]
            )

        async def call_tool(self, *args, **kwargs):
            return types.CallToolResult.model_validate(
                {
                    "content": [],
                    "isError": False,
                    "structuredContent": _project_result(),
                    "_meta": {"enterprise-agent/mcp-call-id": "audit"},
                }
            )

    def factory(**kwargs):
        bridge = OnesResultBridge(**kwargs, session=Session())
        captured["bridge"] = bridge
        return bridge

    async def query(*, options, **kwargs):
        captured["cwd"] = options["cwd"]
        assert set(options["tools"]) == {"Read", "Glob", "Grep"}
        assert {"Write", "Edit", "Bash"} <= set(options["disallowed_tools"])
        result = await captured["bridge"].call_tool(name, {"keyword": ""})
        summary = result.model_dump(by_alias=True)["structuredContent"]
        path = Path(options["cwd"]) / summary["result_file"]
        assert "Project 1000" in path.read_text()
        allowed = await options["can_use_tool"]("Read", {"file_path": str(path)}, None)
        assert allowed["behavior"] == "allow"
        denied = await options["can_use_tool"](
            "Write", {"file_path": str(path), "content": "bad"}, None
        )
        assert denied["behavior"] == "deny"
        if ending == "failure":
            raise RuntimeError("synthetic failure")
        if ending == "cancel":
            cancel.set()
        if ending in {"cancel", "timeout"}:
            await asyncio.sleep(10)
        yield {"type": "result", "result": "已读取1000条", "is_error": False}

    sdk = ClaudeSdk(
        query=query,
        options=lambda **kw: kw,
        tool=None,
        create_sdk_mcp_server=lambda **kw: {"instance": object()},
        tool_annotations=None,
    )
    binding = ModelRuntimeBinding(
        protocol="anthropic_compatible",
        base_url="https://model.invalid/anthropic",
        model="synthetic",
        effort_level="max",
        default_opus_model="synthetic",
        default_sonnet_model="synthetic",
        default_haiku_model="synthetic",
        subagent_model="synthetic",
    )
    context = AgentExecutionContext(
        system_role="test",
        safety_rules=[],
        user_question="query",
        project_code="test",
        allowed_tools=[name],
        tool_restrictions=[],
        skills={},
        retrieved_context={},
        conversation_summary="",
        publication_id="publication",
        application_publication_id="application",
        model_runtime_binding=binding,
        timeout_seconds=1 if ending == "timeout" else 5,
        job_tool_snapshot_hash="0" * 64,
        mcp_bindings=(
            McpRuntimeBinding(
                server_code="ones-mcp",
                tool_name=name,
                required_scope=f"mcp:ones-mcp:{name}:invoke",
                tool_schema_hash=tool_schema_hash(contract.input_schema),
            ),
        ),
        control_plane_build_identity={
            "component": "control-plane",
            "source_revision": "test-revision",
            "build_id": "test-build",
            "platform": "linux/amd64",
        },
        worker_build_identity={
            "component": "agent-worker",
            "source_revision": "test-revision",
            "build_id": "test-build",
            "platform": "linux/amd64",
        },
    )
    client = FixedMcpClaudeSdkClient(
        limits=test_settings().execution,
        api_key="synthetic-key",
        mcp_server_url="http://tool.invalid/mcp",
        mcp_principal_tokens={"ones-mcp": "synthetic-principal"},
        sandbox_manager=JobSandboxManager(tmp_path),
        cancellation_event=cancel,
        ones_bridge_factory=factory,
    )
    client.sdk_loader = lambda: sdk
    request = AgentRunRequest(
        job_id="job-bridge", user_id="user", project_code="test", context=context
    )
    if ending == "success":
        assert client.run(request).final_answer == "已读取1000条"
    else:
        with pytest.raises(AppError):
            client.run(request)
    assert not Path(captured["cwd"]).exists()
    assert captured["bridge"].session is None


@pytest.mark.parametrize(
    "count,limit",
    [
        (0, 1000),
        (199, 1000),
        (200, 1000),
        (201, 1000),
        (999, 1000),
        (1000, 1000),
        (1001, 1000),
        (1100, 953),
    ],
)
def test_service_collects_pages_with_exact_internal_cursors(count, limit):
    fixture = _fixture(capabilities=("ones_search_projects",))
    service = fixture["project_search_service"]
    pages = [
        _normalized_project_page(
            start=start + 1,
            count=min(200, count - start, limit - start),
            total=count,
            truncated=start + min(200, count - start, limit - start) < count,
            provider_cursor=f"opaque-{start + min(200, count - start, limit - start)}",
        )
        for start in range(0, min(count, limit), 200)
    ]
    if not pages:
        pages = [
            _normalized_project_page(start=1, count=0, total=0, truncated=False, provider_cursor="")
        ]
    graphql = _PagingGraphql(pages)
    service.graphql = graphql
    output = service.invoke(
        claims=service.authenticate(fixture["token"]),
        arguments={"keyword": "", "limit": limit},
        correlation_id="auto-pages",
        invocation_id="",
    )
    assert output["returned"] == min(count, limit)
    assert output["truncated"] is (count > limit)
    assert output["pagination_limit_reached"] is (count > limit)
    assert "cursor" not in output and "next_cursor" not in output
    assert all(call["arguments"]["limit"] <= 200 for call in graphql.calls)
    for index, call in enumerate(graphql.calls):
        assert call["arguments"]["provider_cursor"] == (
            "" if not index else f"opaque-{index * 200}"
        )
    Draft202012Validator(service.output_schema).validate(output)


@pytest.mark.parametrize("field", list(ONES_COLLECTED_LIST_FIELDS.values()))
def test_collector_stops_on_page_info_not_approximate_total(field):
    result = collect_pages(
        lambda args: {field: [{"uuid": "one"}], "total": 101, "truncated": False},
        {"limit": 1000},
        field=field,
    )
    assert result["returned"] == 1 and result["truncated"] is False


@pytest.mark.parametrize(
    "pages,code",
    [
        ([{"uuid": "one"}], "ones_pagination_unstable"),
        ([], "ones_pagination_cursor_missing"),
    ],
)
def test_repeated_or_empty_pages_fail_closed(pages, code):
    def fetch(args):
        return {"items": pages, "total": 500, "truncated": True, "_provider_cursor": "same"}

    with pytest.raises(OnesMcpError) as error:
        collect_pages(fetch, {"limit": 1000}, field="items")
    assert error.value.error_code == code


@pytest.mark.parametrize(
    "change,code",
    [
        ({"unstable": True}, "ones_pagination_unstable"),
        ({"count": 2}, "ones_provider_page_size_invalid"),
        ({"hasNextPage": "false"}, "ones_provider_schema_invalid"),
    ],
)
def test_provider_page_integrity_is_checked(change, code):
    info = {"count": 1, "totalCount": 1, "hasNextPage": False, **change}
    with pytest.raises(OnesMcpError) as error:
        page_items(
            {"data": {"buckets": [{"tasks": [{"uuid": "one"}], "pageInfo": info}]}},
            collection="tasks",
            limit=200,
        )
    assert error.value.error_code == code


def test_all_graphql_tools_default_to_1000_and_reject_model_cursor():
    for name in ONES_COLLECTED_LIST_FIELDS:
        contract = ONES_TOOL_CONTRACTS[name]
        assert "limit" not in contract.input_schema["required"]
        assert contract.input_schema["properties"]["limit"]["maximum"] == 1000
        assert "cursor" not in contract.input_schema["properties"]
        assert "next_cursor" not in contract.output_schema["properties"]
    fixture = _fixture()
    with pytest.raises(OnesMcpError) as error:
        fixture["service"].search(
            claims=fixture["claims"],
            arguments={"keyword": "test", "issue_type": "defect", "cursor": "altered-long-cursor"},
            correlation_id="reject-cursor",
        )
    assert error.value.error_code == "ones_tool_input_invalid"


def _project_result(count=1000):
    return collect_pages(
        lambda args: _normalized_project_page(
            start=args["cumulative_returned"] + 1,
            count=min(args["limit"], count - args["cumulative_returned"]),
            total=count,
            truncated=args["cumulative_returned"] + args["limit"] < count,
            provider_cursor=f"page-{args['cumulative_returned']}",
        ),
        {"limit": 1000},
        field="projects",
    )


def test_bridge_materializes_1000_rows_without_model_copy_and_cleans_job(tmp_path):
    sandbox = JobSandboxManager(tmp_path).create("job-ones")
    payload = _project_result()
    summary = materialize_result(sandbox, "ones_search_projects", payload)
    path = sandbox.path / summary["result_file"]
    assert summary["returned"] == 1000 and summary["complete"] is True
    assert "projects" not in summary and "Project 1000" in path.read_text()
    assert len(json.dumps(summary)) < 1000
    sandbox.authorize_tool("Read", {"file_path": str(path)})
    with pytest.raises(JobSandboxError):
        sandbox.authorize_tool("Write", {"file_path": str(path), "content": "overwrite"})
    other = JobSandboxManager(tmp_path).create("job-other")
    with pytest.raises(JobSandboxError):
        other.authorize_tool("Read", {"file_path": str(path)})
    sandbox.cleanup()
    assert not path.exists()


def test_materialization_budget_failure_leaves_no_partial_file(tmp_path):
    sandbox = JobSandboxManager(tmp_path).create("job-budget")
    for _ in range(sandbox.limits.max_work_output_files):
        materialize_result(sandbox, "ones_search_projects", _project_result(1))
    with pytest.raises(JobSandboxError):
        materialize_result(sandbox, "ones_search_projects", _project_result(1))
    assert len(list((sandbox.path / "work").iterdir())) == sandbox.limits.max_work_output_files
    assert not sandbox._pending


def test_bridge_keeps_remote_error_and_audit_link_and_checks_frozen_schema(tmp_path):
    contract = ONES_TOOL_CONTRACTS["ones_search_projects"]
    remote = types.CallToolResult.model_validate(
        {
            "content": [],
            "isError": True,
            "structuredContent": {
                "error": "ONES 返回了无效业务数据",
                "error_code": "ones_provider_schema_invalid",
            },
            "_meta": {"enterprise-agent/mcp-call-id": "audit-call"},
        }
    )

    class Session:
        async def initialize(self):
            pass

        async def list_tools(self, **kwargs):
            return types.ListToolsResult(
                tools=[
                    types.Tool.model_validate(
                        {"name": contract.identifier, "inputSchema": contract.input_schema}
                    )
                ]
            )

        async def call_tool(self, *args, **kwargs):
            return remote

    bridge = OnesResultBridge(
        sdk=SimpleNamespace(create_sdk_mcp_server=lambda **kw: {"instance": object()}),
        url="http://test.invalid/mcp",
        headers={},
        frozen={contract.identifier: tool_schema_hash(contract.input_schema)},
        sandbox=JobSandboxManager(tmp_path).create("job-error"),
        timeout=5,
        session=Session(),
    )

    async def run():
        await bridge.connect()
        assert await bridge.call_tool(contract.identifier, {"keyword": ""}) is remote
        await bridge.close()

    asyncio.run(run())
    assert not list((bridge.sandbox.path / "work").iterdir())
