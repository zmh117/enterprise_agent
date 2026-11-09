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
from backend.tests.test_knowledge_io_cancellation import held_connection
from app.shared.database import Database
from app.modules.knowledge.application.retrieval_budget import DEADLINE_HEADER
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
        principal_client=f["readability_client"],
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


@pytest.mark.parametrize(
    "code",
    [
        "knowledge_embedding_busy",
        "knowledge_embedding_read_timeout",
        "knowledge_embedding_unavailable",
    ],
)
def test_mcp_keeps_safe_embedding_error_classification(mcp_fixture, monkeypatch, code):
    from app.modules.knowledge.domain.vector_contract import VectorError

    f = mcp_fixture

    def fail():
        raise VectorError(code)

    monkeypatch.setattr(f["search"].embedding, "check", fail)
    response = rpc(f)
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["isError"] and result["structuredContent"]["error_code"] == code
    assert "knowledge_storage_unavailable" not in response.text
    assert "合成查询绝不记录" not in response.text and f["knowledge_token"] not in response.text
    assert not f["hops"] and not f["vector"].qdrant.search_limits
    audit = f["runtime"].database.execute_one(
        "select business_response_json from mcp_operation_audit order by created_at desc limit 1"
    )
    timing = json.loads(audit["business_response_json"])["retrieval_timing"]
    assert timing["stopped_stage"] == "embedding"
    assert timing["stage_ms"]["embedding"] >= 0
    assert timing["rerank"] is None
    assert timing["deadline_source"] in {"call_limit", "job"}


def test_real_mcp_entry_bounds_first_authentication_pool_wait(mcp_fixture, monkeypatch):
    f = mcp_fixture
    blocked = Database("sqlite:///:memory:", pool_max_size=1, pool_timeout_seconds=3)
    original = f["tools"].auth.resolve

    def resolve(*args):
        blocked.execute("select 1")
        return original(*args)

    monkeypatch.setattr(f["tools"].auth, "resolve", resolve)
    try:
        with held_connection(blocked):
            started = time.monotonic()
            response = rpc(
                f, headers={**headers(f), DEADLINE_HEADER: str(int(time.time() * 1000) + 100)}
            )
            assert time.monotonic() - started < 0.8
            assert response.json()["result"]["isError"]
            assert (
                response.json()["result"]["structuredContent"]["error_code"]
                == "knowledge_search_budget_exhausted"
            )
        assert not rpc(f).json()["result"]["isError"]
    finally:
        blocked.close()


@pytest.mark.parametrize("mode", ["online", "offline"])
def test_initialize_list_call_and_safe_audit(mcp_fixture, caplog, mode):
    from app.modules.knowledge.domain.models import KnowledgeAccessMode

    f = mcp_fixture
    f["search"].access_mode = KnowledgeAccessMode(mode)
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
        assert (
            tool["annotations"]["readOnlyHint"] is KNOWLEDGE_TOOL_CONTRACTS[tool["name"]].read_only
        )
    directory = rpc(f, params={"name": "knowledge_list_bases", "arguments": {}})
    assert not directory.json()["result"]["isError"]
    response = rpc(f)
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert "X-Knowledge-Principal-Continuation" not in response.headers
    result = response.json()["result"]
    assert not result["isError"] and len(result["structuredContent"]["documents"]) == 1
    audit_id = result["_meta"]["enterprise-agent/mcp-call-id"]
    db = f["runtime"].database
    rows = db.execute("select * from mcp_operation_audit where mcp_call_id=?", (audit_id,))
    assert len(rows) == 1 and rows[0]["status"] == "SUCCEEDED"
    assert json.loads(rows[0]["business_response_json"])["returned"] == 1
    timing = json.loads(rows[0]["business_response_json"])["retrieval_timing"]
    assert {"access_check", "embedding", "vector_search", "rerank", "response"} <= set(
        timing["stage_ms"]
    )
    assert ("readability" in timing["stage_ms"]) == (mode == "online")
    assert 0 < timing["budget_after_auth_ms"] <= timing["entry_budget_ms"] <= 360000
    assert timing["stopped_stage"] is None and len(timing["request_id"]) == 32
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


