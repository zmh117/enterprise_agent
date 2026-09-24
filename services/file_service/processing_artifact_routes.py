from __future__ import annotations

import asyncio
import tempfile

from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

from app.modules.document_processing.profile import DOCLING_LAYOUT_OCR_V2
from services.file_service.auth import FilePrincipalError
from services.file_service.internal_http import (
    denial_on_app_error,
    iter_blocking_stream,
    request_json_exact,
    safe_processing_run,
    safe_result,
    staged_request_body,
)
from services.file_service.processing_routes import ProcessingAccess


class DocumentArtifactRoutes:
    def __init__(self, access: ProcessingAccess) -> None:
        self._access = access

    @denial_on_app_error
    async def representation_prepare(self, request: Request) -> JSONResponse:
        self._access.claims(
            request,
            "internal:file-service:document-processing:representation:write",
        )
        payload = await request_json_exact(request, {"expected_size_bytes", "expected_sha256"})
        result = await asyncio.to_thread(
            self._access.service().prepare_representation_transfer,
            run_id=str(request.path_params["run_id"]),
            kind=str(request.path_params["kind"]),
            expected_size_bytes=int(payload["expected_size_bytes"]),
            expected_sha256=str(payload["expected_sha256"]),
        )
        return JSONResponse(safe_result(result))

    @denial_on_app_error
    async def representation_upload(self, request: Request) -> JSONResponse:
        self._access.claims(
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
                if size > DOCLING_LAYOUT_OCR_V2.max_docling_json_bytes:
                    raise FilePrincipalError(
                        "Representation request exceeds the size bound",
                        safe_message="派生表示超过大小上限",
                        error_code="document_representation_size_exceeded",
                    )
                staged.write(chunk)
            staged.seek(0)
            result = await asyncio.to_thread(
                self._access.service().upload_representation,
                transfer_id=str(request.path_params["transfer_id"]),
                upload_token=upload_token,
                stream=staged,
                media_type=str(request.headers.get("content-type") or "application/octet-stream"),
            )
        finally:
            staged.close()
        return JSONResponse(
            safe_result(
                {
                    "transfer_id": str(result["id"]),
                    "kind": str(result["kind"]),
                    "status": str(result["status"]),
                }
            )
        )

    @denial_on_app_error
    async def parent_artifact_prepare(self, request: Request) -> JSONResponse:
        self._access.claims(
            request, "internal:file-service:document-processing:representation:write"
        )
        payload = await request_json_exact(request, {"expected_size_bytes", "expected_sha256"})
        result = await asyncio.to_thread(
            self._access.service().prepare_parent_artifact_transfer,
            run_id=str(request.path_params["run_id"]),
            expected_size_bytes=int(payload["expected_size_bytes"]),
            expected_sha256=str(payload["expected_sha256"]),
        )
        return JSONResponse(safe_result(result))

    @denial_on_app_error
    async def parent_artifact_upload(self, request: Request) -> JSONResponse:
        self._access.claims(
            request, "internal:file-service:document-processing:representation:write"
        )
        token = str(request.headers.get("x-parent-artifact-upload-token") or "")
        if not token or len(token) > 4096:
            raise FilePrincipalError(
                "Parent artifact upload token is missing",
                safe_message="父Markdown上传授权缺失",
                error_code="document_parent_artifact_upload_token_missing",
            )
        async with staged_request_body(request) as staged:
            result = await asyncio.to_thread(
                self._access.service().upload_parent_artifact,
                transfer_id=str(request.path_params["transfer_id"]),
                upload_token=token,
                stream=staged,
            )
        return JSONResponse(
            safe_result({"transfer_id": str(result["id"]), "status": str(result["status"])})
        )

    @denial_on_app_error
    async def parent_artifact_content(self, request: Request) -> StreamingResponse:
        self._access.claims(request, "internal:file-service:document-processing:source:read")
        stream = await asyncio.to_thread(
            self._access.service().open_parent_artifact,
            run_id=str(request.path_params["run_id"]),
        )
        return StreamingResponse(iter_blocking_stream(stream), media_type="text/markdown")

    @denial_on_app_error
    async def parent_parse_complete(self, request: Request) -> JSONResponse:
        self._access.claims(request, "internal:file-service:document-processing:complete")
        payload = await request_json_exact(request, {"correlation_id"})
        result = await asyncio.to_thread(
            self._access.service().complete_parent_parse,
            run_id=str(request.path_params["run_id"]),
            correlation_id=str(payload["correlation_id"]),
        )
        return JSONResponse(safe_processing_run(result))

    @denial_on_app_error
    async def assembly_claim(self, request: Request) -> JSONResponse:
        self._access.claims(request, "internal:file-service:document-processing:claim")
        payload = await request_json_exact(request, {"claim_token"})
        run, claimed = await asyncio.to_thread(
            self._access.service().claim_assembly,
            run_id=str(request.path_params["run_id"]),
            claim_token=str(payload["claim_token"]),
        )
        return JSONResponse(
            safe_result(
                {
                    "run_id": str(run["id"]),
                    "profile_hash": str(run["profile_hash"]),
                    "assembly_status": str(run["assembly_status"]),
                    "assembly_attempt": int(run["assembly_attempt"]),
                    "claimed": claimed,
                }
            )
        )

    @denial_on_app_error
    async def assembly_context(self, request: Request) -> JSONResponse:
        self._access.claims(request, "internal:file-service:document-processing:source:read")
        result = await asyncio.to_thread(
            self._access.service().assembly_context,
            run_id=str(request.path_params["run_id"]),
        )
        return JSONResponse(safe_result(result))

    @denial_on_app_error
    async def assembly_finish(self, request: Request) -> JSONResponse:
        self._access.claims(request, "internal:file-service:document-processing:complete")
        payload = await request_json_exact(request, {"succeeded"})
        result = await asyncio.to_thread(
            self._access.service().finish_assembly,
            run_id=str(request.path_params["run_id"]),
            succeeded=bool(payload["succeeded"]),
        )
        return JSONResponse(safe_processing_run(result))

    @denial_on_app_error
    async def assembly_retry(self, request: Request) -> JSONResponse:
        self._access.claims(request, "internal:file-service:document-processing:complete")
        payload = await request_json_exact(request, set())
        del payload
        result = await asyncio.to_thread(
            self._access.service().retry_assembly,
            run_id=str(request.path_params["run_id"]),
        )
        return JSONResponse(safe_processing_run(result))
