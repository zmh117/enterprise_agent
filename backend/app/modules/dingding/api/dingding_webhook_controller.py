from __future__ import annotations

from typing import Any

from app.bootstrap import build_container
from app.shared.config import Settings
from app.shared.logging import new_correlation_id


def build_dingding_router(settings: Settings) -> Any:
    from fastapi import APIRouter, Header, HTTPException, Request

    router = APIRouter(prefix="/webhooks/dingding", tags=["dingding"])

    @router.post("/agent")
    async def dingtalk_agent(
        request: Request,
        x_dingtalk_timestamp: str = Header(default=""),
        x_dingtalk_sign: str = Header(default=""),
    ) -> dict[str, Any]:
        container = build_container(settings, migrate=True, seed=True)
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
