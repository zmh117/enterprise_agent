from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from contextlib import suppress
from dataclasses import replace
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
from app.modules.identity.application.principal_jwt import PrincipalJwks, PrincipalTokenVerifier
from app.modules.identity.infrastructure.ones_identity_verifier import UrllibOnesIdentityVerifier
from app.modules.mcp_audit import McpAuditCoordinator, McpAuditHandle
from app.shared.config import OnesIdentitySettings, load_settings
from app.shared.exceptions import AppError
from services.ones_mcp_server.contracts import (
    SERVER_CODE,
    SERVER_VERSION,
    TOOL_IDENTIFIER,
    TOOL_INPUT_SCHEMA,
    validate_provider_target,
)
from services.ones_mcp_server.runtime import (
    OnesMcpError,
    OnesPrincipalResolver,
    OnesProviderClient,
    OnesWorkItemSearchService,
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
        body = bytearray()
        while True:
            message = await receive()
            if message.get("type") == "http.disconnect":
                return
            body.extend(message.get("body") or b"")
            if len(body) > self.max_request_bytes:
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


def create_ones_server(service: OnesWorkItemSearchService) -> Server:
    async def list_tools(
        context: ServerRequestContext,
        _params: types.PaginatedRequestParams | None,
    ) -> types.ListToolsResult:
        request = _request(context)
        service.authenticate(_bearer(request))
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name=TOOL_IDENTIFIER,
                    description="按关键字和类型查询当前用户默认 Team 的 ONES 工作项。",
                    input_schema=TOOL_INPUT_SCHEMA,
                    annotations=types.ToolAnnotations(
                        read_only_hint=True,
                        destructive_hint=False,
                        idempotent_hint=True,
                        open_world_hint=False,
                    ),
                )
            ]
        )

    async def call_tool(
        context: ServerRequestContext,
        params: types.CallToolRequestParams,
    ) -> types.CallToolResult:
        request = _request(context)
        try:
            claims = service.authenticate(_bearer(request))
            if params.name != TOOL_IDENTIFIER:
                raise OnesMcpError(
                    "ONES MCP Tool is not published",
                    safe_message="当前 ONES 工具未发布",
                    error_code="ones_mcp_tool_denied",
                )
            result = await asyncio.to_thread(
                service.search,
                claims=claims,
                arguments=params.arguments or {},
                correlation_id=str(request.headers.get("x-correlation-id") or "")[:128],
                invocation_id=_invocation_id(request),
            )
            return _tool_result(
                dict(result),
                is_error=False,
                meta=result.audit_handle.result_meta(),
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
                {"error": "ONES 查询暂时不可用", "error_code": "ones_mcp_unavailable"},
                is_error=True,
                meta=_error_meta(exc),
            )

    return Server(
        "Enterprise ONES MCP",
        version=SERVER_VERSION,
        instructions="Identity-aware ONES work-item search only.",
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )


def create_app(
    service: OnesWorkItemSearchService,
    *,
    database: Any,
    max_request_bytes: int,
    audit_retention_days: int,
    platform_audit_service: Any | None = None,
    allowed_hosts: tuple[str, ...] = (
        "ones-mcp",
        "ones-mcp:9104",
        "127.0.0.1:9104",
    ),
) -> OnesMcpSecurityMiddleware:
    server = create_ones_server(service)
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
            service.audit.assert_ready()
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
                    service,
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

    app = Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Route("/mcp", endpoint=_StreamableHttpApp(manager)),
        ],
        lifespan=lifespan,
    )
    return OnesMcpSecurityMiddleware(app, max_request_bytes=max_request_bytes)


def service_from_container(runtime: Container) -> OnesWorkItemSearchService:
    settings = runtime.settings
    credentials = runtime.external_identity_credential_repository
    if credentials is None:
        raise ValueError("ONES MCP requires the platform credential master key")
    target = validate_provider_target(
        settings.ones_mcp.provider_base_url,
        allowed_hosts=settings.ones_mcp.provider_allowed_hosts,
        app_env=settings.environment,
        allow_insecure_local=settings.ones_mcp.allow_insecure_local,
    )
    verifier = PrincipalTokenVerifier(
        PrincipalJwks.from_file(settings.principal_jwt.public_jwks_file),
        audit_service=runtime.audit_service,
    )
    provider = OnesProviderClient(
        target,
        timeout_seconds=settings.ones_mcp.timeout_seconds,
        max_response_bytes=settings.ones_mcp.max_response_bytes,
    )
    login_settings = replace(
        settings.ones_identity,
        base_url=target.base_url,
        allowed_hosts=(target.host,),
        timeout_seconds=settings.ones_mcp.timeout_seconds,
        max_response_bytes=settings.ones_mcp.max_response_bytes,
        allow_insecure_local=target.allow_insecure_local,
    )
    if not isinstance(login_settings, OnesIdentitySettings):
        raise TypeError("ONES identity settings are invalid")
    return OnesWorkItemSearchService(
        OnesPrincipalResolver(
            runtime.database,
            verifier,
            runtime.mcp_tool_snapshot_service,
            runtime.business_authorization_service,
            credentials,
        ),
        provider,
        UrllibOnesIdentityVerifier(login_settings, environment=settings.environment),
        credentials,
        McpAuditCoordinator(
            runtime.database,
            max_payload_bytes=settings.ones_mcp.max_response_bytes,
            audit_service=runtime.audit_service,
        ),
    )


def create_default_app() -> OnesMcpSecurityMiddleware:
    settings = load_settings()
    runtime = build_worker_container(
        settings,
        seed=settings.seed_local_config,
        service_name=SERVER_CODE,
    )
    return create_app(
        service_from_container(runtime),
        database=runtime.database,
        max_request_bytes=settings.ones_mcp.max_request_bytes,
        audit_retention_days=settings.ones_mcp.audit_retention_days,
        platform_audit_service=runtime.audit_service,
    )


async def _retention_loop(
    service: OnesWorkItemSearchService,
    *,
    retention_days: int,
    platform_audit_service: Any | None,
) -> None:
    while True:
        try:
            deleted = await asyncio.to_thread(
                service.audit.purge_expired,
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
        meta=meta or None,
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
