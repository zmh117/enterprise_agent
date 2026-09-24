from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from typing import Any, Protocol

from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

from app.shared.exceptions import AppError
from services.file_service.auth import FileWorkerPrincipalVerifier
from services.file_service.internal_http import bearer_token, safe_error, safe_result


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


class FileStreamingRoutes:
    def __init__(
        self,
        *,
        streaming: FileStreamingOperations,
        service_principal: FileWorkerPrincipalVerifier,
    ) -> None:
        self._streaming = streaming
        self._service_principal = service_principal

    async def download(self, request: Request) -> StreamingResponse | JSONResponse:
        try:
            stream, media_type = await self._streaming.download_transfer(
                transfer_id=request.path_params["transfer_id"],
                token=bearer_token(request),
            )
            return StreamingResponse(stream, media_type=media_type)
        except AppError as exc:
            return safe_error(exc)

    async def upload(self, request: Request) -> JSONResponse:
        try:
            result = await self._streaming.upload_commit(
                commit_id=request.path_params["commit_id"],
                token=bearer_token(request),
                body=request.stream(),
            )
            return JSONResponse(safe_result(result))
        except AppError as exc:
            return safe_error(exc)

    async def attachment(self, request: Request) -> JSONResponse:
        try:
            claims = self._service_principal.verify_service(
                bearer_token(request),
                required_scope="internal:file-service:attachment:import",
            )
            result = await self._streaming.import_attachment(
                attachment_id=request.path_params["attachment_id"],
                service_claims=claims,
                media_type=str(request.headers.get("content-type") or "application/octet-stream"),
                body=request.stream(),
            )
            return JSONResponse(safe_result(result))
        except AppError as exc:
            return safe_error(exc)

    async def maintenance(self, request: Request) -> JSONResponse:
        try:
            claims = self._service_principal.verify_service(
                bearer_token(request),
                required_scope="internal:file-service:content:cleanup",
            )
            result = await self._streaming.run_maintenance(service_claims=claims)
            return JSONResponse(safe_result(result))
        except AppError as exc:
            return safe_error(exc)

    async def maintenance_metrics(self, request: Request) -> JSONResponse:
        try:
            claims = self._service_principal.verify_service(
                bearer_token(request),
                required_scope="internal:file-service:content:cleanup",
            )
            result = await self._streaming.maintenance_metrics(service_claims=claims)
            return JSONResponse(safe_result(result))
        except AppError as exc:
            return safe_error(exc)

    async def delivery_content(self, request: Request) -> StreamingResponse | JSONResponse:
        try:
            claims = self._service_principal.verify_delivery(
                bearer_token(request),
                required_scope="internal:file-service:delivery:read",
            )
            stream, metadata = await self._streaming.download_delivery(
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
            return safe_error(exc)