def test_runtime_bridge_real_mcp_serializes_and_audits_wait(mcp_fixture, monkeypatch):
    import httpx
    from mcp import ClientSession
    from mcp.client._memory import InMemoryTransport
    from app.python_runtime.claude_client import load_claude_agent_sdk
    from app.python_runtime.knowledge_mcp_bridge import KnowledgeMcpBridge
    from app.shared.tool_contract import tool_schema_hash

    f = mcp_fixture
    original = f["search"].reranker.rank

    def slow_rank(*args):
        time.sleep(0.03)
        return original(*args)

    monkeypatch.setattr(f["search"].reranker, "rank", slow_rank)

    async def run():
        app = create_app(f["tools"], ready=lambda: None)
        async with app.app.router.lifespan_context(app.app):
            bridge = KnowledgeMcpBridge(
                sdk=load_claude_agent_sdk(),
                url="http://knowledge-mcp:9108/mcp",
                headers=headers(f),
                frozen={
                    name: tool_schema_hash(contract.input_schema)
                    for name, contract in KNOWLEDGE_TOOL_CONTRACTS.items()
                },
                timeout=10,
                transport=httpx.ASGITransport(app=app),
            )
            try:
                await bridge.connect()
                async with InMemoryTransport(bridge.server["instance"]) as streams:
                    async with ClientSession(*streams) as session:
                        await session.initialize()
                        results = await asyncio.gather(
                            *(
                                session.call_tool(
                                    "knowledge_search",
                                    {
                                        "knowledge_base_id": f["body"]["knowledge_base_id"],
                                        "query": "合成并行查询",
                                    },
                                )
                                for _ in range(3)
                            )
                        )
                        assert [
                            r.structured_content.get("error_code") for r in results if r.is_error
                        ] == []
                        assert all(
                            not r.is_error and len(r.structured_content["documents"]) == 1
                            for r in results
                        )
            finally:
                await bridge.close()
        rows = f["runtime"].database.execute(
            "select business_response_json from mcp_operation_audit where status='SUCCEEDED' order by created_at"
        )
        timings = [json.loads(row["business_response_json"])["retrieval_timing"] for row in rows]
        assert len(timings) == 3
        assert timings[2]["dispatch_wait_ms"] >= 50
        assert all(t["deadline_source"] == "upstream" for t in timings)
        assert len({t["request_id"] for t in timings}) == 3

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


def test_rerank_deadline_failure_keeps_stage_audit_without_inventing_remote_time(
    mcp_fixture, monkeypatch
):
    from app.shared.io_deadline import current_io_deadline

    f = mcp_fixture

    def blocked_rank(*_):
        while True:
            time.sleep(0.01)
            current_io_deadline().check()

    monkeypatch.setattr(f["search"].reranker, "rank", blocked_rank)
    response = rpc(f, headers={**headers(f), DEADLINE_HEADER: str(int(time.time() * 1000) + 1000)})
    assert (
        response.json()["result"]["structuredContent"]["error_code"]
        == "knowledge_search_budget_exhausted"
    )
    until = time.monotonic() + 2
    while True:
        row = f["runtime"].database.execute_one(
            "select status,business_response_json from mcp_operation_audit order by created_at desc limit 1"
        )
        if row and row["status"] == "FAILED" or time.monotonic() >= until:
            break
        time.sleep(0.01)
    assert row["status"] == "FAILED"
    timing = json.loads(row["business_response_json"])["retrieval_timing"]
    assert timing["stopped_stage"] == "rerank" and timing["deadline_source"] == "upstream"
    assert 0 < timing["stage_ms"]["rerank"] <= timing["elapsed_ms"]
    assert timing["entry_budget_ms"] <= 1000 and timing["rerank"] is None


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
        assert service.search.embedding.http.endpoint == "http://knowledge-embedding-online:8096"
    source = Path("services/knowledge_mcp_server/bootstrap.py").read_text()
    for forbidden in (
        "from app.bootstrap",
        "import load_settings",
        "PrincipalSigningKey(",
        "ExternalIdentityCredentialRepository(",
    ):
        assert forbidden not in source


