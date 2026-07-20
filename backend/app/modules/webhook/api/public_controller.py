from __future__ import annotations

import hashlib
import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.modules.identity.api.dependencies import container
from app.shared.exceptions import AppError, NotFound, PermissionDenied
from app.shared.logging import new_correlation_id


logger = logging.getLogger(__name__)


def build_public_webhook_router() -> APIRouter:
    router = APIRouter(prefix="/webhooks/v1", tags=["managed-webhooks"])

    @router.post("/{public_id}")
    async def receive(request: Request, public_id: str) -> JSONResponse:
        c = container(request)
        try:
            raw_body = await bounded_raw_body(request, c.settings.webhooks.max_body_bytes)
            acknowledgement = c.webhook_ingress_service.receive(
                public_id=public_id,
                raw_body=raw_body,
                content_type=request.headers.get("content-type", ""),
                headers=request.headers,
                correlation_id=request.headers.get("x-correlation-id")
                or new_correlation_id(),
                remote_address=request.client.host if request.client else "",
            )
        except Exception as exc:
            code = exc.error_code if isinstance(exc, AppError) else "webhook_request_failed"
            c.audit_service.record(
                "webhook.request.rejected",
                status="DENIED",
                summary="Managed Webhook request rejected",
                payload={
                    "public_id_hash": hashlib.sha256(public_id.encode()).hexdigest()[:16],
                    "error_code": code,
                    "request_bytes": len(raw_body) if "raw_body" in locals() else 0,
                },
            )
            logger.warning(
                "Managed Webhook request rejected public_id_hash=%s error_code=%s",
                hashlib.sha256(public_id.encode()).hexdigest()[:16],
                code,
            )
            return public_error_response(exc)
        if acknowledgement.accepted:
            c.webhook_outbox_publisher.publish_pending(limit=1)
        return JSONResponse(
            status_code=200 if acknowledgement.ignored else 202,
            content=acknowledgement_payload(acknowledgement),
        )

    return router


async def bounded_raw_body(request: Request, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > max_bytes:
            from app.shared.exceptions import NonRetryableExecutionError

            raise NonRetryableExecutionError(
                "Webhook request body exceeds configured limit",
                safe_message="Webhook payload is too large",
                error_code="webhook_payload_too_large",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def acknowledgement_payload(acknowledgement: Any) -> dict[str, Any]:
    return {
        "event_id": acknowledgement.event_id,
        "correlation_id": acknowledgement.correlation_id,
        "accepted": acknowledgement.accepted,
        "ignored": acknowledgement.ignored,
        "duplicate": acknowledgement.duplicate,
        "status": acknowledgement.status,
        "reason": acknowledgement.reason,
    }


def public_error_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, NotFound):
        status = 404
    elif isinstance(exc, PermissionDenied):
        status = 429 if exc.error_code == "webhook_rate_limited" else 401
    elif isinstance(exc, AppError):
        status = 413 if exc.error_code == "webhook_payload_too_large" else 400
    else:
        status = 500
    if isinstance(exc, AppError):
        message = exc.safe_message
        code = exc.error_code or "webhook_request_failed"
        fields = exc.field_errors
    else:
        message = "Webhook request failed"
        code = "webhook_request_failed"
        fields = []
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "field_errors": fields}},
    )
