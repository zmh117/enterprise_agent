from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.shared.principal_token_contract import (
    FILE_PRINCIPAL_REFRESH_PATH,
    MAX_PRINCIPAL_TOKEN_BYTES,
)
from app.shared.exceptions import AppError


def build_file_principal_refresh_router() -> APIRouter:
    router = APIRouter()

    @router.post(FILE_PRINCIPAL_REFRESH_PATH)
    async def refresh_file_principal_token(request: Request) -> JSONResponse:
        container = request.app.state.container
        issuer = getattr(container, "principal_token_issuer", None)
        if issuer is None:
            raise HTTPException(status_code=503, detail="File Principal refresh is unavailable")

        authorization_headers = request.headers.getlist("authorization")
        content_length = request.headers.get("content-length")
        malformed = (
            len(authorization_headers) != 1
            or len(authorization_headers[0]) > 7 + MAX_PRINCIPAL_TOKEN_BYTES
            or not authorization_headers[0].startswith("Bearer ")
            or not authorization_headers[0][7:]
            or (content_length is not None and content_length != "0")
        )
        if not malformed:
            async for chunk in request.stream():
                if chunk:
                    malformed = True
                    break
        if malformed:
            container.audit_service.record(
                "principal.jwt.refresh_denied",
                status="denied",
                summary="Malformed File Principal JWT refresh was rejected",
                payload={"reason": "request_invalid"},
            )
            raise HTTPException(status_code=401, detail="File Principal refresh was rejected")

        try:
            refreshed = issuer.refresh_file_for_job(authorization_headers[0][7:])
        except AppError as exc:
            raise HTTPException(
                status_code=401,
                detail={
                    "code": exc.error_code or "file_principal_refresh_denied",
                    "message": "平台文件身份凭证刷新失败",
                },
            ) from exc
        return JSONResponse(
            {
                "access_token": refreshed,
                "token_type": "Bearer",
                "expires_in": int(getattr(issuer, "ttl_seconds", 300)),
            },
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )

    return router
