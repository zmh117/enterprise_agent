"""Safe knowledge failures through the real SDK bridge and durable event projection."""

import asyncio
import json
from types import SimpleNamespace

import httpx
from mcp import ClientSession
from mcp.client._memory import InMemoryTransport
import pytest

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.python_runtime.sdk_event_normalizer import extract_tool_events
from app.python_runtime.tool_policy import normalize_tool_events
from app.shared.knowledge_tool_errors import error_payload, input_issues, knowledge_failure
from backend.tests.support.runtime import test_settings as build_settings
from backend.tests.test_knowledge_runtime_dispatch import Remote, bridge


def save_args():
    return {
        "environment": "test",
        "knowledge_base_id": "kb-synthetic",
        "analysis_id": "analysis",
        "request_key": "save-1",
        "question": "合成问题",
        "result": {
            "title": "合成规则",
            "answer": "已核验的有限结论",
            "conditions": {},
            "claims": [
                {
                    "claim_id": "rule",
                    "conclusion": "合成规则",
                    "conditions": {},
                    "evidence_ids": ["read-1"],
                }
            ],
            "coverage": {},
            "unknowns": [],
            "support_status": "supported",
        },
    }


def test_sdk_invalid_save_has_field_hint_and_does_not_close_source_reads():
    async def run():
        remote = Remote()
        calls = []

        async def before(name, args):
            calls.append(name)

        async def after(name, result):
            return result

        client = bridge(remote, source_guard=SimpleNamespace(before_mcp=before, after_mcp=after))
        try:
            await client.connect()
            async with InMemoryTransport(client.server["instance"]) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    args = save_args()
                    args["result"]["claims"][0]["evidence_ids"] = "private-value-not-an-array"
                    result = await session.call_tool("knowledge_save_code_answer", args)
                    assert result.is_error
                    assert result.structured_content["error_code"] == "knowledge_input_invalid"
                    assert result.structured_content["input_issues"] == [
                        {"path": "result/claims/0/evidence_ids", "rule": "type"}
                    ]
                    assert "private-value" not in result.model_dump_json()
                    assert not calls and not remote.calls
                    result = await session.call_tool("knowledge_save_code_answer", save_args())
                    assert not result.is_error and calls == ["knowledge_save_code_answer"]
        finally:
            await client.close()

    asyncio.run(run())


@pytest.mark.parametrize("where", ["source_guard", "remote"])
def test_save_failure_preserves_known_code_without_private_text(where):
    async def run():
        remote = Remote()
        client = bridge(remote)

        async def before(name, args):
            raise CodeKnowledgeError("CODE_SAVE_GRANT_INVALID")

        if where == "source_guard":
            client.source_guard = SimpleNamespace(before_mcp=before)
        else:

            async def failed(request):
                rpc = json.loads(request.content)
                return httpx.Response(
                    200,
                    json={
                        "jsonrpc": "2.0",
                        "id": rpc["id"],
                        "result": {
                            "isError": True,
                            "content": [],
                            "structuredContent": {
                                "error_code": "CODE_SAVE_GRANT_INVALID",
                                "error": "private-value",
                            },
                            "_meta": {"enterprise-agent/mcp-call-id": "real-audit-id"},
                        },
                    },
                )

            await client._client.aclose()
            client._client = httpx.AsyncClient(transport=httpx.MockTransport(failed))
        try:
            result = await client.call_tool("knowledge_save_code_answer", save_args())
            assert (
                result.is_error
                and result.structured_content["error_code"] == "CODE_SAVE_GRANT_INVALID"
            )
            assert "private-value" not in result.model_dump_json()
            assert bool(result.meta) is (where == "remote")
        finally:
            await client.close()

    asyncio.run(run())


@pytest.mark.parametrize("response", ["json", "blocks", "object"])
def test_sdk_failure_is_classified_without_persisting_payload(response):
    name = "mcp__knowledge_mcp__knowledge_save_code_answer"
    payload = {
        "error_code": "CODE_QUESTION_MISMATCH",
        "error": "private-business-body",
        "token": "private-secret",
    }
    wire = payload if response == "object" else json.dumps(payload)
    if response == "blocks":
        wire = [{"type": "text", "text": wire}]
    calls = {"call-1": {"tool_name": name, "request_payload": {}}}
    events = extract_tool_events(
        {
            "type": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "call-1", "is_error": True, "content": wire}
            ],
        },
        build_settings().execution,
        calls,
    )
    request = {
        "protocol_version": "1.5",
        "mcp_servers": [
            {"server_code": "knowledge-mcp", "tools": [{"tool_name": "knowledge_save_code_answer"}]}
        ],
    }
    result = normalize_tool_events(events, request)[0]
    assert result["tool_origin"] == "mcp"
    assert result["failure"] == knowledge_failure("CODE_QUESTION_MISMATCH")
    assert result["failure"]["retry_class"] == "NEVER"
    assert "private-" not in json.dumps(events + [result])


def test_invalid_extra_fields_and_free_form_objects_do_not_disclose_keys_or_values():
    args = save_args()
    args["result"]["private-key-secret"] = "private-value"
    args["result"]["claims"][0].pop("conditions")
    issues = input_issues("knowledge_save_code_answer", args)
    assert "private-" not in json.dumps(issues)
    assert {"path": "result", "rule": "additionalProperties"} in issues
    assert {"path": "result/claims/0/conditions", "rule": "required"} in issues
    result = error_payload(
        "knowledge_save_code_answer",
        {
            "error_code": "knowledge_input_invalid",
            "input_issues": [{"path": "result/conditions/private-key-secret", "rule": "type"}],
            "error": "private-value",
        },
    )
    assert "input_issues" not in result and "private-" not in json.dumps(result)
    assert (
        error_payload("", {"error_code": "private-code"})["error_code"] == "knowledge_tool_failed"
    )


