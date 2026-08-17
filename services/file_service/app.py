from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, Protocol

from mcp import types
from mcp.server import Server, ServerRequestContext
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route
from starlette.types import Message, Receive, Scope, Send

from app.modules.file_workspace.application import FileWorkspaceApplicationService
from app.modules.file_workspace.contracts import (
    FILE_MCP_SERVER_CODE,
    FILE_TOOL_MANIFEST,
)
from app.modules.file_workspace.streaming_service import INTERNAL_TRANSFER_META
from app.shared.exceptions import AppError
from app.modules.mcp_audit import McpAuditHandle
from services.file_service.audit import FileMcpAudit
from services.file_service.auth import (
    CachedPrincipalJwks,
    FilePrincipalError,
    FileWorkerPrincipalVerifier,
)
from services.file_service.principal import FilePrincipalResolver


logger = logging.getLogger(__name__)
SERVER_VERSION = "0.1.0"
REQUIRED_SCHEMA_VERSION = 111
MAX_TOOL_RESPONSE_BYTES = 256 * 1024


class FileStreamingOperations(Protocol):
    async def download_delivery(
        self,
        *,
        delivery_id: str,
        service_claims: dict[str, Any],
    ) -> tuple[AsyncIterator[bytes], dict[str, str | int]]: ...

    async def download_transfer(
        self, *, transfer_id: str, token: str
    ) -> tuple[AsyncIterator[bytes], str]: ...

    async def upload_commit(
        self,
        *,
        commit_id: str,
        token: str,
        body: AsyncIterator[bytes],
    ) -> dict[str, Any]: ...

    async def import_attachment(
        self,
        *,
        attachment_id: str,
        service_claims: dict[str, Any],
        media_type: str,
        body: AsyncIterator[bytes],
    ) -> dict[str, Any]: ...

    async def run_maintenance(self, *, service_claims: dict[str, Any]) -> dict[str, Any]: ...

    async def maintenance_metrics(self, *, service_claims: dict[str, Any]) -> dict[str, Any]: ...


class FileServiceReadiness(Protocol):
    def assert_ready(self) -> None: ...


class _StreamableHttpApp:
    def __init__(self, manager: StreamableHTTPSessionManager) -> None:
        self.manager = manager

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.manager.handle_request(scope, receive, send)


