"""独立服务入口的真实 MCP 协议/安全审计，全部使用合成库与 Mock 上游。"""

import asyncio
from contextlib import ExitStack
import json
from pathlib import Path
import threading
import time

from fastapi.testclient import TestClient
import pytest

from app.modules.knowledge.application.directory import KnowledgeDirectory
from app.modules.mcp_audit import McpAuditCoordinator
from app.shared.exceptions import AppError
from app.shared.knowledge_tool_contracts import KNOWLEDGE_TOOL_CONTRACTS
from services.knowledge_mcp_server.app import create_app
from services.knowledge_mcp_server.app import KnowledgeSecurityMiddleware
from services.knowledge_mcp_server.auth import KnowledgeMcpAuth
from services.knowledge_mcp_server.execution import BoundedCalls, CallControl
from services.knowledge_mcp_server.tools import KnowledgeMcpTools
from backend.tests.test_knowledge_search import (
    knowledge_contract as knowledge_contract_fixture,
    readable_fixture as readable_fixture_impl,
    bridge_fixture as bridge_fixture_impl,
    search_fixture as search_fixture_impl,
)

knowledge_contract = knowledge_contract_fixture
readable_fixture = readable_fixture_impl
bridge_fixture = bridge_fixture_impl
search_fixture = search_fixture_impl


@pytest.fixture
def mcp_fixture(search_fixture):
    f = search_fixture
    search = f["search"]
    audit = McpAuditCoordinator(f["runtime"].database, max_payload_bytes=16384)
    tools = KnowledgeMcpTools(
        KnowledgeMcpAuth(f["runtime"].database, search.access),
        KnowledgeDirectory(search.access, search.resources, search.audit),
        search,
        audit,
    )
    app = create_app(tools, ready=audit.assert_ready)
    with TestClient(app, base_url="http://knowledge-mcp:9108") as client:
        yield {**f, "mcp": client, "tools": tools, "app": app}


def headers(f):
    job = f["job"]
    return {
        "authorization": "Bearer " + f["knowledge_token"],
        "accept": "application/json, text/event-stream",
        "mcp-protocol-version": "2025-06-18",
        "x-job-id": job.id,
        "x-app-user-id": job.internal_user_id,
        "x-project-code": job.project_code,
        "x-agent-publication-id": job.agent_publication_id,
        "x-application-publication-id": job.business_application_publication_id,
        "x-invocation-id": f"{job.id}.attempt-{job.retry_count}",
        "x-correlation-id": f"job:{job.id}",
    }


def rpc(f, method="tools/call", params=None, **kwargs):
    return f["mcp"].post(
        "/mcp",
        headers=kwargs.pop("headers", headers(f)),
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params
            if params is not None
            else {
                "name": "knowledge_search",
                "arguments": {
                    "knowledge_base_id": f["body"]["knowledge_base_id"],
                    "query": "合成查询绝不记录",
                },
            },
        },
        **kwargs,
    )


