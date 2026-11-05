"""当前 Job 的固定知识工具派发；排队不占用远端检索预算。"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
import json
import threading
import time
from typing import Any, TypeVar
from uuid import uuid4

import httpx
from jsonschema import Draft202012Validator
from mcp import types
from mcp.server import Server

from app.shared.bounded_read_http import quiet_read_http
from app.shared.exceptions import NonRetryableExecutionError
from app.shared.knowledge_limits import (
    KNOWLEDGE_CONTINUATION_HEADER,
    KNOWLEDGE_DISPATCH_WAIT_HEADER,
    MAX_RETRIEVAL_SECONDS,
)
from app.shared.knowledge_tool_contracts import KNOWLEDGE_TOOL_CONTRACTS
from app.shared.principal_token_contract import MAX_PRINCIPAL_TOKEN_BYTES
from app.shared.tool_contract import tool_schema_hash
from app.python_runtime.file_mcp_bridge import call_tool_result, safe_meta

T = TypeVar("T")


class _Stopped(Exception):
    def __init__(self, code: str):
        self.code = code


def _error(code: str) -> types.CallToolResult:
    payload = {"error_code": code, "error": "知识工具调用未完成，请根据错误码处理"}
    return call_tool_result(
        content=[types.TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))],
        structured_content=payload,
        is_error=True,
    )


class KnowledgeMcpBridge:
    def __init__(
        self,
        *,
        sdk: Any,
        url: str,
        headers: dict[str, str],
        frozen: dict[str, str],
        timeout: float,
        cancellation_event: threading.Event | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.url, self.headers, self.frozen = (
            url,
            {key.lower(): value for key, value in headers.items()},
            dict(frozen),
        )
        self.deadline = time.monotonic() + timeout
        self.cancellation_event = cancellation_event
        self._closed = False
        self._lock = asyncio.Lock()
        self._pending: set[asyncio.Task[Any]] = set()
        self._client = httpx.AsyncClient(
            transport=transport, trust_env=False, follow_redirects=False
        )
        self.server = self._build_server(sdk)
        # SDK/CLI 等待本地派发可跨过单次检索上限；真正的 HTTP 仍最多 360 秒。
        self.server["timeout"] = max(1, int(timeout * 1000))

    def _check(self) -> None:
        if self._closed or self.cancellation_event is not None and self.cancellation_event.is_set():
            raise _Stopped("runtime_cancelled")
        if time.monotonic() >= self.deadline:
            raise _Stopped("runtime_timeout")

    async def _bounded(self, work: Coroutine[Any, Any, T]) -> T:
        task = asyncio.create_task(work)
        self._pending.add(task)

        async def watch() -> None:
            while True:
                self._check()
                await asyncio.sleep(min(0.05, max(0, self.deadline - time.monotonic())))

        watcher = asyncio.create_task(watch())
        try:
            done, _ = await asyncio.wait({task, watcher}, return_when=asyncio.FIRST_COMPLETED)
            if watcher in done:
                await watcher
            self._check()
            return await task
        finally:
            task.cancel()
            watcher.cancel()
            await asyncio.gather(task, watcher, return_exceptions=True)
            self._pending.discard(task)

    async def _rpc(
        self, method: str, params: dict[str, Any], *, wait_ms: int = 0
    ) -> dict[str, Any]:
        self._check()
        request_id = uuid4().hex
        remaining = self.deadline - time.monotonic()
        headers = {
            **self.headers,
            "Accept": "application/json, text/event-stream",
            "Accept-Encoding": "identity",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": "2025-06-18",
            "X-Knowledge-Deadline-Ms": str(int((time.time() + remaining) * 1000)),
            KNOWLEDGE_DISPATCH_WAIT_HEADER: str(wait_ms),
            KNOWLEDGE_CONTINUATION_HEADER: "1",
        }
        # 静态 JSON/stateless 服务，不接受重定向、SSE 或环境代理。
        with quiet_read_http():
            async with asyncio.timeout(min(MAX_RETRIEVAL_SECONDS, remaining)):
                async with self._client.stream(
                    "POST",
                    self.url,
                    headers=headers,
                    json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
                    timeout=min(MAX_RETRIEVAL_SECONDS, remaining),
                ) as response:
                    if response.headers.get("content-encoding", "identity") != "identity":
                        raise ValueError("Invalid knowledge response encoding")
                    body = bytearray()
                    async for part in response.aiter_bytes():
                        body.extend(part)
                        if len(body) > 600 * 1024:
                            raise ValueError("Knowledge response too large")
                    tokens = response.headers.get_list(KNOWLEDGE_CONTINUATION_HEADER)
                    if tokens:
                        if (
                            len(tokens) != 1
                            or not 0 < len(tokens[0]) <= MAX_PRINCIPAL_TOKEN_BYTES
                            or not tokens[0].isascii()
                            or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in tokens[0])
                            or response.headers.get("cache-control") != "no-store"
                        ):
                            raise ValueError("Invalid knowledge continuation")
                        self.headers["authorization"] = "Bearer " + tokens[0]
                    if response.status_code != 200:
                        return {"transport_error": self._http_error(body)}
                    value = json.loads(body)
                    if (
                        not isinstance(value, dict)
                        or value.get("jsonrpc") != "2.0"
                        or value.get("id") != request_id
                        or not isinstance(value.get("result"), dict)
                    ):
                        raise ValueError("Invalid knowledge RPC response")
                    return dict(value["result"])

    async def connect(self) -> None:
        async def preflight() -> None:
            initialized = await self._rpc(
                "initialize",
                {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "knowledge-runtime", "version": "1"},
                },
            )
            if types.InitializeResult.model_validate(initialized).protocol_version != "2025-06-18":
                raise ValueError("Unsupported knowledge protocol")
            result = types.ListToolsResult.model_validate(await self._rpc("tools/list", {}))
            live = {tool.name: tool_schema_hash(tool.input_schema) for tool in result.tools}
            if result.next_cursor is not None or len(live) != len(result.tools):
                raise ValueError("Invalid knowledge tool directory")
            for name, expected in self.frozen.items():
                if (
                    name not in KNOWLEDGE_TOOL_CONTRACTS
                    or live.get(name) != expected
                    or tool_schema_hash(KNOWLEDGE_TOOL_CONTRACTS[name].input_schema) != expected
                ):
                    raise ValueError("Knowledge frozen schema mismatch")

        try:
            await self._bounded(preflight())
        except BaseException as exc:
            await self.close()
            if not isinstance(exc, Exception):
                raise
            raise NonRetryableExecutionError(
                "Knowledge MCP preflight failed",
                safe_message="知识工具连接或冻结契约校验失败",
                error_code="runtime_knowledge_tool_contract_invalid",
            ) from None

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        if name not in self.frozen or name not in KNOWLEDGE_TOOL_CONTRACTS:
            return _error("knowledge_job_denied")
        if not Draft202012Validator(KNOWLEDGE_TOOL_CONTRACTS[name].input_schema).is_valid(
            arguments
        ):
            return _error("knowledge_input_invalid")
        entered = time.monotonic()

        async def dispatch() -> types.CallToolResult:
            async with self._lock:
                self._check()
                payload = await self._rpc(
                    "tools/call",
                    {"name": name, "arguments": arguments},
                    wait_ms=min(3_600_000, int((time.monotonic() - entered) * 1000)),
                )
                if "transport_error" in payload:
                    return _error(payload["transport_error"])
                result = types.CallToolResult.model_validate(payload)
                return call_tool_result(
                    content=result.content,
                    structured_content=result.structured_content,
                    is_error=result.is_error,
                    meta=safe_meta(result),
                )

        try:
            return await self._bounded(dispatch())
        except _Stopped as exc:
            return _error(exc.code)
        except (TimeoutError, httpx.TimeoutException):
            return _error("knowledge_search_budget_exhausted")
        except Exception:
            return _error("knowledge_mcp_unavailable")

    @staticmethod
    def _http_error(body: bytearray) -> str:
        try:
            value = json.loads(body)
        except (ValueError, TypeError):
            return "knowledge_mcp_unavailable"
        code = value.get("error_code") if isinstance(value, dict) else None
        allowed = {
            "knowledge_mcp_unavailable",
            "knowledge_mcp_authentication_failed",
            "knowledge_mcp_context_invalid",
            "knowledge_mcp_input_invalid",
            "knowledge_mcp_busy",
            "knowledge_search_budget_exhausted",
        }
        return code if isinstance(code, str) and code in allowed else "knowledge_mcp_unavailable"

    def _build_server(self, sdk: Any) -> Any:
        def visible() -> list[types.Tool]:
            return [
                types.Tool.model_validate(
                    {
                        "name": name,
                        "description": KNOWLEDGE_TOOL_CONTRACTS[name].description,
                        "inputSchema": KNOWLEDGE_TOOL_CONTRACTS[name].input_schema,
                    }
                )
                for name in sorted(self.frozen)
                if name in KNOWLEDGE_TOOL_CONTRACTS
            ]

        config = sdk.create_sdk_mcp_server(
            name="enterprise-knowledge-bridge", version="1.0.0", tools=[]
        )
        instance = config["instance"] if isinstance(config, dict) else config.instance
        if hasattr(instance, "list_tools") and hasattr(instance, "call_tool"):

            @instance.list_tools()  # type: ignore[untyped-decorator]
            async def list_v1() -> list[types.Tool]:
                return visible()

            @instance.call_tool()  # type: ignore[untyped-decorator]
            async def call_v1(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
                return await self.call_tool(name, arguments)

            return config

        async def list_v2(_context: Any, _params: Any) -> types.ListToolsResult:
            return types.ListToolsResult(tools=visible())

        async def call_v2(
            _context: Any, params: types.CallToolRequestParams
        ) -> types.CallToolResult:
            return await self.call_tool(params.name, params.arguments or {})

        return {
            "type": "sdk",
            "name": "enterprise-knowledge-bridge",
            "instance": Server(
                "enterprise-knowledge-bridge",
                version="1.0.0",
                on_list_tools=list_v2,
                on_call_tool=call_v2,
            ),
        }

    async def close(self) -> None:
        self._closed = True
        for task in list(self._pending):
            task.cancel()
        await asyncio.gather(*list(self._pending), return_exceptions=True)
        await self._client.aclose()
        self.headers.clear()
