from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Awaitable, Callable

import uvicorn
from mcp import types
from mcp.server import Server, ServerRequestContext
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import Message, Receive, Scope, Send

from app.bootstrap import build_worker_container
from app.modules.mcp_audit import McpAuditHandle
from app.shared.config import load_settings
from app.shared.exceptions import AppError
from services.dingtalk_mcp_server.contracts import SERVER_CODE, SERVER_VERSION
from services.dingtalk_mcp_server.errors import DingTalkMcpError
from services.dingtalk_mcp_server.tools.registry import DingTalkToolRegistry


logger = logging.getLogger(__name__)
MAX_REQUEST_BYTES = 256 * 1024
MAX_RESPONSE_BYTES = 256 * 1024
REQUIRED_SCHEMA_VERSION = 123


class _McpTransport:
    def __init__(self, manager: StreamableHTTPSessionManager) -> None:
        self.manager = manager

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.manager.handle_request(scope, receive, send)


class DingTalkMcpSecurityMiddleware:
    def __init__(
        self,
        app: Callable[[Scope, Receive, Send], Awaitable[None]],
        *,
        max_request_bytes: int = MAX_REQUEST_BYTES,
    ) -> None:
        self.app = app
        self.max_request_bytes = max_request_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http" or scope.get("path") != "/mcp":
            await self.app(scope, receive, send)
            return
        headers: dict[str, list[str]] = {}
        for key, value in scope.get("headers") or []:
            headers.setdefault(key.decode("latin-1").lower(), []).append(value.decode("latin-1"))
        auth = headers.get("authorization") or []
        token = auth[0].removeprefix("Bearer ").strip() if len(auth) == 1 else ""
        if (
            len(auth) != 1
            or not auth[0].startswith("Bearer ")
            or not token
            or len(token.encode()) > 8192
            or "\r" in token
            or "\n" in token
        ):
            await JSONResponse({"error": "dingtalk_mcp_authentication_failed"}, status_code=401)(
                scope, receive, send
            )
            return
        if headers.get("origin"):
            await JSONResponse({"error": "dingtalk_mcp_origin_forbidden"}, status_code=403)(
                scope, receive, send
            )
            return
        body = bytearray()
        while True:
            message = await receive()
            if message.get("type") == "http.disconnect":
                return
            body.extend(message.get("body") or b"")
            if len(body) > self.max_request_bytes:
                await JSONResponse({"error": "dingtalk_mcp_request_too_large"}, status_code=413)(
                    scope, receive, send
                )
                return
            if not message.get("more_body", False):
                break
        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if delivered:
                return {"type": "http.disconnect"}
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay, send)


def create_server(registry: DingTalkToolRegistry) -> Server:
    async def list_tools(
        context: ServerRequestContext,
        _params: types.PaginatedRequestParams | None,
    ) -> types.ListToolsResult:
        request = _request(context)
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name=tool.tool_identifier,
                    description=tool.description,
                    input_schema=tool.input_schema,
                    output_schema=tool.output_schema,
                    annotations=types.ToolAnnotations(
                        read_only_hint=tool.read_only,
                        destructive_hint=tool.destructive,
                        idempotent_hint=tool.idempotent,
                        open_world_hint=tool.open_world,
                    ),
                )
                for tool in registry.authorized_tools(_bearer(request))
            ]
        )

    async def call_tool(
        context: ServerRequestContext,
        params: types.CallToolRequestParams,
    ) -> types.CallToolResult:
        request = _request(context)
        try:
            tool = registry.require(params.name)
            claims = tool.authenticate(_bearer(request))
            result = await asyncio.to_thread(
                tool.invoke,
                claims=claims,
                arguments=params.arguments or {},
                correlation_id=str(request.headers.get("x-correlation-id") or "")[:128],
                invocation_id=_invocation_id(request),
            )
            handle = getattr(result, "audit_handle", None)
            if not isinstance(handle, McpAuditHandle):
                raise DingTalkMcpError(
                    "DingTalk MCP result has no audit handle",
                    safe_message="钉钉操作审计结果无效",
                    error_code="dingtalk_mcp_audit_invalid",
                )
            return _tool_result(dict(result), is_error=False, meta=handle.result_meta())
        except AppError as exc:
            return _tool_result(
                {"error": str(exc.safe_message), "error_code": str(exc.error_code)},
                is_error=True,
                meta=_error_meta(exc),
            )
        except Exception as exc:
            logger.exception("DingTalk MCP call failed safely tool_name=%s", params.name)
            return _tool_result(
                {"error": "钉钉操作暂时不可用", "error_code": "dingtalk_mcp_unavailable"},
                is_error=True,
                meta=_error_meta(exc),
            )

    return Server(
        "Enterprise DingTalk MCP",
        version=SERVER_VERSION,
        instructions="Prepare governed DingTalk mutations; provider writes require card confirmation.",
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )


