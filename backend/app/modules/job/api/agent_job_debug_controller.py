from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.bootstrap import Container
from app.modules.channel.domain.channel_event import (
    ChannelEvent,
    ChannelSource,
    ReplyRoute,
    RoutingContext,
    safe_payload_summary,
)
from app.shared.exceptions import NotFound, PermissionDenied
from app.shared.logging import new_correlation_id


def build_agent_job_debug_router() -> Any:
    router = APIRouter(prefix="/api/agent/jobs", tags=["agent-jobs"])

    @router.post("")
    async def create_job(request: Request) -> dict[str, Any]:
        container = _container(request)
        payload = await _json_payload(request)
        message = _required_string(payload, "message")
        user_id = _optional_string(payload, "user_id") or container.settings.debug_agent_user_id
        conversation_id = _optional_string(payload, "conversation_id") or f"debug:{user_id}"
        project_code = _optional_string(payload, "project_code") or "default"
        raw_idempotency_key = _optional_string(payload, "idempotency_key")
        idempotency_key = (
            f"debug:{raw_idempotency_key}" if raw_idempotency_key else f"debug:{uuid.uuid4().hex}"
        )
        delivery = ReplyRoute.from_dict(_optional_dict(payload, "delivery") or {"type": "none"})
        routing = RoutingContext.from_dict(
            {
                **(_optional_dict(payload, "routing") or {}),
                "project_code": project_code,
            }
        )
        event = ChannelEvent(
            source=ChannelSource(
                type="debug_api",
                connector_id="connector-debug-api",
                event_id=idempotency_key,
                actor_id=user_id,
                conversation_id=conversation_id,
            ),
            delivery=delivery,
            routing=routing,
            message=message,
            raw_payload_summary=safe_payload_summary(payload),
            idempotency_key=idempotency_key,
            correlation_id=request.headers.get("x-correlation-id") or new_correlation_id(),
        )
        try:
            job = container.channel_ingress_service.accept(event)
        except PermissionDenied as exc:
            raise HTTPException(status_code=403, detail=exc.safe_message) from exc
        return {
            "accepted": True,
            "status": job.status.value,
            "job_id": job.id,
            "idempotency_key": idempotency_key,
        }

    @router.get("/{job_id}")
    def get_job(request: Request, job_id: str) -> dict[str, Any]:
        try:
            return _container(request).agent_repository.get_job_detail(job_id)
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/{job_id}/steps")
    def list_steps(request: Request, job_id: str) -> dict[str, Any]:
        try:
            return {
                "job_id": job_id,
                "steps": _container(request).agent_repository.list_steps(job_id),
            }
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/{job_id}/tool-calls")
    def list_tool_calls(request: Request, job_id: str) -> dict[str, Any]:
        try:
            return {
                "job_id": job_id,
                "tool_calls": _container(request).agent_repository.list_tool_calls(job_id),
            }
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/{job_id}/delivery-attempts")
    def list_delivery_attempts(request: Request, job_id: str) -> dict[str, Any]:
        try:
            container = _container(request)
            return {
                "job_id": job_id,
                "delivery_attempts": container.agent_repository.list_delivery_attempts(job_id),
                "delivery_chunks": container.agent_repository.list_delivery_chunks(job_id),
            }
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router


def _container(request: Any) -> Container:
    container = getattr(request.app.state, "container", None)
    if not isinstance(container, Container):
        raise RuntimeError("Application container is not initialized")
    return container


async def _json_payload(request: Any) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception as exc:
        raise _bad_request("Request body must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise _bad_request("Request body must be a JSON object")
    return payload


def _required_string(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise _bad_request(f"Field '{field}' is required")
    return value.strip()


def _optional_string(payload: dict[str, Any], field: str) -> str | None:
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise _bad_request(f"Field '{field}' must be a string")
    value = value.strip()
    return value or None


def _optional_dict(payload: dict[str, Any], field: str) -> dict[str, Any] | None:
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise _bad_request(f"Field '{field}' must be an object")
    return value


def _bad_request(message: str) -> Exception:
    return HTTPException(status_code=400, detail=message)
