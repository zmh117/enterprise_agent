from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from contextlib import suppress
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

from app.bootstrap import Container, build_worker_container
from app.modules.mcp_audit import McpAuditHandle
from app.shared.config import load_settings
from app.shared.exceptions import AppError
from app.modules.knowledge.domain.governance import strict_object
from app.modules.knowledge.api.deadline import bounded_knowledge_request
from app.modules.knowledge.application.readability import MAX_REQUEST_BYTES as READABILITY_MAX_BYTES
from app.modules.knowledge.application.retrieval_budget import (
    DEADLINE_HEADER,
    MAX_RETRIEVAL_SECONDS,
    deadline_from_headers,
)
from services.ones_mcp_server.contracts import (
    SERVER_CODE,
    SERVER_VERSION,
)
from services.ones_mcp_server.errors import OnesMcpError
from services.ones_mcp_server.tools.registry import OnesToolRegistry
from services.ones_mcp_server.tools.work_item_search import OnesWorkItemSearchService
from services.ones_mcp_server.knowledge_verification import (
    OnesSourceVerification,
    SOURCE_VERIFICATION_PATH,
)
from services.ones_mcp_server.knowledge_readability import (
    READABILITY_PATH,
    OnesKnowledgeReadability,
    ReadabilityRequest,
)


logger = logging.getLogger(__name__)
MAX_TOOL_RESPONSE_BYTES = 256 * 1024
REQUIRED_ONES_SCHEMA_VERSION = 105


class _StreamableHttpApp:
    def __init__(self, manager: StreamableHTTPSessionManager) -> None:
        self.manager = manager

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.manager.handle_request(scope, receive, send)


class OnesMcpSecurityMiddleware:
    def __init__(
        self,
        app: Callable[[Scope, Receive, Send], Awaitable[None]],
        *,
        max_request_bytes: int,
        internal_allowed_hosts: tuple[str, ...] = (),
    ) -> None:
        self.app = app
        self.max_request_bytes = max_request_bytes
        self.internal_allowed_hosts = internal_allowed_hosts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:  # noqa: C901
        if scope.get("type") != "http" or scope.get("path") not in {
            "/mcp",
            SOURCE_VERIFICATION_PATH,
            READABILITY_PATH,
        }:
            await self.app(scope, receive, send)
            return
        headers: dict[str, list[str]] = {}
        for key, value in scope.get("headers") or []:
            headers.setdefault(key.decode("latin-1").lower(), []).append(value.decode("latin-1"))
        authorization = headers.get("authorization") or []
        token = ""
        if len(authorization) == 1 and authorization[0].startswith("Bearer "):
            token = authorization[0].removeprefix("Bearer ").strip()
        if (
            len(authorization) != 1
            or not token
            or len(token.encode("utf-8")) > 8192
            or "\r" in token
            or "\n" in token
        ):
            await self._reject(
                scope,
                receive,
                send,
                status=401,
                code="ones_mcp_authentication_failed",
            )
            return
        if headers.get("origin"):
            await self._reject(
                scope,
                receive,
                send,
                status=403,
                code="ones_mcp_origin_forbidden",
            )
            return
        internal = scope.get("path") in {SOURCE_VERIFICATION_PATH, READABILITY_PATH}
        if internal and (headers.get("host") or []) not in [
            [host] for host in self.internal_allowed_hosts
        ]:
            await self._reject(scope, receive, send, status=403, code="ones_mcp_host_forbidden")
            return
        read_deadline = None
        if scope.get("path") == READABILITY_PATH:
            try:
                incoming = deadline_from_headers(headers.get(DEADLINE_HEADER.lower(), []))
            except AppError:
                await self._reject(scope, receive, send, status=400, code="knowledge_input_invalid")
                return
            milliseconds = (
                min(int((time.time() + MAX_RETRIEVAL_SECONDS) * 1000), incoming)
                if incoming is not None
                else int((time.time() + MAX_RETRIEVAL_SECONDS) * 1000)
            )
            read_deadline = time.monotonic() + milliseconds / 1000 - time.time()
            # Preserve time already spent reading the body when the header was absent.
            if incoming is None:
                scope = {
                    **scope,
                    "headers": [
                        *scope.get("headers", []),
                        (DEADLINE_HEADER.lower().encode(), str(milliseconds).encode()),
                    ],
                }
        body = bytearray()
        while True:
            try:
                message = (
                    await receive()
                    if read_deadline is None
                    else await asyncio.wait_for(receive(), max(0, read_deadline - time.monotonic()))
                )
            except TimeoutError:
                await self._reject(
                    scope, receive, send, status=503, code="knowledge_search_budget_exhausted"
                )
                return
            if message.get("type") == "http.disconnect":
                return
            body.extend(message.get("body") or b"")
            if len(body) > (
                min(
                    self.max_request_bytes,
                    READABILITY_MAX_BYTES if scope.get("path") == READABILITY_PATH else 4096,
                )
                if internal
                else self.max_request_bytes
            ):
                await self._reject(
                    scope,
                    receive,
                    send,
                    status=413,
                    code="ones_mcp_request_too_large",
                )
                return
            if not message.get("more_body", False):
                break
        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if delivered:
                if scope.get("path") == READABILITY_PATH:
                    return await receive()
                return {"type": "http.disconnect"}
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay, send)

    @staticmethod
    async def _reject(
        scope: Scope,
        receive: Receive,
        send: Send,
        *,
        status: int,
        code: str,
    ) -> None:
        response = JSONResponse({"error": code}, status_code=status)
        await response(scope, receive, send)


