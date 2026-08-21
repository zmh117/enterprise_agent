from __future__ import annotations

import asyncio
import base64
import json
import logging
import tempfile
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
from app.modules.document_processing.profile import (
    DOCLING_LAYOUT_OCR_V1,
    DOCLING_LAYOUT_OCR_V1_PROFILE_HASH,
    DOCLING_TEXT_V1,
)
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
REQUIRED_SCHEMA_VERSION = 118
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


class DocumentProcessingOperations(Protocol):
    def claim(self, *, message: dict[str, Any], service_principal_id: str) -> dict[str, Any]: ...

    def prepare_source_stream(
        self, *, run_id: str, tenant_id: str, service_principal_id: str
    ) -> dict[str, str]: ...

    def open_source_stream(self, *, grant: str, service_principal_id: str) -> Any: ...

    def mark_submitted(self, *, run_id: str, external_task_id: str) -> dict[str, Any]: ...

    def prepare_representation_transfer(
        self,
        *,
        run_id: str,
        kind: str,
        expected_size_bytes: int,
        expected_sha256: str,
    ) -> dict[str, Any]: ...

    def upload_representation(
        self,
        *,
        transfer_id: str,
        upload_token: str,
        stream: Any,
        media_type: str,
    ) -> dict[str, Any]: ...

    def prepare_parent_artifact_transfer(
        self, *, run_id: str, expected_size_bytes: int, expected_sha256: str
    ) -> dict[str, Any]: ...

    def upload_parent_artifact(
        self, *, transfer_id: str, upload_token: str, stream: Any
    ) -> dict[str, Any]: ...

    def open_parent_artifact(self, *, run_id: str) -> Any: ...

    def prepare_picture_asset_transfer(self, **values: Any) -> dict[str, Any]: ...

    def upload_picture_asset(self, **values: Any) -> dict[str, Any]: ...

    def register_picture_occurrence(self, **values: Any) -> dict[str, Any]: ...

    def register_picture_item(self, **values: Any) -> dict[str, Any]: ...

    def claim_picture_item(self, **values: Any) -> tuple[dict[str, Any], bool]: ...

    def picture_item_context(self, **values: Any) -> dict[str, Any]: ...

    def open_picture_asset(self, *, picture_item_id: str) -> Any: ...

    def mark_picture_submitted(self, **values: Any) -> dict[str, Any]: ...

    def complete_picture_item(self, **values: Any) -> dict[str, Any]: ...

    def retry_picture_item(self, **values: Any) -> dict[str, Any]: ...

    def prepare_picture_result_transfer(self, **values: Any) -> dict[str, Any]: ...

    def upload_picture_result(self, **values: Any) -> dict[str, Any]: ...

    def open_picture_result(self, *, picture_item_id: str) -> Any: ...

    def complete_parent_parse(self, **values: Any) -> dict[str, Any]: ...

    def claim_assembly(self, **values: Any) -> tuple[dict[str, Any], bool]: ...

    def assembly_context(self, **values: Any) -> dict[str, Any]: ...

    def finish_assembly(self, **values: Any) -> dict[str, Any]: ...

    def retry_assembly(self, **values: Any) -> dict[str, Any]: ...

    def finalize(
        self,
        *,
        run_id: str,
        partial: bool,
        page_count: int | None,
        processing_time_ms: int | None,
    ) -> list[dict[str, Any]]: ...

    def complete_without_text(
        self, *, run_id: str, page_count: int | None, processing_time_ms: int | None
    ) -> dict[str, Any]: ...

    def schedule_retry(
        self, *, run_id: str, error_code: str, delay_seconds: int
    ) -> dict[str, Any]: ...

    def fail(
        self, *, run_id: str, error_code: str, processing_time_ms: int | None = None
    ) -> dict[str, Any]: ...


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
            database.execute("select id from document_picture_asset where 1 = 0")
            database.execute("select id from document_processing_stage_outbox where 1 = 0")
            layout_options = DOCLING_LAYOUT_OCR_V1.layout_ocr_options
            if (
                layout_options is None
                or DOCLING_LAYOUT_OCR_V1.profile_hash
                != DOCLING_LAYOUT_OCR_V1_PROFILE_HASH
                or layout_options["layout_schema"]
                != {
                    "name": "enterprise-agent.office-image-ocr-layout",
                    "version": "v1",
                }
                or tuple(DOCLING_LAYOUT_OCR_V1.output_kinds)
                != ("MARKDOWN", "DOCLING_JSON", "OCR_LAYOUT_JSON")
            ):
                raise ValueError("File Service layout OCR registry is invalid")
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
                "task_workspace_search_files",
            ):
                raise ValueError("File Tool Manifest is invalid")
            if document_processing_expected and document_processing is None:
                raise ValueError(
                    "File Service document processing is configured but was not composed"
                )
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
                    "layout_ocr_profile_registry": "ready",
                    "layout_ocr_schema": "ready",
                    "document_processing": (
                        "ready" if document_processing is not None else "not_configured"
                    ),
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

    def processing_service() -> DocumentProcessingOperations:
        if document_processing is None:
            raise FilePrincipalError(
                "Document processing is not configured",
                safe_message="文档处理服务尚未就绪",
                error_code="document_processing_not_ready",
            )
        return document_processing

    def processing_claims(request: Request, required_scope: str) -> dict[str, Any]:
        return service_principal.verify_processing(_bearer(request), required_scope=required_scope)

    async def processing_claim(request: Request) -> JSONResponse:
        try:
            claims = processing_claims(request, "internal:file-service:document-processing:claim")
            payload = await _request_json_exact(
                request,
                {
                    "contract_version",
                    "run_id",
                    "source_version_id",
                    "profile_hash",
                    "attempt",
                    "correlation_id",
                },
            )
            if str(payload["run_id"]) != str(request.path_params["run_id"]):
                raise FilePrincipalError(
                    "Document processing path and message identity differ",
                    safe_message="文档处理消息身份不匹配",
                    error_code="document_processing_message_mismatch",
                )
            result = await asyncio.to_thread(
                processing_service().claim,
                message=payload,
                service_principal_id=str(claims["sub"]),
            )
            return JSONResponse(_safe_result(result))
        except AppError as exc:
            return _safe_error(exc)

    async def processing_source_grant(request: Request) -> JSONResponse:
        try:
            claims = processing_claims(
                request, "internal:file-service:document-processing:source:read"
            )
            payload = await _request_json_exact(request, {"tenant_id"})
            result = await asyncio.to_thread(
                processing_service().prepare_source_stream,
                run_id=str(request.path_params["run_id"]),
                tenant_id=str(payload["tenant_id"]),
                service_principal_id=str(claims["sub"]),
            )
            return JSONResponse(_safe_result(result))
        except AppError as exc:
            return _safe_error(exc)

    async def processing_source_content(
        request: Request,
    ) -> StreamingResponse | JSONResponse:
        try:
            claims = processing_claims(
                request, "internal:file-service:document-processing:source:read"
            )
            grant = str(request.headers.get("x-document-source-grant") or "")
            if not grant or len(grant) > 4096:
                raise FilePrincipalError(
                    "Document source grant is missing",
                    safe_message="文档原件读取授权缺失",
                    error_code="document_source_grant_missing",
                )
            stream = await asyncio.to_thread(
                processing_service().open_source_stream,
                grant=grant,
                service_principal_id=str(claims["sub"]),
            )

            async def content() -> AsyncIterator[bytes]:
                try:
                    while True:
                        chunk = await asyncio.to_thread(stream.read, 64 * 1024)
                        if not chunk:
                            break
                        yield chunk
                finally:
                    await asyncio.to_thread(stream.close)

            return StreamingResponse(content(), media_type="application/octet-stream")
        except AppError as exc:
            return _safe_error(exc)

    async def processing_submitted(request: Request) -> JSONResponse:
        try:
            processing_claims(request, "internal:file-service:document-processing:claim")
            payload = await _request_json_exact(request, {"external_task_id"})
            result = await asyncio.to_thread(
                processing_service().mark_submitted,
                run_id=str(request.path_params["run_id"]),
                external_task_id=str(payload["external_task_id"]),
            )
            return JSONResponse(_safe_processing_run(result))
        except AppError as exc:
            return _safe_error(exc)

    async def representation_prepare(request: Request) -> JSONResponse:
        try:
            processing_claims(
                request,
                "internal:file-service:document-processing:representation:write",
            )
            payload = await _request_json_exact(request, {"expected_size_bytes", "expected_sha256"})
            result = await asyncio.to_thread(
                processing_service().prepare_representation_transfer,
                run_id=str(request.path_params["run_id"]),
                kind=str(request.path_params["kind"]),
                expected_size_bytes=int(payload["expected_size_bytes"]),
                expected_sha256=str(payload["expected_sha256"]),
            )
            return JSONResponse(_safe_result(result))
        except AppError as exc:
            return _safe_error(exc)

    async def representation_upload(request: Request) -> JSONResponse:
        try:
            processing_claims(
                request,
                "internal:file-service:document-processing:representation:write",
            )
            upload_token = str(request.headers.get("x-representation-upload-token") or "")
            if not upload_token or len(upload_token) > 4096:
                raise FilePrincipalError(
                    "Representation upload token is missing",
                    safe_message="派生表示上传授权缺失",
                    error_code="document_representation_upload_token_missing",
                )
            staged = tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b")
            size = 0
            try:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > DOCLING_TEXT_V1.max_docling_json_bytes:
                        raise FilePrincipalError(
                            "Representation request exceeds the size bound",
                            safe_message="派生表示超过大小上限",
                            error_code="document_representation_size_exceeded",
                        )
                    staged.write(chunk)
                staged.seek(0)
                result = await asyncio.to_thread(
                    processing_service().upload_representation,
                    transfer_id=str(request.path_params["transfer_id"]),
                    upload_token=upload_token,
                    stream=staged,
                    media_type=str(
                        request.headers.get("content-type") or "application/octet-stream"
                    ),
                )
            finally:
                staged.close()
            return JSONResponse(
                _safe_result(
                    {
                        "transfer_id": str(result["id"]),
                        "kind": str(result["kind"]),
                        "status": str(result["status"]),
                    }
                )
            )
        except AppError as exc:
            return _safe_error(exc)

    async def parent_artifact_prepare(request: Request) -> JSONResponse:
        try:
            processing_claims(
                request, "internal:file-service:document-processing:representation:write"
            )
            payload = await _request_json_exact(request, {"expected_size_bytes", "expected_sha256"})
            result = await asyncio.to_thread(
                processing_service().prepare_parent_artifact_transfer,
                run_id=str(request.path_params["run_id"]),
                expected_size_bytes=int(payload["expected_size_bytes"]),
                expected_sha256=str(payload["expected_sha256"]),
            )
            return JSONResponse(_safe_result(result))
        except AppError as exc:
            return _safe_error(exc)

    async def parent_artifact_upload(request: Request) -> JSONResponse:
        try:
            processing_claims(
                request, "internal:file-service:document-processing:representation:write"
            )
            token = str(request.headers.get("x-parent-artifact-upload-token") or "")
            if not token or len(token) > 4096:
                raise FilePrincipalError(
                    "Parent artifact upload token is missing",
                    safe_message="父Markdown上传授权缺失",
                    error_code="document_parent_artifact_upload_token_missing",
                )
            staged = tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b")
            try:
                async for chunk in request.stream():
                    staged.write(chunk)
                staged.seek(0)
                result = await asyncio.to_thread(
                    processing_service().upload_parent_artifact,
                    transfer_id=str(request.path_params["transfer_id"]),
                    upload_token=token,
                    stream=staged,
                )
            finally:
                staged.close()
            return JSONResponse(
                _safe_result({"transfer_id": str(result["id"]), "status": str(result["status"])})
            )
        except AppError as exc:
            return _safe_error(exc)

    async def parent_artifact_content(request: Request) -> StreamingResponse | JSONResponse:
        try:
            processing_claims(request, "internal:file-service:document-processing:source:read")
            stream = await asyncio.to_thread(
                processing_service().open_parent_artifact,
                run_id=str(request.path_params["run_id"]),
            )

            async def content() -> AsyncIterator[bytes]:
                try:
                    while chunk := await asyncio.to_thread(stream.read, 64 * 1024):
                        yield chunk
                finally:
                    await asyncio.to_thread(stream.close)

            return StreamingResponse(content(), media_type="text/markdown")
        except AppError as exc:
            return _safe_error(exc)

    async def picture_asset_prepare(request: Request) -> JSONResponse:
        try:
            processing_claims(
                request, "internal:file-service:document-processing:representation:write"
            )
            payload = await _request_json_exact(
                request,
                {
                    "normalized_sha256",
                    "media_type",
                    "original_width_pixels",
                    "original_height_pixels",
                    "width_pixels",
                    "height_pixels",
                    "normalization_transform",
                    "size_bytes",
                },
            )
            result = await asyncio.to_thread(
                processing_service().prepare_picture_asset_transfer,
                run_id=str(request.path_params["run_id"]),
                normalized_sha256=str(payload["normalized_sha256"]),
                media_type=str(payload["media_type"]),
                original_width_pixels=int(payload["original_width_pixels"]),
                original_height_pixels=int(payload["original_height_pixels"]),
                width_pixels=int(payload["width_pixels"]),
                height_pixels=int(payload["height_pixels"]),
                normalization_transform=dict(payload["normalization_transform"]),
                size_bytes=int(payload["size_bytes"]),
            )
            return JSONResponse(_safe_result(result))
        except AppError as exc:
            return _safe_error(exc)

    async def picture_asset_upload(request: Request) -> JSONResponse:
        try:
            processing_claims(
                request, "internal:file-service:document-processing:representation:write"
            )
            token = str(request.headers.get("x-picture-asset-upload-token") or "")
            if not token or len(token) > 4096:
                raise FilePrincipalError(
                    "Picture asset upload token is missing",
                    safe_message="图片asset上传授权缺失",
                    error_code="document_picture_asset_upload_token_missing",
                )
            staged = tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b")
            try:
                async for chunk in request.stream():
                    staged.write(chunk)
                staged.seek(0)
                result = await asyncio.to_thread(
                    processing_service().upload_picture_asset,
                    transfer_id=str(request.path_params["transfer_id"]),
                    upload_token=token,
                    stream=staged,
                    media_type=str(request.headers.get("content-type") or ""),
                )
            finally:
                staged.close()
            return JSONResponse(
                _safe_result(
                    {
                        "picture_asset_id": str(result["id"]),
                        "status": str(result["status"]),
                    }
                )
            )
        except AppError as exc:
            return _safe_error(exc)

    async def picture_occurrence_register(request: Request) -> JSONResponse:
        try:
            processing_claims(request, "internal:file-service:document-processing:claim")
            payload = await _request_json_exact(
                request,
                {
                    "picture_asset_id",
                    "occurrence_index",
                    "source_format",
                    "picture_ref",
                    "parent_ref",
                    "parent_label",
                    "parent_ordinal",
                    "slide_no",
                    "parent_bbox",
                    "selection_status",
                },
            )
            result = await asyncio.to_thread(
                processing_service().register_picture_occurrence,
                run_id=str(request.path_params["run_id"]),
                picture_asset_id=str(payload["picture_asset_id"]),
                occurrence_index=int(payload["occurrence_index"]),
                source_format=str(payload["source_format"]),
                picture_ref=str(payload["picture_ref"]),
                parent_ref=str(payload["parent_ref"]),
                parent_label=str(payload["parent_label"]),
                parent_ordinal=int(payload["parent_ordinal"]),
                slide_no=_optional_int(payload["slide_no"]),
                parent_bbox=payload["parent_bbox"],
                selection_status=str(payload["selection_status"]),
            )
            return JSONResponse(
                _safe_result(
                    {
                        "occurrence_id": str(result["id"]),
                        "occurrence_index": int(result["occurrence_index"]),
                    }
                )
            )
        except AppError as exc:
            return _safe_error(exc)

    async def picture_item_register(request: Request) -> JSONResponse:
        try:
            processing_claims(request, "internal:file-service:document-processing:claim")
            payload = await _request_json_exact(
                request,
                {
                    "picture_asset_id",
                    "occurrence_count",
                    "ocr_engine_code",
                    "model_revision",
                    "model_digest",
                    "correlation_id",
                },
            )
            result = await asyncio.to_thread(
                processing_service().register_picture_item,
                run_id=str(request.path_params["run_id"]),
                picture_asset_id=str(payload["picture_asset_id"]),
                occurrence_count=int(payload["occurrence_count"]),
                ocr_engine_code=str(payload["ocr_engine_code"]),
                model_revision=str(payload["model_revision"]),
                model_digest=str(payload["model_digest"]),
                correlation_id=str(payload["correlation_id"]),
            )
            return JSONResponse(
                _safe_result(
                    {
                        "picture_item_id": str(result["id"]),
                        "status": str(result["status"]),
                    }
                )
            )
        except AppError as exc:
            return _safe_error(exc)

    async def picture_item_claim(request: Request) -> JSONResponse:
        try:
            processing_claims(request, "internal:file-service:document-processing:claim")
            payload = await _request_json_exact(request, {"claim_token", "claim_expires_at"})
            item, claimed = await asyncio.to_thread(
                processing_service().claim_picture_item,
                picture_item_id=str(request.path_params["picture_item_id"]),
                claim_token=str(payload["claim_token"]),
                claim_expires_at=str(payload["claim_expires_at"]),
            )
            result = await asyncio.to_thread(
                processing_service().picture_item_context,
                picture_item_id=str(item["id"]),
                claimed=claimed,
            )
            return JSONResponse(_safe_result(result))
        except AppError as exc:
            return _safe_error(exc)

    async def picture_asset_content(request: Request) -> StreamingResponse | JSONResponse:
        try:
            processing_claims(request, "internal:file-service:document-processing:source:read")
            stream = await asyncio.to_thread(
                processing_service().open_picture_asset,
                picture_item_id=str(request.path_params["picture_item_id"]),
            )

            async def content() -> AsyncIterator[bytes]:
                try:
                    while chunk := await asyncio.to_thread(stream.read, 64 * 1024):
                        yield chunk
                finally:
                    await asyncio.to_thread(stream.close)

            return StreamingResponse(content(), media_type="application/octet-stream")
        except AppError as exc:
            return _safe_error(exc)

    async def picture_item_submitted(request: Request) -> JSONResponse:
        try:
            processing_claims(request, "internal:file-service:document-processing:claim")
            payload = await _request_json_exact(request, {"external_task_id"})
            result = await asyncio.to_thread(
                processing_service().mark_picture_submitted,
                picture_item_id=str(request.path_params["picture_item_id"]),
                external_task_id=str(payload["external_task_id"]),
            )
            return JSONResponse(
                _safe_result(
                    {"picture_item_id": str(result["id"]), "status": str(result["status"])}
                )
            )
        except AppError as exc:
            return _safe_error(exc)

    async def picture_result_prepare(request: Request) -> JSONResponse:
        try:
            processing_claims(
                request, "internal:file-service:document-processing:representation:write"
            )
            payload = await _request_json_exact(request, {"expected_size_bytes", "expected_sha256"})
            result = await asyncio.to_thread(
                processing_service().prepare_picture_result_transfer,
                picture_item_id=str(request.path_params["picture_item_id"]),
                expected_size_bytes=int(payload["expected_size_bytes"]),
                expected_sha256=str(payload["expected_sha256"]),
            )
            return JSONResponse(_safe_result(result))
        except AppError as exc:
            return _safe_error(exc)

    async def picture_result_upload(request: Request) -> JSONResponse:
        try:
            processing_claims(
                request, "internal:file-service:document-processing:representation:write"
            )
            token = str(request.headers.get("x-picture-result-upload-token") or "")
            if not token or len(token) > 4096:
                raise FilePrincipalError(
                    "Picture result upload token is missing",
                    safe_message="图片OCR结果上传授权缺失",
                    error_code="document_picture_result_upload_token_missing",
                )
            staged = tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b")
            try:
                async for chunk in request.stream():
                    staged.write(chunk)
                staged.seek(0)
                result = await asyncio.to_thread(
                    processing_service().upload_picture_result,
                    transfer_id=str(request.path_params["transfer_id"]),
                    upload_token=token,
                    stream=staged,
                )
            finally:
                staged.close()
            return JSONResponse(
                _safe_result({"transfer_id": str(result["id"]), "status": str(result["status"])})
            )
        except AppError as exc:
            return _safe_error(exc)

    async def picture_result_content(request: Request) -> StreamingResponse | JSONResponse:
        try:
            processing_claims(request, "internal:file-service:document-processing:source:read")
            stream = await asyncio.to_thread(
                processing_service().open_picture_result,
                picture_item_id=str(request.path_params["picture_item_id"]),
            )

            async def content() -> AsyncIterator[bytes]:
                try:
                    while chunk := await asyncio.to_thread(stream.read, 64 * 1024):
                        yield chunk
                finally:
                    await asyncio.to_thread(stream.close)

            return StreamingResponse(content(), media_type="application/json")
        except AppError as exc:
            return _safe_error(exc)

    async def picture_item_complete(request: Request) -> JSONResponse:
        try:
            processing_claims(request, "internal:file-service:document-processing:complete")
            payload = await _request_json_exact(
                request,
                {
                    "status",
                    "result_size_bytes",
                    "result_sha256",
                    "error_code",
                    "correlation_id",
                },
            )
            result = await asyncio.to_thread(
                processing_service().complete_picture_item,
                picture_item_id=str(request.path_params["picture_item_id"]),
                status=str(payload["status"]),
                result_size_bytes=_optional_int(payload["result_size_bytes"]),
                result_sha256=str(payload["result_sha256"]),
                error_code=str(payload["error_code"]),
                correlation_id=str(payload["correlation_id"]),
            )
            return JSONResponse(
                _safe_result(
                    {"picture_item_id": str(result["id"]), "status": str(result["status"])}
                )
            )
        except AppError as exc:
            return _safe_error(exc)

    async def picture_item_retry(request: Request) -> JSONResponse:
        try:
            processing_claims(request, "internal:file-service:document-processing:complete")
            payload = await _request_json_exact(request, {"error_code", "delay_seconds"})
            result = await asyncio.to_thread(
                processing_service().retry_picture_item,
                picture_item_id=str(request.path_params["picture_item_id"]),
                error_code=str(payload["error_code"]),
                delay_seconds=int(payload["delay_seconds"]),
            )
            return JSONResponse(
                _safe_result(
                    {"picture_item_id": str(result["id"]), "status": str(result["status"])}
                )
            )
        except AppError as exc:
            return _safe_error(exc)

    async def parent_parse_complete(request: Request) -> JSONResponse:
        try:
            processing_claims(request, "internal:file-service:document-processing:complete")
            payload = await _request_json_exact(request, {"correlation_id"})
            result = await asyncio.to_thread(
                processing_service().complete_parent_parse,
                run_id=str(request.path_params["run_id"]),
                correlation_id=str(payload["correlation_id"]),
            )
            return JSONResponse(_safe_processing_run(result))
        except AppError as exc:
            return _safe_error(exc)

    async def assembly_claim(request: Request) -> JSONResponse:
        try:
            processing_claims(request, "internal:file-service:document-processing:claim")
            payload = await _request_json_exact(request, {"claim_token"})
            run, claimed = await asyncio.to_thread(
                processing_service().claim_assembly,
                run_id=str(request.path_params["run_id"]),
                claim_token=str(payload["claim_token"]),
            )
            return JSONResponse(
                _safe_result(
                    {
                        "run_id": str(run["id"]),
                        "profile_hash": str(run["profile_hash"]),
                        "assembly_status": str(run["assembly_status"]),
                        "assembly_attempt": int(run["assembly_attempt"]),
                        "claimed": claimed,
                    }
                )
            )
        except AppError as exc:
            return _safe_error(exc)

    async def assembly_context(request: Request) -> JSONResponse:
        try:
            processing_claims(request, "internal:file-service:document-processing:source:read")
            result = await asyncio.to_thread(
                processing_service().assembly_context,
                run_id=str(request.path_params["run_id"]),
            )
            return JSONResponse(_safe_result(result))
        except AppError as exc:
            return _safe_error(exc)

    async def assembly_finish(request: Request) -> JSONResponse:
        try:
            processing_claims(request, "internal:file-service:document-processing:complete")
            payload = await _request_json_exact(request, {"succeeded"})
            result = await asyncio.to_thread(
                processing_service().finish_assembly,
                run_id=str(request.path_params["run_id"]),
                succeeded=bool(payload["succeeded"]),
            )
            return JSONResponse(_safe_processing_run(result))
        except AppError as exc:
            return _safe_error(exc)

    async def assembly_retry(request: Request) -> JSONResponse:
        try:
            processing_claims(request, "internal:file-service:document-processing:complete")
            payload = await _request_json_exact(request, set())
            del payload
            result = await asyncio.to_thread(
                processing_service().retry_assembly,
                run_id=str(request.path_params["run_id"]),
            )
            return JSONResponse(_safe_processing_run(result))
        except AppError as exc:
            return _safe_error(exc)

    async def processing_finalize(request: Request) -> JSONResponse:
        try:
            processing_claims(request, "internal:file-service:document-processing:complete")
            payload = await _request_json_exact(
                request, {"partial", "page_count", "processing_time_ms"}
            )
            representations = await asyncio.to_thread(
                processing_service().finalize,
                run_id=str(request.path_params["run_id"]),
                partial=bool(payload["partial"]),
                page_count=_optional_int(payload["page_count"]),
                processing_time_ms=_optional_int(payload["processing_time_ms"]),
            )
            return JSONResponse(
                {
                    "representations": [
                        {
                            "id": str(item["id"]),
                            "kind": str(item["kind"]),
                            "status": str(item["status"]),
                            "size_bytes": int(item["size_bytes"]),
                            "content_sha256": str(item["content_sha256"]),
                        }
                        for item in representations
                    ]
                }
            )
        except AppError as exc:
            return _safe_error(exc)

    async def processing_no_text(request: Request) -> JSONResponse:
        try:
            processing_claims(request, "internal:file-service:document-processing:complete")
            payload = await _request_json_exact(request, {"page_count", "processing_time_ms"})
            result = await asyncio.to_thread(
                processing_service().complete_without_text,
                run_id=str(request.path_params["run_id"]),
                page_count=_optional_int(payload["page_count"]),
                processing_time_ms=_optional_int(payload["processing_time_ms"]),
            )
            return JSONResponse(_safe_processing_run(result))
        except AppError as exc:
            return _safe_error(exc)

    async def processing_retry(request: Request) -> JSONResponse:
        try:
            processing_claims(request, "internal:file-service:document-processing:complete")
            payload = await _request_json_exact(request, {"error_code", "delay_seconds"})
            result = await asyncio.to_thread(
                processing_service().schedule_retry,
                run_id=str(request.path_params["run_id"]),
                error_code=str(payload["error_code"]),
                delay_seconds=int(payload["delay_seconds"]),
            )
            return JSONResponse(_safe_processing_run(result))
        except AppError as exc:
            return _safe_error(exc)

    async def processing_fail(request: Request) -> JSONResponse:
        try:
            processing_claims(request, "internal:file-service:document-processing:complete")
            payload = await _request_json_exact(request, {"error_code", "processing_time_ms"})
            result = await asyncio.to_thread(
                processing_service().fail,
                run_id=str(request.path_params["run_id"]),
                error_code=str(payload["error_code"]),
                processing_time_ms=_optional_int(payload["processing_time_ms"]),
            )
            return JSONResponse(_safe_processing_run(result))
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
            Route(
                "/internal/v1/document-processing/runs/{run_id}/claim",
                processing_claim,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/document-processing/runs/{run_id}/source-grant",
                processing_source_grant,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/document-processing/runs/{run_id}/source",
                processing_source_content,
                methods=["GET"],
            ),
            Route(
                "/internal/v1/document-processing/runs/{run_id}/submitted",
                processing_submitted,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/document-processing/runs/{run_id}/representations/{kind}/prepare",
                representation_prepare,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/document-processing/transfers/{transfer_id}/content",
                representation_upload,
                methods=["PUT"],
            ),
            Route(
                "/internal/v1/document-processing/runs/{run_id}/parent-artifact/prepare",
                parent_artifact_prepare,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/document-processing/parent-artifact-transfers/{transfer_id}/content",
                parent_artifact_upload,
                methods=["PUT"],
            ),
            Route(
                "/internal/v1/document-processing/runs/{run_id}/parent-artifact",
                parent_artifact_content,
                methods=["GET"],
            ),
            Route(
                "/internal/v1/document-processing/runs/{run_id}/picture-assets/prepare",
                picture_asset_prepare,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/document-processing/picture-asset-transfers/{transfer_id}/content",
                picture_asset_upload,
                methods=["PUT"],
            ),
            Route(
                "/internal/v1/document-processing/runs/{run_id}/picture-occurrences",
                picture_occurrence_register,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/document-processing/runs/{run_id}/picture-items",
                picture_item_register,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/document-processing/picture-items/{picture_item_id}/claim",
                picture_item_claim,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/document-processing/picture-items/{picture_item_id}/asset",
                picture_asset_content,
                methods=["GET"],
            ),
            Route(
                "/internal/v1/document-processing/picture-items/{picture_item_id}/submitted",
                picture_item_submitted,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/document-processing/picture-items/{picture_item_id}/result/prepare",
                picture_result_prepare,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/document-processing/picture-result-transfers/{transfer_id}/content",
                picture_result_upload,
                methods=["PUT"],
            ),
            Route(
                "/internal/v1/document-processing/picture-items/{picture_item_id}/result",
                picture_result_content,
                methods=["GET"],
            ),
            Route(
                "/internal/v1/document-processing/picture-items/{picture_item_id}/complete",
                picture_item_complete,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/document-processing/picture-items/{picture_item_id}/retry",
                picture_item_retry,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/document-processing/runs/{run_id}/parent-complete",
                parent_parse_complete,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/document-processing/runs/{run_id}/assembly/claim",
                assembly_claim,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/document-processing/runs/{run_id}/assembly/context",
                assembly_context,
                methods=["GET"],
            ),
            Route(
                "/internal/v1/document-processing/runs/{run_id}/assembly/finish",
                assembly_finish,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/document-processing/runs/{run_id}/assembly/retry",
                assembly_retry,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/document-processing/runs/{run_id}/finalize",
                processing_finalize,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/document-processing/runs/{run_id}/no-text",
                processing_no_text,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/document-processing/runs/{run_id}/retry",
                processing_retry,
                methods=["POST"],
            ),
            Route(
                "/internal/v1/document-processing/runs/{run_id}/fail",
                processing_fail,
                methods=["POST"],
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


async def _request_json_exact(
    request: Request,
    required_fields: set[str],
) -> dict[str, Any]:
    content_type = str(request.headers.get("content-type") or "").split(";", 1)[0]
    if content_type != "application/json":
        raise FilePrincipalError(
            "Document processing request media type is invalid",
            safe_message="文档处理请求媒体类型无效",
            error_code="document_processing_request_media_type_invalid",
        )
    raw = await request.body()
    if not raw or len(raw) > 16 * 1024:
        raise FilePrincipalError(
            "Document processing request size is invalid",
            safe_message="文档处理请求大小无效",
            error_code="document_processing_request_size_invalid",
        )
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FilePrincipalError(
            "Document processing request JSON is invalid",
            safe_message="文档处理请求无效",
            error_code="document_processing_request_json_invalid",
        ) from exc
    if not isinstance(value, dict) or set(value) != required_fields:
        raise FilePrincipalError(
            "Document processing request schema is invalid",
            safe_message="文档处理请求结构无效",
            error_code="document_processing_request_schema_invalid",
        )
    return value


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise FilePrincipalError(
            "Document processing metric is invalid",
            safe_message="文档处理指标无效",
            error_code="document_processing_metric_invalid",
        )
    return value


def _safe_processing_run(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": str(value["id"]),
        "status": str(value["status"]),
        "attempt": int(value["attempt"]),
        "error_code": str(value["error_code"] or ""),
        "external_task_id": str(value["external_task_id"] or ""),
    }


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
