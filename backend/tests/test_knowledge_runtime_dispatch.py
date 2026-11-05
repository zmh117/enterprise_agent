"""固定知识 bridge 的真实进程内 MCP 协议及合成 HTTP 派发回归。"""

import asyncio
import json
import logging
import threading
import time

import httpx
from mcp import ClientSession
from mcp.client._memory import InMemoryTransport
import pytest

from app.python_runtime.claude_client import load_claude_agent_sdk
from app.python_runtime.knowledge_mcp_bridge import KnowledgeMcpBridge
from app.shared.exceptions import NonRetryableExecutionError
from app.shared.knowledge_limits import (
    KNOWLEDGE_CONTINUATION_HEADER,
    KNOWLEDGE_DISPATCH_WAIT_HEADER,
)
from app.shared.knowledge_tool_contracts import KNOWLEDGE_TOOL_CONTRACTS
from app.shared.tool_contract import tool_schema_hash


class Remote:
    def __init__(self):
        self.started, self.release = asyncio.Event(), asyncio.Event()
        self.calls = []
        self.active = self.peak = 0
        self.block = False
        self.fail_first = False
        self.fail_status = 503
        self.delay = 0.0
        self.principal = "synthetic-original-principal"
        self.mismatch = False

    async def handle(self, request):
        body = json.loads(request.content)
        continuation = {}
        if body["method"] == "initialize":
            value = {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "test", "version": "1"},
            }
        elif body["method"] == "tools/list":
            value = {
                "tools": [
                    {"name": name, "inputSchema": {} if self.mismatch else contract.input_schema}
                    for name, contract in KNOWLEDGE_TOOL_CONTRACTS.items()
                ]
            }
        else:
            assert request.headers["authorization"] == "Bearer " + self.principal
            self.calls.append(
                {
                    "name": body["params"]["name"],
                    "query": body["params"]["arguments"].get("query"),
                    "wait": int(request.headers[KNOWLEDGE_DISPATCH_WAIT_HEADER]),
                    "deadline": int(request.headers["X-Knowledge-Deadline-Ms"]),
                }
            )
            self.active += 1
            self.peak = max(self.peak, self.active)
            try:
                if len(self.calls) == 1:
                    self.started.set()
                    if self.block:
                        await self.release.wait()
                    if self.fail_first:
                        self.principal = "synthetic-continued-principal"
                        return httpx.Response(
                            self.fail_status,
                            json={
                                "error": "synthetic-private-detail",
                                "error_code": "knowledge_search_budget_exhausted"
                                if self.fail_status == 408
                                else "unknown-private-code",
                            },
                            headers={
                                KNOWLEDGE_CONTINUATION_HEADER: self.principal,
                                "cache-control": "no-store",
                            },
                        )
                await asyncio.sleep(self.delay)
                self.principal = "synthetic-continued-principal"
                continuation = {
                    KNOWLEDGE_CONTINUATION_HEADER: self.principal,
                    "cache-control": "no-store",
                }
                value = {
                    "content": [{"type": "text", "text": "synthetic-result"}],
                    "structuredContent": {"ok": True},
                    "isError": False,
                    "_meta": {
                        "enterprise-agent/mcp-call-id": "synthetic-call",
                        "unexpected": "omit",
                    },
                }
            finally:
                self.active -= 1
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": body["id"], "result": value}, headers=continuation
        )


def bridge(remote, **kwargs):
    return KnowledgeMcpBridge(
        sdk=load_claude_agent_sdk(),
        url="http://knowledge-mcp:9108/mcp",
        headers={"Authorization": "Bearer " + remote.principal},
        frozen={
            name: tool_schema_hash(contract.input_schema)
            for name, contract in KNOWLEDGE_TOOL_CONTRACTS.items()
        },
        timeout=kwargs.pop("timeout", 2),
        transport=httpx.MockTransport(remote.handle),
        **kwargs,
    )


def args(query):
    return {"knowledge_base_id": "kb-synthetic", "query": query}