def create_ones_server(registry: OnesToolRegistry) -> Server:
    async def list_tools(
        context: ServerRequestContext,
        _params: types.PaginatedRequestParams | None,
    ) -> types.ListToolsResult:
        request = _request(context)
        authorized_tools = registry.authorized_tools(_bearer(request))
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
                for tool in authorized_tools
            ]
        )

    async def call_tool(
        context: ServerRequestContext,
        params: types.CallToolRequestParams,
    ) -> types.CallToolResult:
        request = _request(context)
        try:
            tool = registry.require(params.name)
            claims = registry.authenticate(
                _bearer(request),
                tool_identifier=tool.tool_identifier,
            )
            result = await asyncio.to_thread(
                tool.invoke,
                claims=claims,
                arguments=params.arguments or {},
                correlation_id=str(request.headers.get("x-correlation-id") or "")[:128],
                invocation_id=_invocation_id(request),
            )
            audit_handle = getattr(result, "audit_handle", None)
            if not isinstance(audit_handle, McpAuditHandle):
                raise OnesMcpError(
                    "ONES MCP Tool result is missing its audit handle",
                    safe_message="ONES 操作审计结果无效",
                    error_code="ones_mcp_audit_invalid",
                )
            return _tool_result(
                dict(result),
                is_error=False,
                meta=audit_handle.result_meta(),
            )
        except AppError as exc:
            return _tool_result(
                {
                    "error": str(exc.safe_message),
                    "error_code": str(exc.error_code or "ones_mcp_denied"),
                },
                is_error=True,
                meta=_error_meta(exc),
            )
        except Exception as exc:
            logger.exception("ONES MCP call failed safely tool_name=%s", params.name)
            return _tool_result(
                {"error": "ONES 操作暂时不可用", "error_code": "ones_mcp_unavailable"},
                is_error=True,
                meta=_error_meta(exc),
            )

    return Server(
        "Enterprise ONES MCP",
        version=SERVER_VERSION,
        instructions=(
            "Identity-aware, code-registered ONES reads plus confirmed defect creation and updates."
        ),
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )


