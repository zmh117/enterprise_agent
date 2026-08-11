from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.bootstrap import Container
from app.modules.identity.api.dependencies import (
    current_principal,
    handle_exception,
    require_action,
)
from app.shared.exceptions import AppError, NotFound
from app.shared.logging import new_correlation_id


class DebugJobCreateRequest(BaseModel):
    """Only caller-controlled values that cannot expand runtime authority."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    message: str = Field(min_length=1, max_length=20_000)
    application_id: str = Field(min_length=1, max_length=200)
    execution_scope_id: str = Field(min_length=1, max_length=200)
    delivery_binding_id: str = Field(default="", max_length=200)
    idempotency_key: str = Field(default="", max_length=240)
    continue_session_id: str = Field(default="", max_length=200)


def build_agent_job_debug_router() -> Any:
    router = APIRouter(prefix="/api/agent/jobs", tags=["agent-jobs"])

    @router.post("")
    async def create_job(
        request: Request,
        payload: DebugJobCreateRequest,
    ) -> dict[str, Any]:
        container = _container(request)
        principal = require_action(
            request,
            resource_type="agent_job",
            resource_code="*",
            action="debug_execute",
            csrf=True,
        )
        try:
            job, scoped_idempotency_key = container.debug_job_access_service.create_job(
                user_id=principal.user_id,
                display_name=principal.display_name,
                message=payload.message,
                application_id=payload.application_id,
                execution_scope_id=payload.execution_scope_id,
                delivery_binding_id=payload.delivery_binding_id,
                idempotency_key=payload.idempotency_key,
                continue_session_id=payload.continue_session_id,
                correlation_id=(
                    getattr(request.state, "correlation_id", "") or new_correlation_id()
                ),
                environment="local",
            )
        except AppError as exc:
            raise handle_exception(exc) from exc
        return {
            "accepted": True,
            "status": job.status.value,
            "job_id": job.id,
            "idempotency_key": scoped_idempotency_key,
        }

    @router.get("/_debug-options")
    def debug_options(request: Request) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="agent_job",
            resource_code="*",
            action="debug_execute",
        )
        return _container(request).debug_job_access_service.available_options(
            user_id=principal.user_id,
            environment="local",
        )

    @router.get("/{job_id}")
    def get_job(request: Request, job_id: str) -> dict[str, Any]:
        try:
            container = _container(request)
            principal = current_principal(request)
            return container.debug_job_access_service.require_job_read(
                user_id=principal.user_id,
                job_id=job_id,
            )
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=exc.safe_message) from exc

    @router.get("/{job_id}/steps")
    def list_steps(request: Request, job_id: str) -> dict[str, Any]:
        try:
            container = _container(request)
            principal = current_principal(request)
            container.debug_job_access_service.require_job_read(
                user_id=principal.user_id,
                job_id=job_id,
            )
            return {
                "job_id": job_id,
                "steps": container.agent_repository.list_steps(job_id),
            }
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=exc.safe_message) from exc

    @router.get("/{job_id}/tool-calls")
    def list_tool_calls(request: Request, job_id: str) -> dict[str, Any]:
        try:
            container = _container(request)
            principal = current_principal(request)
            container.debug_job_access_service.require_job_read(
                user_id=principal.user_id,
                job_id=job_id,
            )
            return {
                "job_id": job_id,
                "tool_calls": container.agent_repository.list_tool_calls(job_id),
            }
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=exc.safe_message) from exc

    @router.get("/{job_id}/deliveries")
    def list_deliveries(request: Request, job_id: str) -> dict[str, Any]:
        try:
            container = _container(request)
            principal = current_principal(request)
            container.debug_job_access_service.require_job_read(
                user_id=principal.user_id,
                job_id=job_id,
            )
            return {
                "job_id": job_id,
                "deliveries": {
                    "events": container.agent_repository.list_delivery_events(job_id),
                    "attempts": container.agent_repository.list_delivery_attempts(job_id),
                    "chunks": container.agent_repository.list_delivery_chunks(job_id),
                },
            }
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=exc.safe_message) from exc

    @router.get("/{job_id}/evidence")
    def job_evidence(request: Request, job_id: str) -> dict[str, Any]:
        try:
            container = _container(request)
            principal = current_principal(request)
            job = container.debug_job_access_service.require_job_read(
                user_id=principal.user_id,
                job_id=job_id,
            )
            agent = container.database.execute_one(
                """
                select d.code
                  from agent_job j
                  left join agent_definition d
                    on d.id = j.agent_definition_id
                 where j.id = ?
                """,
                (job_id,),
            )
            dispatch = container.agent_repository.get_dispatch_event_for_job(job_id)
            return {
                "job": {
                    **job,
                    "agent_code": str((agent or {}).get("code") or "default-diagnostic-agent"),
                    "correlation_id": str(
                        job.get("business_application_route_decision", {}).get("correlation_id")
                        or ""
                    ),
                    "error_summary": str(job.get("error_message") or "")[:500],
                },
                "session_ref": {"id": str(job["session_id"])},
                "dispatch": asdict(dispatch) if dispatch else None,
                "steps": container.agent_repository.list_steps(job_id),
                "tool_calls": container.agent_repository.list_tool_calls(job_id),
                "deliveries": {
                    "events": container.agent_repository.list_delivery_events(job_id),
                    "attempts": container.agent_repository.list_delivery_attempts(job_id),
                    "chunks": container.agent_repository.list_delivery_chunks(job_id),
                },
                "webhook_events": [],
            }
        except NotFound as exc:
            raise HTTPException(
                status_code=404,
                detail=exc.safe_message,
            ) from exc

    return router


def _container(request: Any) -> Container:
    container = getattr(request.app.state, "container", None)
    if not isinstance(container, Container):
        raise RuntimeError("Application container is not initialized")
    return container