class FileServiceSecurityMiddleware:
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
        headers = _headers(scope)
        if _bearer_values(headers) is None:
            await JSONResponse({"error": "file_mcp_authentication_failed"}, status_code=401)(
                scope, receive, send
            )
            return
        if headers.get("origin"):
            await JSONResponse({"error": "file_mcp_origin_forbidden"}, status_code=403)(
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
                await JSONResponse({"error": "file_mcp_request_too_large"}, status_code=413)(
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


def create_file_server(
    principal: FilePrincipalResolver,
    application: FileWorkspaceApplicationService,
    audit: FileMcpAudit | None = None,
) -> Server:
    async def list_tools(
        context: ServerRequestContext,
        _params: types.PaginatedRequestParams | None,
    ) -> types.ListToolsResult:
        request = _request(context)
        _claims, _authorization, visible = principal.authenticate(_bearer(request))
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name=identifier,
                    description=FILE_TOOL_MANIFEST[identifier].description,
                    input_schema=dict(FILE_TOOL_MANIFEST[identifier].input_schema),
                    annotations=types.ToolAnnotations(
                        read_only_hint=not FILE_TOOL_MANIFEST[identifier].mutating,
                        destructive_hint=False,
                        idempotent_hint=True,
                        open_world_hint=False,
                    ),
                )
                for identifier in visible
            ]
        )

    async def call_tool(
        context: ServerRequestContext,
        params: types.CallToolRequestParams,
    ) -> types.CallToolResult:
        request = _request(context)
        started = time.monotonic()
        handle: McpAuditHandle | None = None
        try:
            claims, authorization, _visible = principal.authenticate(
                _bearer(request), tool_identifier=params.name
            )
            if audit is not None:
                handle = audit.begin(
                    claims=claims,
                    authorization=authorization,
                    tool_identifier=params.name,
                    arguments=params.arguments or {},
                    invocation_id=str(request.headers.get("x-invocation-id") or ""),
                    correlation_id=str(request.headers.get("x-correlation-id") or ""),
                )
                audit.authorized(handle)
            result = await asyncio.to_thread(
                application.invoke,
                context=authorization,
                tool_identifier=params.name,
                arguments=params.arguments or {},
            )
            transfer_meta = result.pop(INTERNAL_TRANSFER_META, None)
            if audit is not None and handle is not None:
                audit.complete(
                    handle,
                    status="SUCCEEDED",
                    result={**result, "status": "SUCCEEDED"},
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
            result_meta: dict[str, Any] = dict(handle.result_meta()) if handle is not None else {}
            if isinstance(transfer_meta, dict):
                result_meta.update(transfer_meta)
            return _tool_result(
                result,
                meta=result_meta or None,
            )
        except AppError as exc:
            if audit is not None and handle is not None:
                audit.complete(
                    handle,
                    status="DENIED",
                    result={"status": "DENIED", "error_code": exc.error_code},
                    error_code=exc.error_code or "file_mcp_denied",
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
            return _tool_result(
                {"error": exc.safe_message, "error_code": exc.error_code or "file_mcp_denied"},
                is_error=True,
                meta=handle.result_meta() if handle is not None else None,
            )
        except Exception:
            logger.exception("File MCP call failed safely tool_name=%s", params.name)
            return _tool_result(
                {"error": "文件服务暂时不可用", "error_code": "file_mcp_unavailable"},
                is_error=True,
            )

    return Server(
        "Enterprise File Service",
        version=SERVER_VERSION,
        instructions="Governed Job-bound task file tools only.",
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )


def create_app(
    *,
    principal: FilePrincipalResolver,
    service_principal: FileWorkerPrincipalVerifier,
    application: FileWorkspaceApplicationService,
    streaming: FileStreamingOperations,
    database: Any,
    storage: FileServiceReadiness,
    jwks: CachedPrincipalJwks,
    audit: FileMcpAudit | None = None,
    max_request_bytes: int = 32 * 1024,
    allowed_hosts: tuple[str, ...] = (
        "file-service",
        "file-service:9105",
        "127.0.0.1:9105",
    ),
) -> FileServiceSecurityMiddleware:
    server = create_file_server(principal, application, audit)
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
        return JSONResponse({"status": "ok", "server_code": FILE_MCP_SERVER_CODE})

    async def readiness(_: Request) -> JSONResponse:
        try:
            database.execute_one("select 1 as ready")
            schema = database.execute_one(
                "select version from schema_migration order by version desc limit 1"
            )
            if schema is None or int(schema["version"]) < REQUIRED_SCHEMA_VERSION:
                raise ValueError("File Service schema is not current")
            database.execute("select id from task_workspace where 1 = 0")
            database.execute("select id from managed_file_version where 1 = 0")
            storage.assert_ready()
            jwks.current()
            if tuple(sorted(FILE_TOOL_MANIFEST)) != (
                "file_create_commit_intent",
                "file_deliver_version",
                "file_get_metadata",
                "file_prepare_materialization",
                "file_retain_version",
                "task_workspace_get",
                "task_workspace_list_files",
            ):
                raise ValueError("File Tool Manifest is invalid")
            return JSONResponse(
                {
                    "status": "ok",
                    "server_code": FILE_MCP_SERVER_CODE,
                    "database": "ready",
                    "schema": "ready",
                    "object_storage": "ready",
                    "principal_jwks": "ready",
                    "tool_manifest": "ready",
                    "streaming_api": "ready",
                }
            )
        except Exception:
            return JSONResponse(
                {
                    "status": "degraded",
                    "server_code": FILE_MCP_SERVER_CODE,
                    "dependency": "unavailable",
                },
                status_code=503,
            )

    async def download(request: Request) -> StreamingResponse | JSONResponse:
        try:
            stream, media_type = await streaming.download_transfer(
                transfer_id=request.path_params["transfer_id"],
                token=_bearer(request),
            )
            return StreamingResponse(stream, media_type=media_type)
        except AppError as exc:
            return _safe_error(exc)

    async def upload(request: Request) -> JSONResponse:
        try:
            result = await streaming.upload_commit(
                commit_id=request.path_params["commit_id"],
                token=_bearer(request),
                body=request.stream(),
            )
            return JSONResponse(_safe_result(result))
        except AppError as exc:
            return _safe_error(exc)

    async def attachment(request: Request) -> JSONResponse:
        try:
            claims = service_principal.verify_service(
                _bearer(request),
                required_scope="internal:file-service:attachment:import",
            )
            result = await streaming.import_attachment(
                attachment_id=request.path_params["attachment_id"],
                service_claims=claims,
                media_type=str(request.headers.get("content-type") or "application/octet-stream"),
                body=request.stream(),
            )
            return JSONResponse(_safe_result(result))
        except AppError as exc:
            return _safe_error(exc)

    async def maintenance(request: Request) -> JSONResponse:
        try:
            claims = service_principal.verify_service(
                _bearer(request),
                required_scope="internal:file-service:content:cleanup",
            )
            result = await streaming.run_maintenance(service_claims=claims)
            return JSONResponse(_safe_result(result))
        except AppError as exc:
            return _safe_error(exc)

    async def maintenance_metrics(request: Request) -> JSONResponse:
        try:
            claims = service_principal.verify_service(
                _bearer(request),
                required_scope="internal:file-service:content:cleanup",
            )
            result = await streaming.maintenance_metrics(service_claims=claims)
            return JSONResponse(_safe_result(result))
        except AppError as exc:
            return _safe_error(exc)

    async def delivery_content(request: Request) -> StreamingResponse | JSONResponse:
        try:
            claims = service_principal.verify_delivery(
                _bearer(request),
                required_scope="internal:file-service:delivery:read",
            )
            stream, metadata = await streaming.download_delivery(
                delivery_id=request.path_params["delivery_id"],
                service_claims=claims,
            )
            return StreamingResponse(
                stream,
                media_type=str(metadata["media_type"]),
                headers={
                    "X-File-Name-B64": base64.urlsafe_b64encode(
                        str(metadata["display_name"]).encode("utf-8")
                    ).decode("ascii"),
                    "X-File-Size": str(metadata["size_bytes"]),
                    "X-File-SHA256": str(metadata["sha256"]),
                    "X-File-Format": str(metadata["format_code"]),
                },
            )
        except AppError as exc:
            return _safe_error(exc)

    @asynccontextmanager
    async def lifespan(_: Starlette) -> Any:
        async with manager.run():
            yield

    app = Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Route("/ready", readiness, methods=["GET"]),
            Route("/mcp", endpoint=_StreamableHttpApp(manager)),
            Route(
                "/internal/v1/file-transfers/{transfer_id}/content",
                download,
                methods=["GET"],
            ),
            Route(
                "/internal/v1/file-commits/{commit_id}/content",
                upload,
                methods=["PUT"],
            ),
            Route(
                "/internal/v1/attachments/{attachment_id}/content",
                attachment,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/file-maintenance/run",
                maintenance,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/file-maintenance/metrics",
                maintenance_metrics,
                methods=["GET"],
            ),
            Route(
                "/internal/v1/file-deliveries/{delivery_id}/content",
                delivery_content,
                methods=["GET"],
            ),
        ],
        lifespan=lifespan,
    )
    return FileServiceSecurityMiddleware(app, max_request_bytes=max_request_bytes)


