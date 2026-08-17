from __future__ import annotations

import json
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
from app.modules.job.infrastructure.execution_audit_repository import (
    ExecutionAuditRepository,
)


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

    @router.get("/{job_id}/model-calls")
    def list_model_calls(
        request: Request,
        job_id: str,
        limit: int = 50,
        cursor: str = "",
    ) -> dict[str, Any]:
        try:
            container = _container(request)
            principal = current_principal(request)
            container.debug_job_access_service.require_job_read(
                user_id=principal.user_id,
                job_id=job_id,
            )
            return {
                "job_id": job_id,
                **ExecutionAuditRepository(container.database).list_model_calls(
                    job_id,
                    limit=limit,
                    cursor=cursor or None,
                ),
            }
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=exc.safe_message) from exc
        except AppError as exc:
            raise handle_exception(exc) from exc

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
            execution_audit = ExecutionAuditRepository(container.database)
            execution_summary = execution_audit.get_summary(job_id)
            delivery_events = container.agent_repository.list_delivery_events(job_id)
            delivery_status = (
                str(delivery_events[-1].get("status") or "NOT_REQUESTED")
                if delivery_events
                else "NOT_REQUESTED"
            )
            execution_summary["delivery_status"] = delivery_status
            execution_summary["display_failure_stage"] = (
                "DELIVERY"
                if execution_summary["execution_status"] == "SUCCEEDED"
                and delivery_status in {"FAILED", "DEAD"}
                else execution_summary["execution_failure_stage"]
            )
            model_calls = execution_audit.list_model_calls(job_id, limit=50)
            tool_calls = container.agent_repository.list_tool_calls(job_id)
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
                "tool_calls": tool_calls,
                "execution_summary": execution_summary,
                "model_calls": model_calls,
                "mcp_operation_links": [
                    {
                        "agent_tool_call_id": str(item.get("id") or ""),
                        "mcp_call_id": str(item.get("mcp_call_id") or ""),
                        "server_code": str(item.get("server_code") or ""),
                    }
                    for item in tool_calls
                    if item.get("mcp_call_id")
                ],
                "file_workspace": _file_workspace_evidence(
                    container,
                    job_id=job_id,
                    route_decision=dict(job.get("business_application_route_decision") or {}),
                ),
                "deliveries": {
                    "events": delivery_events,
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


def _file_workspace_evidence(
    container: Container,
    *,
    job_id: str,
    route_decision: dict[str, Any],
) -> dict[str, Any]:
    snapshot = container.database.execute_one(
        """
        select id, schema_version, file_format_policy_version
          from agent_job_file_snapshot
         where job_id = ?
        """,
        (job_id,),
    )
    if snapshot is None:
        routed_policy = str(route_decision.get("file_format_policy_version") or "")
        return {
            "enabled": False,
            "manifest_schema_version": None,
            "file_format_policy_version": routed_policy or "text-v1",
            "policy_source": "job_route_decision" if routed_policy else "legacy_default",
            "formats": [],
        }
    rows = container.database.execute(
        """
        select format_code, allowed_actions_json
          from agent_job_file_snapshot_item
         where snapshot_id = ?
         order by ordinal
        """,
        (str(snapshot["id"]),),
    )
    formats: dict[str, dict[str, Any]] = {}
    allowed_action_codes = {
        "READ_METADATA",
        "MATERIALIZE",
        "EDIT",
        "COMMIT",
        "RETAIN",
        "DELIVER",
    }
    for row in rows:
        format_code = str(row.get("format_code") or "TXT")
        try:
            actions = json.loads(str(row.get("allowed_actions_json") or "[]"))
        except (TypeError, ValueError):
            actions = []
        entry = formats.setdefault(
            format_code,
            {"format_code": format_code, "file_count": 0, "allowed_actions": set()},
        )
        entry["file_count"] += 1
        entry["allowed_actions"].update(
            str(action)
            for action in actions
            if isinstance(action, str) and action in allowed_action_codes
        )
    return {
        "enabled": True,
        "manifest_schema_version": int(snapshot.get("schema_version") or 1),
        "file_format_policy_version": str(snapshot.get("file_format_policy_version") or "text-v1"),
        "policy_source": "job_file_manifest",
        "formats": [
            {
                **entry,
                "allowed_actions": sorted(entry["allowed_actions"]),
            }
            for _code, entry in sorted(formats.items())
        ],
    }


def _container(request: Any) -> Container:
    container = getattr(request.app.state, "container", None)
    if not isinstance(container, Container):
        raise RuntimeError("Application container is not initialized")
    return container
