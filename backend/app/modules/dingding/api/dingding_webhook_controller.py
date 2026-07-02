from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

from app.bootstrap import Container
from app.shared.logging import new_correlation_id


def build_dingding_router() -> Any:
    router = APIRouter(prefix="/webhooks/dingding", tags=["dingding"])

    @router.post("/agent")
    async def dingtalk_agent(
        request: Request,
        x_dingtalk_timestamp: str = Header(default=""),
        x_dingtalk_sign: str = Header(default=""),
    ) -> dict[str, Any]:
        container = _container(request)
        if not container.settings.dingtalk.http_webhook_enabled:
            raise HTTPException(
                status_code=404,
                detail={
                    "status": "disabled",
                    "message": "DingTalk HTTP webhook ingress is disabled; use DingTalk Stream ingress.",
                },
            )
        payload = await request.json()
        result = container.dingtalk_message_service.handle_webhook(
            payload=payload,
            timestamp=x_dingtalk_timestamp,
            sign=x_dingtalk_sign,
            correlation_id=request.headers.get("x-correlation-id") or new_correlation_id(),
        )
        if result["status"] == "invalid_signature":
            raise HTTPException(status_code=401, detail=result)
        if result["status"] == "permission_denied":
            raise HTTPException(status_code=403, detail=result)
        return result

    return router


def _container(request: Any) -> Container:
    container = getattr(request.app.state, "container", None)
    if not isinstance(container, Container):
        raise RuntimeError("Application container is not initialized")
    return container