def create_app(  # noqa: C901, PLR0915
    service: OnesWorkItemSearchService | OnesToolRegistry,
    *,
    database: Any,
    max_request_bytes: int,
    audit_retention_days: int,
    platform_audit_service: Any | None = None,
    source_verification: OnesSourceVerification | None = None,
    knowledge_readability: OnesKnowledgeReadability | None = None,
    allowed_hosts: tuple[str, ...] = (
        "ones-mcp",
        "ones-mcp:9104",
        "127.0.0.1:9104",
    ),
) -> OnesMcpSecurityMiddleware:
    registry = (
        service
        if isinstance(service, OnesToolRegistry)
        else OnesToolRegistry(
            authenticate=service.authenticate,
            tools=(service,),
            audit=service.audit,
        )
    )
    server = create_ones_server(registry)
    manager = StreamableHTTPSessionManager(
        app=server,
        json_response=True,
        stateless=True,
        max_request_body_size=max_request_bytes,
        security_settings=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=list(allowed_hosts),
            allowed_origins=[],
        ),
    )

    async def health(_: Request) -> JSONResponse:
        try:
            database.execute_one("select 1 as ready")
            schema = database.execute_one(
                "select version from schema_migration order by version desc limit 1"
            )
            if schema is None or int(schema["version"]) < REQUIRED_ONES_SCHEMA_VERSION:
                raise ValueError("ONES MCP database schema is not current")
            database.execute("select id from external_identity_credential where 1 = 0")
            database.execute("select id from mcp_operation_audit where 1 = 0")
            registry.audit.assert_ready()
            if not 1 <= audit_retention_days <= 3650:
                raise ValueError("MCP operation audit retention is invalid")
            return JSONResponse(
                {
                    "status": "ok",
                    "server_code": SERVER_CODE,
                    "database": "ready",
                    "schema": "ready",
                    "principal_jwks": "ready",
                    "credential_cipher": "ready",
                    "audit_retention": "ready",
                }
            )
        except Exception:
            return JSONResponse(
                {
                    "status": "degraded",
                    "server_code": SERVER_CODE,
                    "database": "unavailable",
                },
                status_code=503,
            )

    @asynccontextmanager
    async def lifespan(_: Starlette) -> Any:
        retention_task: asyncio.Task[None] | None = None
        if 1 <= audit_retention_days <= 3650:
            retention_task = asyncio.create_task(
                _retention_loop(
                    registry,
                    retention_days=audit_retention_days,
                    platform_audit_service=platform_audit_service,
                )
            )
        try:
            async with manager.run():
                yield
        finally:
            if retention_task is not None:
                retention_task.cancel()
                with suppress(asyncio.CancelledError):
                    await retention_task

    async def verify_source(request: Request) -> JSONResponse:
        if source_verification is None:
            return JSONResponse(
                {"error_code": "knowledge_verifier_unavailable", "error": "来源核验服务未配置"},
                status_code=503,
            )
        try:
            source_verification.detail.authenticate(_bearer(request))
        except AppError:
            return JSONResponse(
                {"error_code": "ones_mcp_authentication_failed", "error": "平台身份凭证无效"},
                status_code=401,
            )
        try:
            value = json.loads(await request.body(), object_pairs_hook=strict_object)
            if (
                not isinstance(value, dict)
                or set(value) != {"binding_id"}
                or not isinstance(value["binding_id"], str)
                or not 1 <= len(value["binding_id"]) <= 128
            ):
                raise ValueError("invalid")
        except (ValueError, UnicodeError, RecursionError):
            return JSONResponse(
                {"error_code": "knowledge_input_invalid", "error": "来源核验参数无效"},
                status_code=400,
            )
        try:
            result = await asyncio.to_thread(
                source_verification.verify, token=_bearer(request), binding_id=value["binding_id"]
            )
            return JSONResponse(result)
        except AppError as exc:
            busy = exc.error_code == "knowledge_verification_busy"
            return JSONResponse(
                {
                    "error_code": "knowledge_verification_busy"
                    if busy
                    else "knowledge_verification_failed",
                    "error": "来源核验繁忙，请稍后重试"
                    if busy
                    else "来源核验未通过，请检查身份、授权及来源",
                },
                status_code=429 if busy else 403,
            )
        except Exception:
            # 不记录动态异常：HTTP 客户端异常可能包含请求 Authorization 或 Provider 响应。
            return JSONResponse(
                {"error_code": "knowledge_verification_failed", "error": "来源核验服务暂时不可用"},
                status_code=503,
            )

    @bounded_knowledge_request
    async def check_readability(request: Request) -> JSONResponse:
        assert knowledge_readability is not None
        try:
            await asyncio.to_thread(knowledge_readability.detail.authenticate, _bearer(request))
        except AppError:
            return JSONResponse(
                {"error_code": "ones_mcp_authentication_failed", "error": "平台身份凭证无效"},
                status_code=401,
            )
        try:
            parsed = ReadabilityRequest.parse(
                json.loads(await request.body(), object_pairs_hook=strict_object)
            )
            deadline_ms = deadline_from_headers(request.headers.getlist(DEADLINE_HEADER))
        except (ValueError, UnicodeError, RecursionError, AppError):
            return JSONResponse(
                {"error_code": "knowledge_input_invalid", "error": "知识候选参数无效"},
                status_code=400,
            )
        try:
            result = await asyncio.to_thread(
                knowledge_readability.check,
                token=_bearer(request),
                request=parsed,
                deadline_ms=deadline_ms,
            )
            return JSONResponse(result)
        except AppError as exc:
            # 不回传 Provider 的动态诊断或部分结果；只有固定安全错误码。
            code = (
                "knowledge_readability_busy"
                if exc.error_code == "knowledge_readability_busy"
                else "knowledge_readability_failed"
            )
            return JSONResponse(
                {"error_code": code, "error": "知识可读性检查未完成，请检查权限或稍后重试"},
                status_code=429 if code == "knowledge_readability_busy" else 503,
            )
        except Exception:
            return JSONResponse(
                {"error_code": "knowledge_readability_failed", "error": "知识可读性检查暂时不可用"},
                status_code=503,
            )

    app = Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Route("/mcp", endpoint=_StreamableHttpApp(manager)),
            *(
                [Route(SOURCE_VERIFICATION_PATH, verify_source, methods=["POST"])]
                if source_verification
                else []
            ),
            *(
                [Route(READABILITY_PATH, check_readability, methods=["POST"])]
                if knowledge_readability
                else []
            ),
        ],
        lifespan=lifespan,
    )
    return OnesMcpSecurityMiddleware(
        app, max_request_bytes=max_request_bytes, internal_allowed_hosts=allowed_hosts
    )