def test_initialize_list_call_and_safe_audit(mcp_fixture, caplog):
    f = mcp_fixture
    assert f["mcp"].get("/health").status_code == 200
    initialized = rpc(
        f,
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "synthetic", "version": "1"},
        },
    )
    assert initialized.status_code == 200
    assert initialized.json()["result"]["serverInfo"]["name"] == "Enterprise Knowledge MCP"
    assert "mcp-session-id" not in initialized.headers
    listed = rpc(f, "tools/list", {})
    assert listed.status_code == 200
    catalog = listed.json()["result"]["tools"]
    assert {t["name"] for t in catalog} == set(KNOWLEDGE_TOOL_CONTRACTS)
    for tool in catalog:
        assert tool["inputSchema"] == KNOWLEDGE_TOOL_CONTRACTS[tool["name"]].input_schema
        assert tool["annotations"]["readOnlyHint"] is True
    directory = rpc(f, params={"name": "knowledge_list_bases", "arguments": {}})
    assert not directory.json()["result"]["isError"]
    response = rpc(f)
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    result = response.json()["result"]
    assert not result["isError"] and len(result["structuredContent"]["documents"]) == 1
    audit_id = result["_meta"]["enterprise-agent/mcp-call-id"]
    db = f["runtime"].database
    rows = db.execute("select * from mcp_operation_audit where mcp_call_id=?", (audit_id,))
    assert len(rows) == 1 and rows[0]["status"] == "SUCCEEDED"
    assert json.loads(rows[0]["business_response_json"])["returned"] == 1
    all_audit = json.dumps(rows, default=str, ensure_ascii=False) + json.dumps(
        db.execute("select * from audit_event"), default=str, ensure_ascii=False
    )
    for forbidden in (
        "合成查询绝不记录",
        "合成正文",
        f["knowledge_token"],
        f["service_token"],
        f["mock"].token,
    ):
        assert forbidden not in all_audit + response.text + caplog.text


@pytest.mark.parametrize(
    "kind,status",
    [
        ("missing", 401),
        ("duplicate", 401),
        ("origin", 403),
        ("cookie", 403),
        ("host", 421),
        ("context_duplicate", 400),
    ],
)
def test_header_rejections(mcp_fixture, kind, status):
    f = mcp_fixture
    h = list(headers(f).items())
    if kind == "missing":
        h = [(k, v) for k, v in h if k != "authorization"]
    elif kind == "duplicate":
        h.append(("authorization", "Bearer synthetic"))
    elif kind == "origin":
        h.append(("origin", "http://synthetic.invalid"))
    elif kind == "cookie":
        h.append(("cookie", "synthetic=1"))
    elif kind == "host":
        h.append(("host", "synthetic.invalid"))
    elif kind == "context_duplicate":
        h.append(("x-job-id", "other"))
    assert rpc(f, headers=h).status_code == status
    assert f["calls"] == []


@pytest.mark.parametrize(
    "kind", ["ones_audience", "bad_token", "revoke", "attempt", "correlation", "scope"]
)
def test_current_principal_and_job_required(mcp_fixture, kind):
    f = mcp_fixture
    h = headers(f)
    if kind == "ones_audience":
        h["authorization"] = "Bearer " + f["token"]
    elif kind == "bad_token":
        h["authorization"] = "Bearer synthetic-not-a-jwt"
    elif kind == "revoke":
        f["runtime"].database.execute("delete from rbac_role_application_knowledge_base")
    elif kind == "attempt":
        h["x-invocation-id"] = f["job"].id + ".attempt-99"
    elif kind == "correlation":
        h["x-correlation-id"] = "other"
    else:
        h["x-application-publication-id"] = "other"
    response = rpc(f, headers=h)
    assert response.json()["result"]["isError"]
    if kind in {"ones_audience", "bad_token"}:
        assert response.json()["result"]["structuredContent"]["error_code"] == (
            "knowledge_mcp_authentication_failed"
        )
    assert f["calls"] == []


@pytest.mark.parametrize(
    "kind", ["unknown_tool", "unknown_argument", "empty_query", "late_text", "exception", "audit"]
)
def test_tool_errors_never_echo_input_or_dependency_data(mcp_fixture, monkeypatch, kind):
    f = mcp_fixture
    params = {
        "name": "knowledge_search",
        "arguments": {"knowledge_base_id": f["body"]["knowledge_base_id"], "query": "合成敏感输入"},
    }
    if kind == "unknown_tool":
        params["name"] = "arbitrary"
    elif kind == "unknown_argument":
        params["arguments"]["team_id"] = "合成敏感输入"
    elif kind == "empty_query":
        params["arguments"]["query"] = " "
    elif kind == "late_text":
        monkeypatch.setattr(f["tools"].search, "search", lambda **kw: {"raw_text": "合成敏感输入"})
    else:

        def fail(*a, **kw):
            raise RuntimeError("合成敏感输入")

        if kind == "audit":
            monkeypatch.setattr(f["tools"].audit, "begin", fail)
        else:
            monkeypatch.setattr(f["tools"].search, "search", fail)
    response = rpc(f, params=params)
    assert response.json()["result"]["isError"]
    assert "合成敏感输入" not in response.text
    rows = f["runtime"].database.execute(
        "select * from mcp_operation_audit where server_code='knowledge-mcp'"
    )
    assert "合成敏感输入" not in json.dumps(rows, ensure_ascii=False)
    if kind not in {"audit", "unknown_tool"}:
        assert rows[-1]["status"] == "FAILED"


