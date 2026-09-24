from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from mcp import types
from mcp.server import Server, ServerRequestContext
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import Message, Receive, Scope, Send

from app.modules.file_workspace.application import FileWorkspaceApplicationService
from app.modules.file_workspace.contracts import FILE_TOOL_MANIFEST
from app.modules.file_workspace.streaming_service import INTERNAL_TRANSFER_META
from app.shared.exceptions import AppError
from app.shared.build_identity import BuildIdentity, build_identity_from_environment
from app.modules.mcp_audit import McpAuditHandle
from services.file_service.audit import FileMcpAudit
from services.file_service.auth import (
    CachedPrincipalJwks,
    FilePrincipalError,
    FileWorkerPrincipalVerifier,
)
from services.file_service.health_routes import FileServiceHealthRoutes, FileServiceReadiness
from services.file_service.internal_http import (
    bearer_from_headers,
    bearer_token,
    header_values,
    safe_result,
)
from services.file_service.principal import FilePrincipalResolver
from services.file_service.processing_artifact_routes import DocumentArtifactRoutes
from services.file_service.processing_picture_routes import DocumentPictureRoutes
from services.file_service.processing_routes import (
    DocumentProcessingOperations,
    DocumentProcessingRunRoutes,
    ProcessingAccess,
)
from services.file_service.streaming_routes import FileStreamingOperations, FileStreamingRoutes


logger = logging.getLogger(__name__)
SERVER_VERSION = "0.1.0"
BUILD_IDENTITY_CAPABILITY = "enterprise-agent/build-identity-v1"


