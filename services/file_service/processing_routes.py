from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, Protocol

from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

from app.shared.exceptions import AppError
from services.file_service.auth import FilePrincipalError, FileWorkerPrincipalVerifier
from services.file_service.internal_http import (
    bearer_token,
    optional_int,
    request_json_exact,
    safe_error,
    safe_processing_run,
    safe_result,
)


class DocumentProcessingOperations(Protocol):  # noqa: PLR0904
    def acquire_docling_slot(self, **values: Any) -> dict[str, Any]: ...

    def renew_docling_slot(self, **values: Any) -> dict[str, Any]: ...

    def release_docling_slot(self, **values: Any) -> dict[str, Any]: ...

    def quarantine_docling_slot(self, **values: Any) -> dict[str, Any]: ...

    def record_processing_worker_heartbeat(self, **values: Any) -> dict[str, Any]: ...

    def docling_concurrency_readiness(self) -> dict[str, Any]: ...

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


class ProcessingAccess:
    def __init__(
        self,
        *,
        service_principal: FileWorkerPrincipalVerifier,
        document_processing: DocumentProcessingOperations | None,
    ) -> None:
        self._service_principal = service_principal
        self._document_processing = document_processing

    def service(self) -> DocumentProcessingOperations:
        if self._document_processing is None:
            raise FilePrincipalError(
                "Document processing is not configured",
                safe_message="文档处理服务尚未就绪",
                error_code="document_processing_not_ready",
            )
        return self._document_processing

    def claims(self, request: Request, required_scope: str) -> dict[str, Any]:
        return self._service_principal.verify_processing(
            bearer_token(request), required_scope=required_scope
        )


class DocumentProcessingRunRoutes:
    def __init__(self, access: ProcessingAccess) -> None:
        self._access = access

    async def admission(self, request: Request) -> JSONResponse:
        try:
            claims = self._access.claims(
                request, "internal:file-service:document-processing:admission"
            )
            action = str(request.path_params["action"])
            fields = {"owner_kind", "owner_id", "worker_instance_id"}
            if action == "quarantine":
                fields.add("reason_code")
            if action not in {"acquire", "renew", "release", "quarantine"}:
                raise FilePrincipalError(
                    "Document processing admission action is invalid",
                    safe_message="文档处理并发槽位操作无效",
                    error_code="docling_slot_action_invalid",
                )
            payload = await request_json_exact(request, fields)
            values = {
                "owner_kind": str(payload["owner_kind"]),
                "owner_id": str(payload["owner_id"]),
                "worker_instance_id": str(payload["worker_instance_id"]),
                "service_principal_id": str(claims["sub"]),
            }
            if action == "quarantine":
                values["reason_code"] = str(payload["reason_code"])
            operation = getattr(self._access.service(), f"{action}_docling_slot")
            result = await asyncio.to_thread(operation, **values)
            return JSONResponse(safe_result(result))
        except AppError as exc:
            return safe_error(exc)

    async def heartbeat(self, request: Request) -> JSONResponse:
        try:
            claims = self._access.claims(
                request, "internal:file-service:document-processing:heartbeat"
            )
            payload = await request_json_exact(
                request,
                {
                    "instance_id",
                    "profile_hash",
                    "queue_contract",
                    "docling_local_workers",
                    "status",
                    "reason_code",
                },
            )
            result = await asyncio.to_thread(
                self._access.service().record_processing_worker_heartbeat,
                instance_id=str(payload["instance_id"]),
                profile_hash=str(payload["profile_hash"]),
                queue_contract=str(payload["queue_contract"]),
                docling_local_workers=int(payload["docling_local_workers"]),
                status=str(payload["status"]),
                reason_code=str(payload["reason_code"]),
                service_principal_id=str(claims["sub"]),
            )
            return JSONResponse(safe_result(result))
        except AppError as exc:
            return safe_error(exc)

    async def claim(self, request: Request) -> JSONResponse:
        try:
            claims = self._access.claims(request, "internal:file-service:document-processing:claim")
            payload = await request_json_exact(
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
                self._access.service().claim,
                message=payload,
                service_principal_id=str(claims["sub"]),
            )
            return JSONResponse(safe_result(result))
        except AppError as exc:
            return safe_error(exc)

    async def source_grant(self, request: Request) -> JSONResponse:
        try:
            claims = self._access.claims(
                request, "internal:file-service:document-processing:source:read"
            )
            payload = await request_json_exact(request, {"tenant_id"})
            result = await asyncio.to_thread(
                self._access.service().prepare_source_stream,
                run_id=str(request.path_params["run_id"]),
                tenant_id=str(payload["tenant_id"]),
                service_principal_id=str(claims["sub"]),
            )
            return JSONResponse(safe_result(result))
        except AppError as exc:
            return safe_error(exc)

    async def source_content(
        self,
        request: Request,
    ) -> StreamingResponse | JSONResponse:
        try:
            claims = self._access.claims(
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
                self._access.service().open_source_stream,
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
            return safe_error(exc)

    async def submitted(self, request: Request) -> JSONResponse:
        try:
            self._access.claims(request, "internal:file-service:document-processing:claim")
            payload = await request_json_exact(request, {"external_task_id"})
            result = await asyncio.to_thread(
                self._access.service().mark_submitted,
                run_id=str(request.path_params["run_id"]),
                external_task_id=str(payload["external_task_id"]),
            )
            return JSONResponse(safe_processing_run(result))
        except AppError as exc:
            return safe_error(exc)

    async def finalize(self, request: Request) -> JSONResponse:
        try:
            self._access.claims(request, "internal:file-service:document-processing:complete")
            payload = await request_json_exact(
                request, {"partial", "page_count", "processing_time_ms"}
            )
            representations = await asyncio.to_thread(
                self._access.service().finalize,
                run_id=str(request.path_params["run_id"]),
                partial=bool(payload["partial"]),
                page_count=optional_int(payload["page_count"]),
                processing_time_ms=optional_int(payload["processing_time_ms"]),
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
            return safe_error(exc)

    async def no_text(self, request: Request) -> JSONResponse:
        try:
            self._access.claims(request, "internal:file-service:document-processing:complete")
            payload = await request_json_exact(request, {"page_count", "processing_time_ms"})
            result = await asyncio.to_thread(
                self._access.service().complete_without_text,
                run_id=str(request.path_params["run_id"]),
                page_count=optional_int(payload["page_count"]),
                processing_time_ms=optional_int(payload["processing_time_ms"]),
            )
            return JSONResponse(safe_processing_run(result))
        except AppError as exc:
            return safe_error(exc)

    async def retry(self, request: Request) -> JSONResponse:
        try:
            self._access.claims(request, "internal:file-service:document-processing:complete")
            payload = await request_json_exact(request, {"error_code", "delay_seconds"})
            result = await asyncio.to_thread(
                self._access.service().schedule_retry,
                run_id=str(request.path_params["run_id"]),
                error_code=str(payload["error_code"]),
                delay_seconds=int(payload["delay_seconds"]),
            )
            return JSONResponse(safe_processing_run(result))
        except AppError as exc:
            return safe_error(exc)

    async def fail(self, request: Request) -> JSONResponse:
        try:
            self._access.claims(request, "internal:file-service:document-processing:complete")
            payload = await request_json_exact(request, {"error_code", "processing_time_ms"})
            result = await asyncio.to_thread(
                self._access.service().fail,
                run_id=str(request.path_params["run_id"]),
                error_code=str(payload["error_code"]),
                processing_time_ms=optional_int(payload["processing_time_ms"]),
            )
            return JSONResponse(safe_processing_run(result))
        except AppError as exc:
            return safe_error(exc)