def test_code_search_receipt_is_host_bound_and_never_in_model_output(mcp_fixture, monkeypatch):
    from dataclasses import replace
    from app.modules.knowledge.domain.code_answers import code_authorization_hash
    from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
    from app.modules.knowledge.infrastructure.code_search_receipts import CodeSearchReceipts

    f = mcp_fixture
    access = f["search"].access.authenticate(f["knowledge_token"], "knowledge_search")
    pin = f["search"].resources.resolve(f["body"]["knowledge_base_id"])

    def code_search(*, token, arguments, search_id):
        return dict(
            source_kind="code",
            knowledge_base_id=pin.knowledge_base_id,
            resource_revision_id=pin.revision_id,
            index_id=pin.index_id,
            search_id=search_id,
            source_id=pin.source_id,
            checkout_id="synthetic-checkout",
            requested_revision=100,
            matched_revision=None,
            match_kind="exact",
            requires_verification=False,
            documents=[],
            content_scope="matched_chunks_with_conditions",
            access_mode="source_permissions",
            ranking_method="cross_encoder",
            ranking_profile_hash="f" * 64,
            partial=False,
            partial_reason=None,
            _code_receipt=dict(
                contract="code-search-receipt/v1",
                search_id=search_id,
                knowledge_base_id=pin.knowledge_base_id,
                resource_revision_id=pin.revision_id,
                resource_fingerprint=pin.fingerprint,
                source_id=pin.source_id,
                index_id=pin.index_id,
                authorization_hash=code_authorization_hash(access),
                question_hash="a" * 64,
                requested_revision=100,
                matches=[],
                version_mode="exact",
            ),
        )

    monkeypatch.setattr(f["search"], "search", code_search)
    result = rpc(f).json()["result"]
    assert not result["isError"]
    content = result["structuredContent"]
    assert "_code_receipt" not in json.dumps(result)
    receipts = CodeSearchReceipts(f["runtime"].database)
    receipt = receipts.read(content["search_id"], access=access, pin=pin)
    assert receipt["requested_revision"] == 100 and receipt["matches"] == []
    with pytest.raises(CodeKnowledgeError, match="CODE_SEARCH_CONTEXT_CHANGED"):
        receipts.read(
            content["search_id"],
            access=replace(access, current_authorization_hash="z" * 64),
            pin=pin,
        )
    f["runtime"].database.execute(
        "UPDATE mcp_operation_audit SET response_truncated=1 WHERE id=?", (content["search_id"],)
    )
    with pytest.raises(CodeKnowledgeError, match="CODE_SUCCESSFUL_SEARCH_REQUIRED"):
        receipts.read(content["search_id"], access=access, pin=pin)


def test_rejected_code_response_cannot_create_successful_receipt(mcp_fixture, monkeypatch):
    f = mcp_fixture
    monkeypatch.setattr(
        f["search"],
        "search",
        lambda **kw: {
            "_code_receipt": {"search_id": kw["search_id"]},
            "invalid": True,
        },
    )
    result = rpc(f).json()["result"]
    assert result["isError"]
    rows = f["runtime"].database.execute(
        "SELECT status,business_response_json FROM mcp_operation_audit WHERE parent_audit_id IS NULL"
    )
    assert rows and all(row["status"] != "SUCCEEDED" for row in rows)
    assert all("code_search" not in row["business_response_json"] for row in rows)