class BuildIdentifiedFileServer(Server):
    def __init__(self, *args: Any, build_identity: BuildIdentity, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._build_identity = build_identity

    def create_initialization_options(
        self,
        notification_options: Any = None,
        experimental_capabilities: dict[str, dict[str, Any]] | None = None,
        extensions: dict[str, dict[str, Any]] | None = None,
    ) -> Any:
        capabilities = dict(experimental_capabilities or {})
        if BUILD_IDENTITY_CAPABILITY in capabilities:
            raise ValueError("Reserved File MCP build identity capability")
        capabilities[BUILD_IDENTITY_CAPABILITY] = self._build_identity.to_dict()
        return super().create_initialization_options(
            notification_options=notification_options,
            experimental_capabilities=capabilities,
            extensions=extensions,
        )


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
        headers = header_values(scope)
        if bearer_from_headers(headers) is None:
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
    build_identity: BuildIdentity | None = None,
) -> Server:
    resolved_build_identity = build_identity or build_identity_from_environment("file-service")

    async def list_tools(
        context: ServerRequestContext,
        _params: types.PaginatedRequestParams | None,
    ) -> types.ListToolsResult:
        request = _request(context)
        _claims, _authorization, visible = principal.authenticate(bearer_token(request))
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
                bearer_token(request), tool_identifier=params.name
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

    return BuildIdentifiedFileServer(
        "Enterprise File Service",
        build_identity=resolved_build_identity,
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
    document_processing: DocumentProcessingOperations | None = None,
    document_processing_expected: bool = False,
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
    build_identity = build_identity_from_environment("file-service")
    server = create_file_server(
        principal,
        application,
        audit,
        build_identity=build_identity,
    )
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
    health = FileServiceHealthRoutes(
        build_identity=build_identity,
        database=database,
        storage=storage,
        jwks=jwks,
        document_processing=document_processing,
        document_processing_expected=document_processing_expected,
    )
    files = FileStreamingRoutes(streaming=streaming, service_principal=service_principal)
    processing_access = ProcessingAccess(
        service_principal=service_principal,
        document_processing=document_processing,
    )
    runs = DocumentProcessingRunRoutes(processing_access)
    artifacts = DocumentArtifactRoutes(processing_access)
    pictures = DocumentPictureRoutes(processing_access)

    @asynccontextmanager
    async def lifespan(_: Starlette) -> Any:
        async with manager.run():
            yield

    app = Starlette(
        routes=[
            Route("/health", health.health, methods=["GET"]),
            Route("/ready", health.readiness, methods=["GET"]),
            Route("/mcp", endpoint=_StreamableHttpApp(manager)),
            Route(
                "/internal/v1/file-transfers/{transfer_id}/content",
                files.download,
                methods=["GET"],
            ),
            Route(
                "/internal/v1/file-commits/{commit_id}/content",
                files.upload,
                methods=["PUT"],
            ),
            Route(
                "/internal/v1/attachments/{attachment_id}/content",
                files.attachment,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/file-maintenance/run",
                files.maintenance,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/file-maintenance/metrics",
                files.maintenance_metrics,
                methods=["GET"],
            ),
            Route(
                "/internal/v1/file-deliveries/{delivery_id}/content",
                files.delivery_content,
                methods=["GET"],
            ),
            Route(
                "/internal/v1/document-processing/admission/{action}",
                runs.admission,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/document-processing/workers/heartbeat",
                runs.heartbeat,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/document-processing/runs/{run_id}/claim",
                runs.claim,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/document-processing/runs/{run_id}/source-grant",
                runs.source_grant,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/document-processing/runs/{run_id}/source",
                runs.source_content,
                methods=["GET"],
            ),
            Route(
                "/internal/v1/document-processing/runs/{run_id}/submitted",
                runs.submitted,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/document-processing/runs/{run_id}/representations/{kind}/prepare",
                artifacts.representation_prepare,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/document-processing/transfers/{transfer_id}/content",
                artifacts.representation_upload,
                methods=["PUT"],
            ),
            Route(
                "/internal/v1/document-processing/runs/{run_id}/parent-artifact/prepare",
                artifacts.parent_artifact_prepare,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/document-processing/parent-artifact-transfers/{transfer_id}/content",
                artifacts.parent_artifact_upload,
                methods=["PUT"],
            ),
            Route(
                "/internal/v1/document-processing/runs/{run_id}/parent-artifact",
                artifacts.parent_artifact_content,
                methods=["GET"],
            ),
            Route(
                "/internal/v1/document-processing/runs/{run_id}/picture-assets/prepare",
                pictures.picture_asset_prepare,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/document-processing/picture-asset-transfers/{transfer_id}/content",
                pictures.picture_asset_upload,
                methods=["PUT"],
            ),
            Route(
                "/internal/v1/document-processing/runs/{run_id}/picture-occurrences",
                pictures.picture_occurrence_register,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/document-processing/runs/{run_id}/picture-items",
                pictures.picture_item_register,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/document-processing/picture-items/{picture_item_id}/claim",
                pictures.picture_item_claim,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/document-processing/picture-items/{picture_item_id}/asset",
                pictures.picture_asset_content,
                methods=["GET"],
            ),
            Route(
                "/internal/v1/document-processing/picture-items/{picture_item_id}/submitted",
                pictures.picture_item_submitted,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/document-processing/picture-items/{picture_item_id}/result/prepare",
                pictures.picture_result_prepare,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/document-processing/picture-result-transfers/{transfer_id}/content",
                pictures.picture_result_upload,
                methods=["PUT"],
            ),
            Route(
                "/internal/v1/document-processing/picture-items/{picture_item_id}/result",
                pictures.picture_result_content,
                methods=["GET"],
            ),
            Route(
                "/internal/v1/document-processing/picture-items/{picture_item_id}/complete",
                pictures.picture_item_complete,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/document-processing/picture-items/{picture_item_id}/retry",
                pictures.picture_item_retry,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/document-processing/runs/{run_id}/parent-complete",
                artifacts.parent_parse_complete,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/document-processing/runs/{run_id}/assembly/claim",
                artifacts.assembly_claim,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/document-processing/runs/{run_id}/assembly/context",
                artifacts.assembly_context,
                methods=["GET"],
            ),
            Route(
                "/internal/v1/document-processing/runs/{run_id}/assembly/finish",
                artifacts.assembly_finish,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/document-processing/runs/{run_id}/assembly/retry",
                artifacts.assembly_retry,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/document-processing/runs/{run_id}/finalize",
                runs.finalize,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/document-processing/runs/{run_id}/no-text",
                runs.no_text,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/document-processing/runs/{run_id}/retry",
                runs.retry,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/document-processing/runs/{run_id}/fail",
                runs.fail,
                methods=["POST"],
            ),
        ],
        lifespan=lifespan,
    )
    return FileServiceSecurityMiddleware(app, max_request_bytes=max_request_bytes)


def _request(context: ServerRequestContext) -> Request:
    if not isinstance(context.request, Request):
        raise FilePrincipalError(
            "File MCP transport context is invalid",
            safe_message="文件工具传输上下文无效",
            error_code="file_mcp_transport_invalid",
        )
    return context.request


def _tool_result(
    payload: dict[str, Any],
    *,
    is_error: bool = False,
    meta: dict[str, Any] | None = None,
) -> types.CallToolResult:
    safe = safe_result(payload)
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