@pytest.mark.parametrize(
    "body",
    [
        b'{"jsonrpc":"2.0","id":1,"id":2,"method":"tools/list"}',
        b"x" * (32768 + 1),
        b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":12,"arguments":{"query":"synthetic-sensitive"}}}',
    ],
)
def test_malformed_requests_are_sanitized(mcp_fixture, body):
    response = mcp_fixture["mcp"].post(
        "/mcp", content=body, headers={**headers(mcp_fixture), "content-type": "application/json"}
    )
    assert response.status_code in {400, 413}
    assert "synthetic-sensitive" not in response.text


def test_capacity_is_not_released_until_timed_out_worker_stops():
    async def run():
        calls, entered, release = BoundedCalls(), [], threading.Event()

        def blocked():
            entered.append(True)
            release.wait(3)

        try:
            tasks = [
                asyncio.create_task(calls.run(blocked, CallControl(seconds=0.15))) for _ in range(4)
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            assert len(entered) == 4
            assert all(isinstance(result, AppError) for result in results)
            with pytest.raises(AppError) as error:
                await calls.run(lambda: None, CallControl())
            assert error.value.error_code == "knowledge_mcp_busy"
        finally:
            release.set()
            calls.close()

    asyncio.run(run())


def test_official_sdk_initialize_discover_and_search(mcp_fixture):
    import httpx2
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    f = mcp_fixture

    async def run():
        app = create_app(f["tools"], ready=lambda: None)
        async with app.app.router.lifespan_context(app.app):
            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app), headers=headers(f), trust_env=False
            ) as client:
                async with streamable_http_client(
                    "http://knowledge-mcp:9108/mcp", http_client=client
                ) as streams:
                    async with ClientSession(*streams, read_timeout_seconds=5) as session:
                        initialized = await session.initialize()
                        assert initialized.server_info.name == "Enterprise Knowledge MCP"
                        listed = await session.list_tools()
                        assert {tool.name for tool in listed.tools} == set(KNOWLEDGE_TOOL_CONTRACTS)
                        result = await session.call_tool(
                            "knowledge_search",
                            {
                                "knowledge_base_id": f["body"]["knowledge_base_id"],
                                "query": "合成查询",
                            },
                        )
                        assert not result.is_error
                        assert len(result.structured_content["documents"]) == 1

    asyncio.run(run())


@pytest.mark.parametrize("readable_fixture", [51], indirect=True)
def test_directory_cursor_through_mcp(mcp_fixture):
    f = mcp_fixture
    first = rpc(f, params={"name": "knowledge_list_bases", "arguments": {}}).json()["result"]
    assert not first["isError"]
    page = first["structuredContent"]
    assert len(page["items"]) == 50 and page["has_more"]
    second = rpc(
        f,
        params={"name": "knowledge_list_bases", "arguments": {"cursor": page["next_cursor"]}},
    ).json()["result"]["structuredContent"]
    assert len(second["items"]) == 1 and not second["has_more"] and second["next_cursor"] is None
    assert len({item["knowledge_base_id"] for item in page["items"] + second["items"]}) == 51
    audits = f["runtime"].database.execute("select business_request_json from mcp_operation_audit")
    assert page["next_cursor"] not in json.dumps(audits)


