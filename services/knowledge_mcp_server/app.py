"""Knowledge Streamable HTTP 入口；与其他 MCP 同级，业务用例不在这里实现。"""

import asyncio
from collections.abc import Callable
from contextlib import asynccontextmanager
import json
import logging
from typing import Any

from mcp import types
from mcp.server import Server, ServerRequestContext
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import TypeAdapter
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.modules.knowledge.domain.governance import strict_object
from app.modules.knowledge.application.retrieval_budget import (
    DEADLINE_HEADER,
    deadline_from_headers,
)
from app.modules.mcp_audit import McpAuditHandle
from app.shared.knowledge_tool_contracts import (
    KNOWLEDGE_TOOL_CONTRACTS,
    KNOWLEDGE_USAGE_INSTRUCTIONS,
)
from app.shared.mcp_server_policy import KNOWLEDGE_MCP_SERVER_CODE
from services.knowledge_mcp_server.errors import failure, safe_failure
from services.knowledge_mcp_server.execution import BoundedCalls, CallControl
from services.knowledge_mcp_server.tools import KnowledgeMcpTools

MAX_REQUEST_BYTES = 32 * 1024
SERVER_VERSION = "1.0.0"


def _request(context: ServerRequestContext) -> Request:
    if not isinstance(context.request, Request):
        raise failure("knowledge_mcp_context_invalid")
    return context.request


def _result(
    payload: dict[str, Any], *, error: bool = False, meta: dict[str, str] | None = None
) -> types.CallToolResult:
    return types.CallToolResult(
        content=[
            types.TextContent(
                type="text", text=json.dumps(payload, ensure_ascii=False, allow_nan=False)
            )
        ],
        structured_content=payload,
        is_error=error,
        _meta=meta,
    )


def create_server(tools: KnowledgeMcpTools, calls: BoundedCalls) -> Server:
    async def list_tools(
        context: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        request = _request(context)
        try:
            if params is not None and params.cursor is not None:
                raise failure("knowledge_mcp_input_invalid")
            names = await calls.run(
                lambda: tools.list_tools(
                    token=request.state.principal,
                    headers=request.headers,
                    control=request.state.control,
                ),
                request.state.control,
            )
            return types.ListToolsResult(
                tools=[
                    types.Tool(
                        name=name,
                        description=KNOWLEDGE_TOOL_CONTRACTS[name].description,
                        input_schema=KNOWLEDGE_TOOL_CONTRACTS[name].input_schema,
                        output_schema=KNOWLEDGE_TOOL_CONTRACTS[name].output_schema,
                        annotations=types.ToolAnnotations(
                            read_only_hint=True,
                            destructive_hint=False,
                            idempotent_hint=False,
                            open_world_hint=False,
                        ),
                    )
                    for name in names
                ]
            )
        except Exception:
            # tools/list 没有 CallToolResult；SDK 只接收固定异常，不接收原始失败内容。
            raise ValueError("知识工具目录不可用，请检查当前身份与任务授权") from None

    async def call_tool(
        context: ServerRequestContext, params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        request = _request(context)
        try:
            payload, handle = await calls.run(
                lambda: tools.invoke(
                    name=params.name,
                    token=request.state.principal,
                    arguments=params.arguments if params.arguments is not None else {},
                    headers=request.headers,
                    control=request.state.control,
                ),
                request.state.control,
            )
            return _result(payload, meta=handle.result_meta())
        except Exception as exc:
            error = safe_failure(exc)
            failed_handle = getattr(exc, "mcp_audit_handle", None)
            return _result(
                {"error": error.safe_message, "error_code": error.error_code},
                error=True,
                meta=failed_handle.result_meta()
                if isinstance(failed_handle, McpAuditHandle)
                else None,
            )

    return Server(
        "Enterprise Knowledge MCP",
        version=SERVER_VERSION,
        instructions=KNOWLEDGE_USAGE_INSTRUCTIONS,
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )


class KnowledgeSecurityMiddleware:
    def __init__(self, app: ASGIApp, allowed_hosts: tuple[str, ...]) -> None:
        self.app, self.allowed_hosts = app, allowed_hosts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] != "/mcp":
            await self.app(scope, receive, send)
            return
        control = CallControl()
        request = Request(scope)
        status, code = 401, "knowledge_mcp_authentication_failed"
        try:
            headers = request.headers
            auth = headers.getlist("authorization")
            if (
                len(auth) != 1
                or not auth[0].startswith("Bearer ")
                or not 1 <= len(auth[0][7:]) <= 8192
                or not auth[0][7:].isascii()
                or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in auth[0][7:])
            ):
                raise ValueError
            status, code = 403, "knowledge_mcp_context_invalid"
            if "origin" in headers or "cookie" in headers or scope.get("query_string"):
                raise ValueError
            status = 421
            if len(headers.getlist("host")) != 1 or headers["host"] not in self.allowed_hosts:
                raise ValueError
            status = 405
            if request.method != "POST":
                raise ValueError
            status, code = 400, "knowledge_mcp_input_invalid"
            for name in (
                "x-job-id",
                "x-app-user-id",
                "x-project-code",
                "x-invocation-id",
                "x-correlation-id",
                "x-agent-publication-id",
                "x-application-publication-id",
            ):
                values = headers.getlist(name)
                if len(values) != 1 or not 1 <= len(values[0]) <= 128:
                    raise ValueError
            incoming = deadline_from_headers(headers.getlist(DEADLINE_HEADER))
            if incoming is not None:
                control = CallControl(deadline_ms=min(control.deadline_ms, incoming))
            control.check()
            if (
                headers.getlist("content-type") != ["application/json"]
                or "content-encoding" in headers
            ):
                raise ValueError
            lengths = headers.getlist("content-length")
            if lengths and (
                len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit()
            ):
                raise ValueError
            status = 413
            if lengths and int(lengths[0]) > MAX_REQUEST_BYTES:
                raise ValueError
            body = bytearray()
            async with asyncio.timeout(max(0, control.remaining())):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    body.extend(message.get("body", b""))
                    if len(body) > MAX_REQUEST_BYTES:
                        raise ValueError
                    if not message.get("more_body", False):
                        break
            status = 400
            value = json.loads(body, object_pairs_hook=strict_object)
            if not isinstance(value, dict) or value.get("jsonrpc") != "2.0":
                raise ValueError
            # SDK 参数模型错误可能带原值，预先验证并仅返回固定错误。
            model = types.ClientRequest if "id" in value else types.ClientNotification
            TypeAdapter(model).validate_python(value)
            request.state.principal, request.state.control = auth[0][7:], control
        except Exception:
            if control.remaining() <= 0:
                status, code = 408, "knowledge_search_budget_exhausted"
            await JSONResponse(
                {"error": "知识服务请求被拒绝", "error_code": code},
                status_code=status,
                headers={"Cache-Control": "no-store"},
            )(scope, receive, send)
            return
        delivered = False
        disconnected = asyncio.Event()

        async def watch_disconnect() -> None:
            # JSON-response transport 等待结果时不读 receive，入口负责观察断开。
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    control.cancelled.set()
                    disconnected.set()
                    return

        async def replay() -> Message:
            nonlocal delivered
            if delivered:
                await disconnected.wait()
                return {"type": "http.disconnect"}
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        async def no_store(message: Message) -> None:
            if message["type"] == "http.response.start":
                message = {
                    **message,
                    "headers": [*message.get("headers", []), (b"cache-control", b"no-store")],
                }
            await send(message)

        async def dispatch_request() -> None:
            await self.app(scope, replay, no_store)

        dispatch = asyncio.create_task(dispatch_request())
        watcher = asyncio.create_task(watch_disconnect())
        try:
            done, _ = await asyncio.wait((dispatch, watcher), return_when=asyncio.FIRST_COMPLETED)
            if dispatch in done:
                await dispatch
            else:
                await watcher
        finally:
            control.cancelled.set()
            dispatch.cancel()
            watcher.cancel()
            await asyncio.gather(dispatch, watcher, return_exceptions=True)


