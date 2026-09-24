from __future__ import annotations

import asyncio
import tempfile
from collections.abc import AsyncIterator

from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

from app.shared.exceptions import AppError
from services.file_service.auth import FilePrincipalError
from services.file_service.internal_http import (
    optional_int,
    request_json_exact,
    safe_error,
    safe_result,
)
from services.file_service.processing_routes import ProcessingAccess


class DocumentPictureRoutes:
    def __init__(self, access: ProcessingAccess) -> None:
        self._access = access

    async def picture_asset_prepare(self, request: Request) -> JSONResponse:
        try:
            self._access.claims(
                request, "internal:file-service:document-processing:representation:write"
            )
            payload = await request_json_exact(
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
                self._access.service().prepare_picture_asset_transfer,
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
            return JSONResponse(safe_result(result))
        except AppError as exc:
            return safe_error(exc)

    async def picture_asset_upload(self, request: Request) -> JSONResponse:
        try:
            self._access.claims(
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
                    self._access.service().upload_picture_asset,
                    transfer_id=str(request.path_params["transfer_id"]),
                    upload_token=token,
                    stream=staged,
                    media_type=str(request.headers.get("content-type") or ""),
                )
            finally:
                staged.close()
            return JSONResponse(
                safe_result(
                    {
                        "picture_asset_id": str(result["id"]),
                        "status": str(result["status"]),
                    }
                )
            )
        except AppError as exc:
            return safe_error(exc)

    async def picture_occurrence_register(self, request: Request) -> JSONResponse:
        try:
            self._access.claims(request, "internal:file-service:document-processing:claim")
            payload = await request_json_exact(
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
                self._access.service().register_picture_occurrence,
                run_id=str(request.path_params["run_id"]),
                picture_asset_id=str(payload["picture_asset_id"]),
                occurrence_index=int(payload["occurrence_index"]),
                source_format=str(payload["source_format"]),
                picture_ref=str(payload["picture_ref"]),
                parent_ref=str(payload["parent_ref"]),
                parent_label=str(payload["parent_label"]),
                parent_ordinal=int(payload["parent_ordinal"]),
                slide_no=optional_int(payload["slide_no"]),
                parent_bbox=payload["parent_bbox"],
                selection_status=str(payload["selection_status"]),
            )
            return JSONResponse(
                safe_result(
                    {
                        "occurrence_id": str(result["id"]),
                        "occurrence_index": int(result["occurrence_index"]),
                    }
                )
            )
        except AppError as exc:
            return safe_error(exc)

    async def picture_item_register(self, request: Request) -> JSONResponse:
        try:
            self._access.claims(request, "internal:file-service:document-processing:claim")
            payload = await request_json_exact(
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
                self._access.service().register_picture_item,
                run_id=str(request.path_params["run_id"]),
                picture_asset_id=str(payload["picture_asset_id"]),
                occurrence_count=int(payload["occurrence_count"]),
                ocr_engine_code=str(payload["ocr_engine_code"]),
                model_revision=str(payload["model_revision"]),
                model_digest=str(payload["model_digest"]),
                correlation_id=str(payload["correlation_id"]),
            )
            return JSONResponse(
                safe_result(
                    {
                        "picture_item_id": str(result["id"]),
                        "status": str(result["status"]),
                    }
                )
            )
        except AppError as exc:
            return safe_error(exc)

    async def picture_item_claim(self, request: Request) -> JSONResponse:
        try:
            self._access.claims(request, "internal:file-service:document-processing:claim")
            payload = await request_json_exact(request, {"claim_token", "claim_expires_at"})
            item, claimed = await asyncio.to_thread(
                self._access.service().claim_picture_item,
                picture_item_id=str(request.path_params["picture_item_id"]),
                claim_token=str(payload["claim_token"]),
                claim_expires_at=str(payload["claim_expires_at"]),
            )
            result = await asyncio.to_thread(
                self._access.service().picture_item_context,
                picture_item_id=str(item["id"]),
                claimed=claimed,
            )
            return JSONResponse(safe_result(result))
        except AppError as exc:
            return safe_error(exc)

    async def picture_asset_content(self, request: Request) -> StreamingResponse | JSONResponse:
        try:
            self._access.claims(request, "internal:file-service:document-processing:source:read")
            stream = await asyncio.to_thread(
                self._access.service().open_picture_asset,
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
            return safe_error(exc)

    async def picture_item_submitted(self, request: Request) -> JSONResponse:
        try:
            self._access.claims(request, "internal:file-service:document-processing:claim")
            payload = await request_json_exact(request, {"external_task_id"})
            result = await asyncio.to_thread(
                self._access.service().mark_picture_submitted,
                picture_item_id=str(request.path_params["picture_item_id"]),
                external_task_id=str(payload["external_task_id"]),
            )
            return JSONResponse(
                safe_result({"picture_item_id": str(result["id"]), "status": str(result["status"])})
            )
        except AppError as exc:
            return safe_error(exc)

    async def picture_result_prepare(self, request: Request) -> JSONResponse:
        try:
            self._access.claims(
                request, "internal:file-service:document-processing:representation:write"
            )
            payload = await request_json_exact(request, {"expected_size_bytes", "expected_sha256"})
            result = await asyncio.to_thread(
                self._access.service().prepare_picture_result_transfer,
                picture_item_id=str(request.path_params["picture_item_id"]),
                expected_size_bytes=int(payload["expected_size_bytes"]),
                expected_sha256=str(payload["expected_sha256"]),
            )
            return JSONResponse(safe_result(result))
        except AppError as exc:
            return safe_error(exc)

    async def picture_result_upload(self, request: Request) -> JSONResponse:
        try:
            self._access.claims(
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
                    self._access.service().upload_picture_result,
                    transfer_id=str(request.path_params["transfer_id"]),
                    upload_token=token,
                    stream=staged,
                )
            finally:
                staged.close()
            return JSONResponse(
                safe_result({"transfer_id": str(result["id"]), "status": str(result["status"])})
            )
        except AppError as exc:
            return safe_error(exc)

    async def picture_result_content(self, request: Request) -> StreamingResponse | JSONResponse:
        try:
            self._access.claims(request, "internal:file-service:document-processing:source:read")
            stream = await asyncio.to_thread(
                self._access.service().open_picture_result,
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
            return safe_error(exc)

    async def picture_item_complete(self, request: Request) -> JSONResponse:
        try:
            self._access.claims(request, "internal:file-service:document-processing:complete")
            payload = await request_json_exact(
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
                self._access.service().complete_picture_item,
                picture_item_id=str(request.path_params["picture_item_id"]),
                status=str(payload["status"]),
                result_size_bytes=optional_int(payload["result_size_bytes"]),
                result_sha256=str(payload["result_sha256"]),
                error_code=str(payload["error_code"]),
                correlation_id=str(payload["correlation_id"]),
            )
            return JSONResponse(
                safe_result({"picture_item_id": str(result["id"]), "status": str(result["status"])})
            )
        except AppError as exc:
            return safe_error(exc)

    async def picture_item_retry(self, request: Request) -> JSONResponse:
        try:
            self._access.claims(request, "internal:file-service:document-processing:complete")
            payload = await request_json_exact(request, {"error_code", "delay_seconds"})
            result = await asyncio.to_thread(
                self._access.service().retry_picture_item,
                picture_item_id=str(request.path_params["picture_item_id"]),
                error_code=str(payload["error_code"]),
                delay_seconds=int(payload["delay_seconds"]),
            )
            return JSONResponse(
                safe_result({"picture_item_id": str(result["id"]), "status": str(result["status"])})
            )
        except AppError as exc:
            return safe_error(exc)