def service_from_container(runtime: Container) -> OnesWorkItemSearchService:
    from services.ones_mcp_server.bootstrap import build_work_item_search_service

    return build_work_item_search_service(runtime)


def registry_from_container(runtime: Container) -> OnesToolRegistry:
    from services.ones_mcp_server.bootstrap import build_tool_registry

    return build_tool_registry(runtime)


def create_default_app() -> OnesMcpSecurityMiddleware:
    settings = load_settings()
    runtime = build_worker_container(
        settings,
        seed=settings.seed_local_config,
        service_name=SERVER_CODE,
    )
    registry = registry_from_container(runtime)
    from services.ones_mcp_server.bootstrap import (
        build_source_verification,
        build_knowledge_readability,
    )

    source_verification = build_source_verification(runtime, registry)

    return create_app(
        registry,
        database=runtime.database,
        max_request_bytes=settings.ones_mcp.max_request_bytes,
        audit_retention_days=settings.ones_mcp.audit_retention_days,
        platform_audit_service=runtime.audit_service,
        source_verification=source_verification,
        knowledge_readability=build_knowledge_readability(runtime, source_verification),
    )


async def _retention_loop(
    registry: OnesToolRegistry,
    *,
    retention_days: int,
    platform_audit_service: Any | None,
) -> None:
    while True:
        try:
            deleted = await asyncio.to_thread(
                registry.audit.purge_expired,
                retention_days=retention_days,
            )
            if platform_audit_service is not None:
                platform_audit_service.record(
                    "mcp.audit.retention_cleanup",
                    status="success",
                    summary="Expired MCP operation audits deleted",
                    payload={"retention_days": retention_days, "deleted_count": deleted},
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.error("MCP operation audit retention cleanup failed safely")
        await asyncio.sleep(60 * 60)


def _request(context: ServerRequestContext) -> Request:
    request = context.request
    if not isinstance(request, Request):
        raise OnesMcpError(
            "ONES MCP transport context is invalid",
            safe_message="ONES MCP 请求上下文无效",
            error_code="ones_mcp_transport_invalid",
        )
    return request


def _bearer(request: Request) -> str:
    values = request.headers.getlist("authorization")
    if len(values) != 1 or not values[0].startswith("Bearer "):
        raise OnesMcpError(
            "ONES MCP Bearer authentication is invalid",
            safe_message="平台身份凭证无效",
            error_code="ones_mcp_authentication_failed",
        )
    token = values[0].removeprefix("Bearer ").strip()
    if not token:
        raise OnesMcpError(
            "ONES MCP Bearer authentication is empty",
            safe_message="平台身份凭证无效",
            error_code="ones_mcp_authentication_failed",
        )
    return token


def _invocation_id(request: Request) -> str:
    invocation_id = str(request.headers.get("x-invocation-id") or "")
    if not invocation_id:
        raise OnesMcpError(
            "ONES MCP invocation context is missing",
            safe_message="ONES MCP 请求缺少执行上下文",
            error_code="ones_mcp_context_missing",
        )
    return invocation_id


def _tool_result(
    payload: dict[str, Any],
    *,
    is_error: bool,
    meta: dict[str, str],
) -> types.CallToolResult:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_TOOL_RESPONSE_BYTES:
        payload = {"error": "ONES 查询结果超限", "error_code": "ones_mcp_response_too_large"}
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
        host=os.environ.get("ONES_MCP_HOST", "0.0.0.0"),
        port=int(os.environ.get("ONES_MCP_PORT", "9104")),
        log_level=os.environ.get("LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    main()
