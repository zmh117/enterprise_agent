"""Shared transport and atomic publication for Job-local query result files."""

from __future__ import annotations

import hashlib
import json
from contextlib import AsyncExitStack
from typing import Any
from collections.abc import Callable

import httpx
import jsonschema
from mcp import ClientSession, types
from mcp.client import streamable_http as transport
from mcp.server import Server

from app.shared.exceptions import NonRetryableExecutionError
from app.shared.tool_contract import tool_schema_hash

from .file_mcp_bridge import (
    call_tool_result,
    result_is_error,
    result_structured_content,
    safe_meta,
    session_timeout,
)
from .job_sandbox import JobSandbox, JobSandboxError


def _result(
    payload: dict[str, Any], *, error: bool = False, meta: dict[str, Any] | None = None
) -> types.CallToolResult:
    return call_tool_result(
        content=[
            types.TextContent(
                type="text",
                text=json.dumps(payload, ensure_ascii=False),
            )
        ],
        structured_content=payload,
        is_error=error,
        meta=meta,
    )


def publish_result_file(
    sandbox: JobSandbox,
    relative: str,
    body: bytes,
    summary: dict[str, Any],
) -> dict[str, Any]:
    reservation = sandbox.reserve_runtime_artifact(
        relative_path=relative, maximum_size_bytes=len(body)
    )
    try:
        with (sandbox.path / reservation.staging_relative_path).open("xb") as stream:
            stream.write(body)
        digest = hashlib.sha256(body).hexdigest()
        sandbox.publish_runtime_artifact(
            reservation,
            expected_size_bytes=len(body),
            expected_sha256=digest,
            request_digest=digest,
            public_payload=summary,
        )
    except BaseException:
        sandbox.release_runtime_artifact(reservation)
        raise
    return summary


class ResultFileBridge:
    def __init__(
        self,
        *,
        sdk: Any,
        contracts: dict[str, Any],
        result_tools: frozenset[str],
        materializer: Callable[[JobSandbox, str, dict[str, Any]], dict[str, Any]],
        label: str,
        code_prefix: str,
        url: str,
        headers: dict[str, str],
        frozen: dict[str, str],
        sandbox: JobSandbox,
        timeout: float,
        session: Any = None,
    ) -> None:
        self.contracts, self.result_tools = contracts, result_tools
        self.materializer, self.label, self.code_prefix = materializer, label, code_prefix
        self.url, self.headers, self.frozen = url, headers, dict(frozen)
        self.sandbox, self.timeout = sandbox, timeout
        self.session = session
        self.stack: AsyncExitStack | None = None
        self.server = self._build_server(sdk)

    async def connect(self) -> None:
        try:
            if self.session is None:
                self.stack = AsyncExitStack()
                client_module = (
                    getattr(transport, "httpx2", None) or getattr(transport, "httpx", None) or httpx
                )
                client = await self.stack.enter_async_context(
                    client_module.AsyncClient(
                        headers=self.headers,
                        timeout=self.timeout,
                        follow_redirects=False,
                    )
                )
                streams = await self.stack.enter_async_context(
                    transport.streamable_http_client(
                        self.url,
                        http_client=client,
                        terminate_on_close=False,
                    )
                )
                self.session = await self.stack.enter_async_context(
                    ClientSession(
                        streams[0],
                        streams[1],
                        read_timeout_seconds=session_timeout(self.timeout),
                    )
                )
            await self.session.initialize()
            live: dict[str, str] = {}
            cursor = None
            seen: set[str] = set()
            for _ in range(10):
                page = await self.session.list_tools(
                    params=types.PaginatedRequestParams(cursor=cursor) if cursor else None
                )
                for tool in page.tools:
                    schema = getattr(tool, "input_schema", getattr(tool, "inputSchema", None))
                    if tool.name in live or len(live) >= 256:
                        raise ValueError("Invalid query tools/list")
                    live[tool.name] = tool_schema_hash(schema)
                cursor = getattr(page, "next_cursor", getattr(page, "nextCursor", None))
                if not cursor:
                    break
                if cursor in seen or len(cursor) > 4096:
                    raise ValueError("Invalid query tools/list cursor")
                seen.add(cursor)
            else:
                raise ValueError("Query tools/list budget exceeded")
            for name, expected in self.frozen.items():
                if (
                    name not in self.contracts
                    or live.get(name) != expected
                    or tool_schema_hash(self.contracts[name].input_schema) != expected
                ):
                    raise ValueError("Query frozen schema mismatch")
        except BaseException as exc:
            await self.close()
            if not isinstance(exc, Exception):
                raise
            raise NonRetryableExecutionError(
                "Query result bridge preflight failed",
                safe_message=f"{self.label} 工具连接或冻结契约校验失败",
                error_code=f"runtime_{self.code_prefix}_tool_contract_invalid",
            ) from None

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        if name not in self.frozen or self.session is None:
            return _result(
                {
                    "error": f"当前 Job 未授权该 {self.label} 工具",
                    "error_code": f"{self.code_prefix}_tool_not_frozen",
                },
                error=True,
            )
        try:
            remote = await self.session.call_tool(
                name, arguments, read_timeout_seconds=session_timeout(self.timeout)
            )
        except Exception:
            return _result(
                {
                    "error": f"{self.label} 工具请求失败或超时，请重试或缩小查询范围",
                    "error_code": f"{self.code_prefix}_runtime_transport_error",
                },
                error=True,
            )
        if not isinstance(remote, types.CallToolResult):
            return _result(
                {
                    "error": f"{self.label} 工具返回了无效响应",
                    "error_code": f"{self.code_prefix}_result_materialization_failed",
                },
                error=True,
            )
        if result_is_error(remote) or name not in self.result_tools:
            return remote
        meta = safe_meta(remote)
        try:
            payload = result_structured_content(remote)
            if not isinstance(payload, dict):
                raise ValueError("Missing query structured result")
            summary = self.materializer(self.sandbox, name, payload)
            return _result(summary, meta=meta)
        except JobSandboxError as exc:
            return _result(
                {
                    "error": f"{self.label} 查询结果无法写入临时沙盒，请检查文件数量和容量限制",
                    "error_code": exc.code,
                },
                error=True,
                meta=meta,
            )
        except (TypeError, ValueError, OSError, jsonschema.ValidationError):
            return _result(
                {
                    "error": f"{self.label} 查询结果校验或临时文件写入失败",
                    "error_code": f"{self.code_prefix}_result_materialization_failed",
                },
                error=True,
                meta=meta,
            )

    def _build_server(self, sdk: Any) -> Any:
        def visible() -> list[types.Tool]:
            return [
                types.Tool.model_validate(
                    {
                        "name": name,
                        "description": self.contracts[name].description,
                        "inputSchema": self.contracts[name].input_schema,
                    }
                )
                for name in sorted(self.frozen)
                if name in self.contracts
            ]

        config = sdk.create_sdk_mcp_server(
            name=f"enterprise-{self.code_prefix}-bridge", version="0.1.0", tools=[]
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
            "name": f"enterprise-{self.code_prefix}-bridge",
            "instance": Server(
                f"enterprise-{self.code_prefix}-bridge",
                version="0.1.0",
                on_list_tools=list_v2,
                on_call_tool=call_v2,
            ),
        }

    async def close(self) -> None:
        self.session = None
        if self.stack is not None:
            stack, self.stack = self.stack, None
            await stack.aclose()