def test_sdk_mcp_parallel_calls_serialize_before_budget_and_continue_principal(monkeypatch, caplog):
    from app.python_runtime import knowledge_mcp_bridge

    # 每次计算 120ms，三次总耗时超过 200ms；等待不能消耗下一次的请求预算。
    monkeypatch.setattr(knowledge_mcp_bridge, "MAX_RETRIEVAL_SECONDS", 0.2)
    caplog.set_level(logging.DEBUG)

    async def run():
        remote = Remote()
        remote.delay = 0.12
        client = bridge(remote)
        try:
            await client.connect()
            async with InMemoryTransport(client.server["instance"]) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    assert {tool.name for tool in (await session.list_tools()).tools} == set(
                        KNOWLEDGE_TOOL_CONTRACTS
                    )
                    results = await asyncio.gather(
                        *(session.call_tool("knowledge_search", args(str(i))) for i in range(3))
                    )
                    assert all(not result.is_error for result in results)
                    assert all(
                        result.meta == {"enterprise-agent/mcp-call-id": "synthetic-call"}
                        for result in results
                    )
                    assert "principal" not in json.dumps([r.model_dump() for r in results])
            assert remote.peak == 1
            assert [c["query"] for c in remote.calls] == ["0", "1", "2"]
            assert remote.calls[2]["wait"] >= 200
            assert (
                max(c["deadline"] for c in remote.calls) - min(c["deadline"] for c in remote.calls)
                <= 5
            )
        finally:
            await client.close()
        assert not client.headers and not client._pending

    asyncio.run(run())
    assert "synthetic-original-principal" not in caplog.text
    assert "synthetic-continued-principal" not in caplog.text


@pytest.mark.parametrize("stop", ["cancel_waiter", "job_cancel", "deadline", "close"])
def test_waiting_search_never_dispatches_after_cancel_or_deadline(stop):
    async def run():
        remote = Remote()
        remote.block = True
        cancellation = threading.Event()
        client = bridge(remote, cancellation_event=cancellation)
        try:
            await client.connect()
            first = asyncio.create_task(client.call_tool("knowledge_search", args("first")))
            await remote.started.wait()
            second = asyncio.create_task(client.call_tool("knowledge_search", args("second")))
            await asyncio.sleep(0.01)
            if stop == "cancel_waiter":
                second.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await second
                remote.release.set()
                assert not (await first).is_error
                assert not (await client.call_tool("knowledge_search", args("third"))).is_error
                assert [c["query"] for c in remote.calls] == ["first", "third"]
            else:
                if stop == "job_cancel":
                    cancellation.set()
                elif stop == "deadline":
                    client.deadline = time.monotonic()
                else:
                    await client.close()
                await asyncio.gather(first, second, return_exceptions=True)
                assert len(remote.calls) == 1 and remote.active == 0
        finally:
            remote.release.set()
            await client.close()
        assert not client._pending

    asyncio.run(run())


@pytest.mark.parametrize("status", [408, 503])
def test_failed_call_releases_dispatch_slot_without_retry(status):
    async def run():
        remote = Remote()
        remote.fail_first = True
        remote.fail_status = status
        client = bridge(remote)
        try:
            await client.connect()
            first, second = await asyncio.gather(
                client.call_tool("knowledge_search", args("first")),
                client.call_tool("knowledge_search", args("second")),
            )
            assert first.is_error and not second.is_error
            assert len(remote.calls) == 2 and remote.peak == 1
            assert "synthetic-private-detail" not in str(first)
            assert first.structured_content["error_code"] == (
                "knowledge_search_budget_exhausted"
                if status == 408
                else "knowledge_mcp_unavailable"
            )
            assert "principal" not in str(first)
        finally:
            await client.close()

    asyncio.run(run())


def test_frozen_contract_and_invalid_arguments_never_dispatch():
    async def run():
        remote = Remote()
        remote.mismatch = True
        client = bridge(remote)
        with pytest.raises(NonRetryableExecutionError, match="Knowledge MCP preflight"):
            await client.connect()
        assert not remote.calls and not client.headers
        remote.mismatch = False
        client = bridge(remote)
        try:
            await client.connect()
            assert (await client.call_tool("unknown", {})).is_error
            assert (
                await client.call_tool(
                    "knowledge_search", {**args("test"), "access_mode": "offline"}
                )
            ).is_error
            assert not remote.calls
        finally:
            await client.close()

    asyncio.run(run())