def _headers(scope: Scope) -> dict[str, list[str]]:
    headers: dict[str, list[str]] = {}
    for key, value in scope.get("headers") or []:
        headers.setdefault(key.decode("latin-1").lower(), []).append(value.decode("latin-1"))
    return headers


def _bearer_values(headers: dict[str, list[str]]) -> str | None:
    values = headers.get("authorization") or []
    if len(values) != 1 or not values[0].startswith("Bearer "):
        return None
    token = values[0].removeprefix("Bearer ").strip()
    if not token or len(token.encode()) > 8192 or "\r" in token or "\n" in token:
        return None
    return token


def _bearer(request: Request) -> str:
    token = _bearer_values({"authorization": request.headers.getlist("authorization")})
    if token is None:
        raise FilePrincipalError(
            "File Service bearer token is missing",
            safe_message="平台文件身份凭证缺失",
            error_code="file_principal_token_missing",
        )
    return token


def _request(context: ServerRequestContext) -> Request:
    if not isinstance(context.request, Request):
        raise FilePrincipalError(
            "File MCP transport context is invalid",
            safe_message="文件工具传输上下文无效",
            error_code="file_mcp_transport_invalid",
        )
    return context.request


def _safe_result(value: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    if len(encoded) > MAX_TOOL_RESPONSE_BYTES:
        raise ValueError("File Service response exceeds its safe bound")
    forbidden = ("object_key", "bucket", "access_key", "secret_key", "presigned_url")
    if any(key in value for key in forbidden):
        raise ValueError("File Service response contains infrastructure fields")
    return value


def _safe_error(exc: AppError) -> JSONResponse:
    return JSONResponse(
        {"error": exc.safe_message, "error_code": exc.error_code or "file_service_denied"},
        status_code=403,
    )


def _tool_result(
    payload: dict[str, Any],
    *,
    is_error: bool = False,
    meta: dict[str, Any] | None = None,
) -> types.CallToolResult:
    safe = _safe_result(payload)
    return types.CallToolResult(
        content=[
            types.TextContent(
                type="text",
                text=json.dumps(safe, ensure_ascii=False, sort_keys=True),
            )
        ],
        structured_content=safe,
        is_error=is_error,
        _meta=meta or None,
    )
