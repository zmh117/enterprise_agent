from __future__ import annotations

import asyncio
import json
import threading
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator
from mcp import types

from app.python_runtime.job_sandbox import JobSandboxError, JobSandboxManager
from app.python_runtime.ones_result_bridge import OnesResultBridge, materialize_result
from app.shared.ones_tool_contracts import ONES_COLLECTED_LIST_FIELDS, ONES_TOOL_CONTRACTS
from app.shared.tool_contract import tool_schema_hash
from app.shared.exceptions import NonRetryableExecutionError
from services.ones_mcp_server.errors import OnesMcpError
from services.ones_mcp_server.provider.graphql.collection import collect_pages
from services.ones_mcp_server.provider.graphql.operations.normalization import page_items
from services.ones_mcp_server.provider.graphql.client import OnesGraphqlClient
from services.ones_mcp_server.provider.graphql.operation import GraphqlOperationRegistry
from services.ones_mcp_server.provider.graphql.operations.business_queries import (
    BUSINESS_GRAPHQL_OPERATIONS,
)
from services.ones_mcp_server.tools import query_services
from services.ones_mcp_server.tools.work_item_search import OnesWorkItemSearchService
from tests.test_ones_mcp_runtime import _fixture, _PagingGraphql, _normalized_project_page


@pytest.mark.parametrize("ending", ["success", "failure", "cancel", "timeout"])
@pytest.mark.parametrize(
    "name,count", [("ones_search_projects", 1000), ("ones_query_test_cases", 10000)]
)
def test_runtime_ones_only_job_reads_result_and_cleans_on_every_exit(tmp_path, ending, name, count):
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
                    "structuredContent": (
                        _project_result()
                        if name == "ones_search_projects"
                        else {
                            "test_cases": [{"uuid": f"CASE-{i}"} for i in range(count)],
                            "total": count,
                            "returned": count,
                            "cumulative_returned": count,
                            "truncated": False,
                            "pagination_limit_reached": False,
                            "untrusted_data": True,
                        }
                    ),
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
        arguments = (
            {"keyword": ""}
            if name == "ones_search_projects"
            else {"source": "plan", "source_uuid": "PLAN"}
        )
        result = await captured["bridge"].call_tool(name, arguments)
        summary = result.model_dump(by_alias=True)["structuredContent"]
        path = Path(options["cwd"]) / summary["result_file"]
        assert summary["returned"] == count
        marker = "Project 1000" if name == "ones_search_projects" else "CASE-9999"
        assert marker in path.read_text()
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
        yield {"type": "result", "result": f"已读取{count}条", "is_error": False}

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
        assert client.run(request).final_answer == f"已读取{count}条"
    else:
        with pytest.raises(AppError):
            client.run(request)
    assert not Path(captured["cwd"]).exists()
    assert captured["bridge"].session is None


@pytest.mark.parametrize(
    "count",
    [
        0,
        199,
        200,
        201,
        256,
        999,
        1000,
        1001,
        1100,
    ],
)
def test_service_collects_pages_with_exact_internal_cursors(count):
    limit = 1000
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
        arguments={"keyword": ""},
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


@pytest.mark.parametrize(
    "service_type,arguments",
    [
        (OnesWorkItemSearchService, {"keyword": "synthetic", "issue_type": "task"}),
        (query_services.OnesProjectSearchService, {"keyword": ""}),
        (query_services.OnesIssueTypeListService, {"project_uuid": "PROJECT"}),
        (query_services.OnesWorkItemQueryService, {}),
        (
            query_services.OnesCustomOptionWorkItemQueryService,
            {"custom_option_filters": [{"field_uuid": "FIELD", "option_uuids": ["OPTION"]}]},
        ),
        (query_services.OnesTestcaseLibraryListService, {}),
        (query_services.OnesTestcaseModuleListService, {"library_uuid": "LIBRARY"}),
        (query_services.OnesTestPlanListService, {}),
        (query_services.OnesTestCaseQueryService, {"source": "plan", "source_uuid": "PLAN"}),
    ],
)
def test_all_nine_service_validators_reject_model_collection_controls(service_type, arguments):
    service = object.__new__(service_type)
    contract = ONES_TOOL_CONTRACTS[service.tool_identifier]
    Draft202012Validator(contract.input_schema).validate(arguments)
    assert "limit" not in service.validate_arguments(arguments)
    for control in (
        {"limit": 50},
        {"limit": 1000},
        {"limit": 10000},
        {"limit": 0},
        {"limit": None},
        {"cursor": "cursor"},
    ):
        assert not Draft202012Validator(contract.input_schema).is_valid({**arguments, **control})
        with pytest.raises(OnesMcpError) as error:
            service.validate_arguments({**arguments, **control})
        assert error.value.error_code == "ones_tool_input_invalid"