@pytest.mark.parametrize("late", [False, True])
def test_http_deadline_discards_late_search(mcp_fixture, monkeypatch, late):
    from app.modules.knowledge.application.retrieval_budget import DEADLINE_HEADER

    f = mcp_fixture
    h = headers(f)
    h[DEADLINE_HEADER] = str(int(time.time() * 1000) + (200 if late else -1000))
    finished = threading.Event()
    if late:

        def slow_search(**kwargs):
            time.sleep(0.3)
            finished.set()
            return {"raw_text": "合成迟到正文"}

        monkeypatch.setattr(f["tools"].search, "search", slow_search)
    response = rpc(f, headers=h)
    if late:
        result = response.json()["result"]
        assert result["isError"]
        assert result["structuredContent"]["error_code"] == "knowledge_search_budget_exhausted"
        assert finished.wait(2)
    else:
        assert response.status_code == 408
    assert "合成迟到正文" not in response.text
    assert not f["calls"]


def test_nested_budget_observes_mcp_cancellation(mcp_fixture):
    from app.modules.knowledge.application.retrieval_budget import current_budget

    f = mcp_fixture
    control = CallControl()
    with pytest.raises(AppError) as error:
        with f["tools"].auth.budget(f["job"].id, control).activate():
            with f["tools"].search.access.budget(f["job"].id).activate():
                control.cancelled.set()
                current_budget().check()
    assert error.value.error_code == "knowledge_mcp_cancelled"
    assert current_budget() is None


def test_http_disconnect_cancels_dispatch_and_preserves_control():
    async def run():
        messages = asyncio.Queue()
        entered = asyncio.Event()
        controls, stopped = [], []

        async def app(scope, receive, send):
            controls.append(scope["state"]["control"])
            await receive()
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.append(True)

        async def send(message):
            raise AssertionError("断开后不能发送结果")

        h = {
            "host": "knowledge-mcp:9108",
            "authorization": "Bearer synthetic",
            "content-type": "application/json",
            **{
                name: "synthetic"
                for name in (
                    "x-job-id",
                    "x-app-user-id",
                    "x-project-code",
                    "x-invocation-id",
                    "x-correlation-id",
                    "x-agent-publication-id",
                    "x-application-publication-id",
                )
            },
        }
        scope = {
            "type": "http",
            "path": "/mcp",
            "method": "POST",
            "query_string": b"",
            "headers": [(k.encode(), v.encode()) for k, v in h.items()],
        }
        await messages.put(
            {"type": "http.request", "body": b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}'}
        )
        middleware = KnowledgeSecurityMiddleware(app, ("knowledge-mcp:9108",))
        task = asyncio.create_task(middleware(scope, messages.get, send))
        await asyncio.wait_for(entered.wait(), 1)
        await messages.put({"type": "http.disconnect"})
        await asyncio.wait_for(task, 1)
        assert stopped == [True] and controls[0].cancelled.is_set()

    asyncio.run(run())


def test_bootstrap_has_no_platform_container_or_credential_loading(search_fixture):
    from services.knowledge_mcp_server.bootstrap import build_tools
    from app.modules.identity.application.principal_jwt import PrincipalJwks

    f = search_fixture
    with ExitStack() as cleanup:
        service = build_tools(
            f["runtime"].database,
            PrincipalJwks.from_dict(f["key"].public_jwks()),
            bootstrap_file="/synthetic/not-read",
            cleanup=cleanup,
        )
        assert service.auth.access.verifier.expected_audience == "knowledge-mcp"
    source = Path("services/knowledge_mcp_server/bootstrap.py").read_text()
    for forbidden in (
        "from app.bootstrap",
        "import load_settings",
        "PrincipalSigningKey(",
        "ExternalIdentityCredentialRepository(",
    ):
        assert forbidden not in source
