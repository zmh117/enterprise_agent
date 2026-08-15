from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.modules.identity.application.service_principal import (
    ServicePrincipalTokenError,
)


def build_service_principal_router() -> APIRouter:
    router = APIRouter(prefix="/api/internal/service-principal")

    @router.post("/token")
    async def issue_service_principal_token(request: Request) -> JSONResponse:
        container = request.app.state.container
        issuer = getattr(container, "service_principal_token_issuer", None)
        if issuer is None:
            raise HTTPException(status_code=503, detail="Service identity is unavailable")

        authorization_headers = request.headers.getlist("authorization")
        content_length = request.headers.get("content-length")
        malformed = (
            len(authorization_headers) != 1
            or len(authorization_headers[0]) > 7 + 4096
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
                "service_principal_token_denied",
                status="denied",
                summary="Malformed Service Principal token exchange was rejected",
                payload={"reason": "request_invalid"},
            )
            raise HTTPException(status_code=401, detail="Service identity was rejected")

        try:
            issued = issuer.issue(authorization_headers[0][7:])
        except ServicePrincipalTokenError as exc:
            raise HTTPException(status_code=401, detail="Service identity was rejected") from exc
        return JSONResponse(
            {
                "access_token": issued.access_token,
                "token_type": issued.token_type,
                "expires_in": issued.expires_in,
            },
            headers={
                "Cache-Control": "no-store",
                "Pragma": "no-cache",
            },
        )

    return router