class _Transport:
    def __init__(self, manager: StreamableHTTPSessionManager) -> None:
        self.manager = manager

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.manager.handle_request(scope, receive, send)


def create_app(
    tools: KnowledgeMcpTools,
    *,
    ready: Callable[[], None],
    close: Callable[[], None] = lambda: None,
    allowed_hosts: tuple[str, ...] = ("knowledge-mcp", "knowledge-mcp:9108", "127.0.0.1:9108"),
) -> KnowledgeSecurityMiddleware:
    calls = BoundedCalls()
    manager = StreamableHTTPSessionManager(
        app=create_server(tools, calls),
        json_response=True,
        stateless=True,
        max_request_body_size=MAX_REQUEST_BYTES,
        security_settings=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=list(allowed_hosts),
            allowed_origins=[],
        ),
    )

    async def health(_: Request) -> JSONResponse:
        try:
            await calls.run(ready, CallControl(seconds=5))
            return JSONResponse({"status": "ok", "server_code": KNOWLEDGE_MCP_SERVER_CODE})
        except Exception:
            return JSONResponse(
                {"status": "degraded", "server_code": KNOWLEDGE_MCP_SERVER_CODE}, status_code=503
            )

    @asynccontextmanager
    async def lifespan(_: Starlette) -> Any:
        try:
            async with manager.run():
                yield
        finally:
            await asyncio.to_thread(calls.close)
            close()

    app = Starlette(
        routes=[Route("/health", health, methods=["GET"]), Route("/mcp", _Transport(manager))],
        lifespan=lifespan,
    )
    app.router.redirect_slashes = False
    return KnowledgeSecurityMiddleware(app, allowed_hosts)


def create_default_app() -> KnowledgeSecurityMiddleware:
    from services.knowledge_mcp_server.bootstrap import build_app

    return build_app()


def main() -> None:
    import uvicorn

    # 本服务不输出 SDK 协议请求、HTTP 调试或原始异常；业务结果由安全审计记录。
    for name in ("mcp", "httpx", "httpx2", "httpcore"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    uvicorn.run(
        create_default_app(), host="0.0.0.0", port=9108, access_log=False, log_level="critical"
    )


if __name__ == "__main__":
    main()