def create_app(
    registry: DingTalkToolRegistry,
    *,
    database: Any,
    allowed_hosts: tuple[str, ...] = (
        "dingtalk-mcp",
        "dingtalk-mcp:9107",
        "127.0.0.1:9107",
    ),
) -> DingTalkMcpSecurityMiddleware:
    manager = StreamableHTTPSessionManager(
        app=create_server(registry),
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
            schema = database.execute_one(
                "select version from schema_migration order by version desc limit 1"
            )
            if schema is None or int(schema["version"]) < REQUIRED_SCHEMA_VERSION:
                raise ValueError("DingTalk MCP database schema is not current")
            database.execute("select id from external_action_intent where 1 = 0")
            database.execute("select id from mcp_operation_audit where 1 = 0")
            registry.audit.assert_ready()
            return JSONResponse({"status": "ok", "server_code": SERVER_CODE})
        except Exception:
            return JSONResponse(
                {"status": "degraded", "server_code": SERVER_CODE}, status_code=503
            )

    @asynccontextmanager
    async def lifespan(_: Starlette) -> Any:
        async with manager.run():
            yield

    app = Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Route("/mcp", endpoint=_McpTransport(manager)),
        ],
        lifespan=lifespan,
    )
    return DingTalkMcpSecurityMiddleware(app)


def create_default_app() -> DingTalkMcpSecurityMiddleware:
    from services.dingtalk_mcp_server.bootstrap import build_tool_registry

    settings = load_settings()
    runtime = build_worker_container(settings, seed=settings.seed_local_config, service_name=SERVER_CODE)
    return create_app(build_tool_registry(runtime), database=runtime.database)


def _request(context: ServerRequestContext) -> Request:
    if not isinstance(context.request, Request):
        raise DingTalkMcpError(
            "DingTalk MCP transport context is invalid",
            safe_message="钉钉 MCP 请求上下文无效",
            error_code="dingtalk_mcp_transport_invalid",
        )
    return context.request


def _bearer(request: Request) -> str:
    values = request.headers.getlist("authorization")
    if len(values) != 1 or not values[0].startswith("Bearer "):
        raise DingTalkMcpError(
            "DingTalk MCP Bearer authentication is invalid",
            safe_message="平台身份凭证无效",
            error_code="dingtalk_mcp_authentication_failed",
        )
    return values[0].removeprefix("Bearer ").strip()


def _invocation_id(request: Request) -> str:
    value = str(request.headers.get("x-invocation-id") or "")
    if not value:
        raise DingTalkMcpError(
            "DingTalk MCP invocation context is missing",
            safe_message="钉钉 MCP 请求缺少执行上下文",
            error_code="dingtalk_mcp_context_missing",
        )
    return value


def _tool_result(payload: dict[str, Any], *, is_error: bool, meta: dict[str, str]) -> types.CallToolResult:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode()) > MAX_RESPONSE_BYTES:
        payload = {"error": "钉钉操作结果超限", "error_code": "dingtalk_mcp_response_too_large"}
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        is_error = True
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=encoded)],
        structured_content=payload,
        is_error=is_error,
        _meta=meta or None,
    )


def _error_meta(exc: Exception) -> dict[str, str]:
    handle = getattr(exc, "mcp_audit_handle", None)
    return handle.result_meta() if isinstance(handle, McpAuditHandle) else {}


def main() -> None:
    uvicorn.run(
        create_default_app(),
        host=os.environ.get("DINGTALK_MCP_HOST", "0.0.0.0"),
        port=int(os.environ.get("DINGTALK_MCP_PORT", "9107")),
        log_level=os.environ.get("LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    main()