def test_safe_parameter_hints_survive_durable_projection():
    request = {
        "protocol_version": "1.5",
        "mcp_servers": [
            {"server_code": "knowledge-mcp", "tools": [{"tool_name": "knowledge_save_code_answer"}]}
        ],
    }
    event = {
        "tool_call_id": "call-2",
        "tool_name": "mcp__knowledge_mcp__knowledge_save_code_answer",
        "status": "FAILED",
        "error_code": "knowledge_input_invalid",
        "response_summary": {
            "input_issues": [{"path": "request_key", "rule": "required"}],
            "private": "never persist",
        },
    }
    result = normalize_tool_events([event], request)[0]
    assert result["response_summary"]["input_issues"] == [
        {"path": "request_key", "rule": "required"}
    ]
    assert "private" not in json.dumps(result)


def test_cli_argument_rejection_is_diagnosed_without_retaining_input():
    calls = {}
    name = "mcp__knowledge_mcp__knowledge_search"
    events = extract_tool_events(
        {
            "content": [
                {
                    "type": "tool_use",
                    "id": "cli-call",
                    "name": name,
                    "input": {"query": "private-question", "resource_code": None},
                }
            ]
        },
        build_settings().execution,
        calls,
    )
    assert "private-question" not in json.dumps(calls)
    events += extract_tool_events(
        {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "cli-call",
                    "is_error": True,
                    "content": "SDK validation text with private values",
                }
            ]
        },
        build_settings().execution,
        calls,
    )
    request = {
        "protocol_version": "1.5",
        "mcp_servers": [
            {"server_code": "knowledge-mcp", "tools": [{"tool_name": "knowledge_search"}]}
        ],
    }
    result = normalize_tool_events(events, request)[-1]
    assert result["failure"]["code"] == "knowledge_input_invalid"
    assert result["response_summary"]["input_issues"] == [{"path": "resource_code", "rule": "type"}]
    assert "private" not in json.dumps(events + [result])


@pytest.mark.parametrize("failure", [False, True])
def test_idle_bridge_keeps_identity_current_and_stops_on_close(monkeypatch, failure):
    from app.python_runtime import knowledge_mcp_bridge
    from app.shared.knowledge_limits import KNOWLEDGE_CONTINUATION_HEADER

    monkeypatch.setattr(knowledge_mcp_bridge, "KEEPALIVE_INTERVAL_SECONDS", 0.01)

    async def run():
        remote = Remote()
        pinged = asyncio.Event()
        pings = []
        original = remote.handle

        async def handler(request):
            rpc = json.loads(request.content)
            if rpc["method"] != "ping":
                return await original(request)
            assert request.headers["authorization"] == "Bearer " + remote.principal
            pings.append(1)
            pinged.set()
            if failure:
                return httpx.Response(
                    403, json={"error_code": "knowledge_mcp_authentication_failed"}
                )
            remote.principal = "synthetic-fresh-idle-principal"
            return httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": rpc["id"], "result": {}},
                headers={
                    KNOWLEDGE_CONTINUATION_HEADER: remote.principal,
                    "cache-control": "no-store",
                },
            )

        remote.handle = handler
        client = bridge(remote)
        try:
            original_deadline = client.deadline
            await client.connect()
            await asyncio.wait_for(pinged.wait(), 1)
            await asyncio.sleep(0.01)
            result = await client.call_tool("knowledge_save_code_answer", save_args())
            assert result.is_error is failure
            if failure:
                assert (
                    result.structured_content["error_code"] == "knowledge_principal_refresh_failed"
                )
                assert not remote.calls
            else:
                assert remote.calls[-1]["name"] == "knowledge_save_code_answer"
            assert client.deadline == original_deadline
        finally:
            await client.close()
        finished = len(pings)
        await asyncio.sleep(0.03)
        assert len(pings) == finished and client._keepalive_task is None and not client._pending

    asyncio.run(run())


@pytest.mark.parametrize(
    "code", ["CODE_READ_GRANT_EXPIRED", "CODE_EXECUTION_ENDED", "private-error"]
)
def test_source_grant_failure_keeps_only_known_code_through_http(monkeypatch, code):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.modules.knowledge.api.code_runtime_controller import build_code_runtime_router
    from app.modules.knowledge.domain.code_contracts import CODE_SOURCE_GRANT_PATH
    from app.python_runtime.code_analysis import CodeGrantClient

    def denied(binding):
        raise CodeKnowledgeError(code, "private-location")

    app = FastAPI()
    app.state.container = SimpleNamespace(
        code_runtime_verifier=SimpleNamespace(verify=lambda token: None),
        code_source_grant=SimpleNamespace(check_invocation=denied),
    )
    app.include_router(build_code_runtime_router())
    with TestClient(app, base_url="http://api-server:8000") as api:
        response = api.post(
            CODE_SOURCE_GRANT_PATH, json={}, headers={"authorization": "Bearer synthetic"}
        )
    assert response.status_code == 403 and "private" not in response.text
    client_factory = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kw: client_factory(
            transport=httpx.MockTransport(lambda req: httpx.Response(403, json=response.json()))
        ),
    )
    grant = CodeGrantClient(SimpleNamespace(access_token=lambda: "synthetic"))
    expected = code if code != "private-error" else "CODE_SOURCE_GRANT_DENIED"
    with pytest.raises(CodeKnowledgeError, match=expected):
        grant.check({})