@pytest.mark.parametrize("count", [256, 1000, 1001])
def test_work_item_service_continues_50_item_provider_pages(count):
    fixture = _fixture(capabilities=("ones_query_work_items",))
    service = fixture["work_item_query_service"]
    requests = []

    class ShortPageHttp:
        def post_json(self, path, payload, **kwargs):
            variables = payload["variables"]
            requests.append(deepcopy(variables))
            pagination = variables["pagination"]
            start = int(pagination["after"] or 0)
            end = min(start + 50, start + pagination["limit"], count)
            rows = [
                {
                    "uuid": f"SYNTHETIC-{i}",
                    "number": i,
                    "name": "Synthetic",
                    "project": {"uuid": "P"},
                    "issueType": {"uuid": "I"},
                    "status": {"uuid": "S", "name": "New", "category": "to_do"},
                    "sprint": {"uuid": "", "name": ""},
                }
                for i in range(start, end)
            ]
            return {
                "data": {
                    "buckets": [
                        {
                            "tasks": rows,
                            "pageInfo": {
                                "count": len(rows),
                                "totalCount": count,
                                "hasNextPage": end < count,
                                "endCursor": str(end),
                                "unstable": False,
                            },
                        }
                    ]
                }
            }

    service.graphql = OnesGraphqlClient(
        ShortPageHttp(), GraphqlOperationRegistry(BUSINESS_GRAPHQL_OPERATIONS)
    )
    result = service.invoke(
        claims=service.authenticate(fixture["token"]),
        arguments={"keyword": "synthetic", "status_categories": ["to_do"]},
        correlation_id="short-provider-pages",
        invocation_id=f"{fixture['job'].id}.attempt-{fixture['job'].retry_count}",
    )
    assert result["returned"] == min(count, 1000)
    assert result["truncated"] is result["pagination_limit_reached"] is (count > 1000)
    assert len(requests) == (min(count, 1000) + 49) // 50
    assert all(1 <= request["pagination"]["limit"] <= 200 for request in requests)
    for index, request in enumerate(requests):
        assert request["pagination"]["after"] == (str(index * 50) if index else "")
        assert request["filterGroup"] == requests[0]["filterGroup"]
        assert request["orderBy"] == requests[0]["orderBy"]
    Draft202012Validator(service.output_schema).validate(result)


def test_internal_legacy_limit_cannot_lower_server_collection_cap():
    def fetch(arguments):
        start = arguments["cumulative_returned"]
        end = min(start + arguments["limit"], 256)
        return {
            "items": [{"uuid": str(i)} for i in range(start, end)],
            "total": 256,
            "truncated": end < 256,
            "_provider_cursor": str(end),
        }

    result = collect_pages(fetch, {"limit": 50}, field="items")
    assert result["returned"] == 256
    assert result["pagination_limit_reached"] is result["truncated"] is False


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


def test_all_graphql_tools_have_no_model_limit_or_cursor():
    for name in ONES_COLLECTED_LIST_FIELDS:
        contract = ONES_TOOL_CONTRACTS[name]
        assert "limit" not in contract.input_schema["required"]
        assert "limit" not in contract.input_schema["properties"]
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

    # A frozen publication with the former optional limit cannot silently upgrade.
    previous_schema = deepcopy(contract.input_schema)
    previous_schema["properties"]["limit"] = {
        "type": "integer",
        "minimum": 1,
        "maximum": 1000,
        "default": 1000,
    }
    bridge.frozen = {contract.identifier: tool_schema_hash(previous_schema)}
    bridge.session = Session()
    with pytest.raises(NonRetryableExecutionError) as error:
        asyncio.run(bridge.connect())
    assert error.value.error_code == "runtime_ones_tool_contract_invalid"
    assert bridge.session is None
