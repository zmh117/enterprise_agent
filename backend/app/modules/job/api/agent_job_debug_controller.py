from __future__ import annotations

import base64
from dataclasses import asdict
import hashlib
import json
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.bootstrap import Container
from app.modules.admin.application.scope import AdminScope, strict_business_scope_summary
from app.modules.agent.application.runtime_migration_gate import RuntimeMigrationGate
from app.modules.identity.api.dependencies import (
    current_principal,
    handle_exception,
    require_action,
)
from app.modules.job.application.create_agent_job_service import CreateAgentJobCommand
from app.modules.job.application.job_status_service import JobStatusService
from app.modules.job.infrastructure.repositories import now_iso
from app.shared.exceptions import NotFound, NonRetryableExecutionError


class _DebugJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    application_code: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9-]*$")
    environment: Literal["test", "production"] = "test"
    message: str = Field(min_length=1, max_length=12_000)


class _CancelJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_status: Literal["WAITING_INPUT", "PENDING", "RUNNING", "RETRY_WAIT"]


def build_self_job_history_router() -> Any:
    """Read-only portal endpoints scoped to the current authenticated user.

    These endpoints deliberately do not reuse the administrator read scope.  A
    platform administrator sees only their own records through the lightweight
    portal, exactly like every other user.
    """

    router = APIRouter(tags=["self-job-history"])

    @router.get("/api/me/jobs")
    def list_owned_jobs(request: Request, limit: int = 50) -> dict[str, Any]:
        principal = current_principal(request)
        bounded_limit = min(max(limit, 1), 100)
        c = _container(request)
        rows = c.database.execute(
            """
            select id
              from agent_job
             where internal_user_id = ? or requester_id = ? or user_id = ?
             order by created_at desc, id desc
             limit ?
            """,
            (
                principal.user_id,
                principal.user_id,
                principal.user_id,
                bounded_limit,
            ),
        )
        return {
            "items": [_job_projection(c, str(row["id"])) for row in rows],
            "page": {"limit": bounded_limit, "has_more": False, "next_cursor": None},
        }

    @router.get("/api/me/jobs/{job_id}/evidence")
    def owned_job_evidence(request: Request, job_id: str) -> dict[str, Any]:
        principal = current_principal(request)
        c = _container(request)
        job = _require_owned_job(c, user_id=principal.user_id, job_id=job_id)
        dispatch = c.agent_repository.get_dispatch_event_for_job(job_id)
        return {
            "job": _job_projection(c, job_id, detail=job),
            "session_ref": {"id": str(job["session_id"])},
            "dispatch": asdict(dispatch) if dispatch else None,
            "steps": c.agent_repository.list_steps(job_id),
            "mcp_tool_calls": _mcp_provenance(c, job_id),
            "deliveries": {
                "events": c.agent_repository.list_delivery_events(job_id),
                "attempts": c.agent_repository.list_delivery_attempts(job_id),
                "chunks": c.agent_repository.list_delivery_chunks(job_id),
            },
        }

    @router.get("/api/me/conversations/{session_id}")
    def owned_conversation(request: Request, session_id: str) -> dict[str, Any]:
        principal = current_principal(request)
        c = _container(request)
        row = c.database.execute_one(
            """
            select * from agent_session
             where id = ? and (requester_id = ? or dingding_user_id = ?)
            """,
            (session_id, principal.user_id, principal.user_id),
        )
        if row is None:
            raise HTTPException(status_code=404, detail="未找到会话")
        job_rows = c.database.execute(
            """
            select id from agent_job
             where session_id = ?
               and (internal_user_id = ? or requester_id = ? or user_id = ?)
             order by created_at, id
            """,
            (
                session_id,
                principal.user_id,
                principal.user_id,
                principal.user_id,
            ),
        )
        return {
            "session": {
                "id": str(row["id"]),
                "requester_id": principal.user_id,
                "source_channel": str(row.get("source_channel") or row.get("source") or ""),
                "source_connector_id": str(row.get("source_connector_id") or ""),
                "external_conversation_id": str(row.get("external_conversation_id") or ""),
                "created_at": str(row.get("created_at") or ""),
                "updated_at": str(row.get("updated_at") or row.get("created_at") or ""),
            },
            "jobs": [_job_projection(c, str(item["id"])) for item in job_rows],
            "messages": c.agent_repository.list_messages(session_id, limit=100),
        }

    return router


def build_admin_job_history_router() -> Any:
    """Governed history, cancel, and debug surfaces for the Web console."""

    router = APIRouter(prefix="/api/admin", tags=["admin-job-history"])

    @router.get("/jobs")
    def list_jobs(
        request: Request,
        limit: int = 50,
        cursor: str = "",
        status: str = "",
    ) -> dict[str, Any]:
        principal = require_action(
            request, resource_type="agent_job", resource_code="*", action="read"
        )
        if status and status not in {
            "WAITING_INPUT",
            "PENDING",
            "RUNNING",
            "RETRY_WAIT",
            "SUCCEEDED",
            "FAILED",
            "TIMEOUT",
            "CANCELLED",
        }:
            raise HTTPException(status_code=422, detail="任务状态无效")
        bounded_limit = min(max(limit, 1), 100)
        c = _container(request)
        scope = _admin_scope(c, principal.user_id)
        before_created_at, before_id = _decode_cursor(cursor)
        clauses: list[str] = []
        parameters: list[object] = []
        if not scope.global_access:
            clauses.append("(internal_user_id = ? or requester_id = ? or user_id = ?)")
            parameters.extend([principal.user_id, principal.user_id, principal.user_id])
        if status:
            clauses.append("status = ?")
            parameters.append(status)
        if before_created_at:
            clauses.append("(created_at < ? or (created_at = ? and id < ?))")
            parameters.extend([before_created_at, before_created_at, before_id])
        where = f"where {' and '.join(clauses)}" if clauses else ""
        rows = c.database.execute(
            f"""
            select id, created_at
              from agent_job
              {where}
             order by created_at desc, id desc
             limit ?
            """,
            tuple([*parameters, bounded_limit + 1]),
        )
        visible = rows[:bounded_limit]
        items = [_job_projection(c, str(row["id"])) for row in visible]
        has_more = len(rows) > bounded_limit
        next_cursor = (
            _encode_cursor(str(visible[-1]["created_at"]), str(visible[-1]["id"]))
            if has_more and visible
            else None
        )
        return {
            "items": items,
            "page": {
                "limit": bounded_limit,
                "has_more": has_more,
                "next_cursor": next_cursor,
            },
        }

    @router.get("/jobs/{job_id}/evidence")
    def job_evidence(request: Request, job_id: str) -> dict[str, Any]:
        principal = require_action(
            request, resource_type="agent_job", resource_code=job_id, action="read"
        )
        c = _container(request)
        job = _require_admin_job(c, user_id=principal.user_id, job_id=job_id)
        return _job_evidence(c, job_id=job_id, job=job)

    @router.post("/jobs/{job_id}/cancel")
    def cancel_job(
        request: Request,
        job_id: str,
        payload: _CancelJobRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="agent_job",
            resource_code=job_id,
            action="cancel",
            csrf=True,
        )
        c = _container(request)
        operation = f"admin.job.cancel:{job_id}"
        request_payload = {"job_id": job_id, "expected_status": payload.expected_status}
        replay = _idempotency_replay(
            c,
            actor_id=principal.user_id,
            operation=operation,
            key=idempotency_key,
            payload=request_payload,
        )
        if replay is not None:
            return replay
        job = _require_admin_job(c, user_id=principal.user_id, job_id=job_id)
        if str(job["status"]) != payload.expected_status:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "job_status_conflict",
                    "message": "任务状态已变化，请刷新后重试",
                    "current_status": str(job["status"]),
                },
            )
        try:
            cancelled = JobStatusService(c.agent_repository).cancel(job_id)
            result = {
                "job": _job_projection(c, job_id),
                "cancelled": cancelled.status.value == "CANCELLED",
            }
            _record_idempotency(
                c,
                actor_id=principal.user_id,
                operation=operation,
                key=idempotency_key,
                payload=request_payload,
                response=result,
            )
            c.audit_service.record(
                "admin.job.cancelled",
                status="SUCCEEDED",
                summary="Agent Job cancelled from governance console",
                actor_id=principal.user_id,
                job_id=job_id,
                payload={
                    "job_id": job_id,
                    "previous_status": payload.expected_status,
                    "new_status": "CANCELLED",
                },
            )
            return result
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.get("/debug/applications")
    def debug_applications(request: Request) -> dict[str, Any]:
        principal = require_action(
            request, resource_type="agent_job", resource_code="*", action="debug"
        )
        c = _container(request)
        rows = c.database.execute(
            """
            select a.id, a.code, a.name, d.environment
              from business_application a
              join business_application_deployment d on d.application_id = a.id
             where a.status = 'enabled' and d.active = 1 and d.publication_id is not null
             order by lower(a.name), a.code, d.environment
            """
        )
        items: list[dict[str, str]] = []
        for row in rows:
            decision = c.business_authorization_service.decide(
                user_id=principal.user_id,
                application_id=str(row["id"]),
                environment=str(row["environment"]),
                stage="debug_catalog",
            )
            if decision["allowed"]:
                items.append(
                    {
                        "id": str(row["id"]),
                        "code": str(row["code"]),
                        "name": str(row["name"]),
                        "environment": str(row["environment"]),
                    }
                )
        return {"items": items}

    @router.post("/debug/jobs", status_code=201)
    def create_debug_job(
        request: Request,
        payload: _DebugJobRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="agent_job",
            resource_code="*",
            action="debug",
            csrf=True,
        )
        c = _container(request)
        operation = "admin.debug_job.create"
        request_payload = payload.model_dump()
        replay = _idempotency_replay(
            c,
            actor_id=principal.user_id,
            operation=operation,
            key=idempotency_key,
            payload=request_payload,
        )
        if replay is not None:
            return replay
        try:
            runtime = c.business_application_resolver.resolve_active(
                payload.application_code, payload.environment
            )
            application = dict(runtime.get("application") or {})
            deployment = dict(runtime.get("deployment") or {})
            publication = dict(runtime.get("publication") or {})
            snapshot = dict(publication.get("snapshot") or {})
            agent = dict(snapshot.get("agent") or {})
            session_policy = dict(snapshot.get("session_policy") or {})
            execution_policy = dict(snapshot.get("execution_policy") or {})
            c.business_authorization_service.require(
                user_id=principal.user_id,
                application_id=str(application.get("id") or ""),
                environment=payload.environment,
                stage="debug_create",
            )
            runtime_selection = RuntimeMigrationGate(c.settings.agent_runtime).select(
                environment=payload.environment,
                application_publication_id=str(publication.get("id") or ""),
            )
            derived_key = _operation_key(
                actor_id=principal.user_id,
                operation=operation,
                key=idempotency_key,
            )
            job = c.create_agent_job_service.execute(
                CreateAgentJobCommand(
                    idempotency_key=derived_key,
                    requester_id=principal.user_id,
                    requester_display_name=principal.display_name,
                    external_conversation_id=f"debug:{derived_key[:24]}",
                    user_message=payload.message,
                    project_code=str(application.get("project_code") or "default"),
                    source_channel="debug_api",
                    source_connector_id="",
                    external_event_id=derived_key,
                    routing_context={
                        "project_code": str(application.get("project_code") or "default"),
                        "environment": payload.environment,
                    },
                    reply_route={"type": "none"},
                    correlation_id=str(getattr(request.state, "correlation_id", "")),
                    conversation_type="direct",
                    agent_code=str(agent.get("code") or ""),
                    fixed_agent_publication_id=str(agent.get("id") or ""),
                    fixed_agent_revision=(
                        int(agent["revision"]) if agent.get("revision") is not None else None
                    ),
                    fixed_agent_config_hash=str(agent.get("config_hash") or ""),
                    continuous_conversation_enabled=bool(
                        session_policy.get("continuous_conversation_enabled", False)
                    ),
                    attachments_enabled=False,
                    business_application_id=str(application.get("id") or ""),
                    business_application_code=str(application.get("code") or ""),
                    business_application_publication_id=str(publication.get("id") or ""),
                    business_application_deployment_id=str(deployment.get("id") or ""),
                    business_application_config_hash=str(publication.get("config_hash") or ""),
                    business_application_runtime_status=str(
                        runtime.get("runtime_status") or ""
                    ),
                    business_application_route_decision={
                        "correlation_id": str(getattr(request.state, "correlation_id", "")),
                        "deployment_environment": payload.environment,
                        "trigger_type": "debug_api",
                        "resolution_outcome": "matched",
                        "reason_code": str(runtime.get("reason_code") or ""),
                        "business_application_code": str(application.get("code") or ""),
                        "business_application_publication_id": str(publication.get("id") or ""),
                        "business_application_deployment_id": str(deployment.get("id") or ""),
                        "runtime_status": str(runtime.get("runtime_status") or ""),
                        "legacy_fallback": False,
                    },
                    conversation_mode=str(session_policy.get("conversation_mode") or "channel"),
                    recent_message_limit=(
                        int(session_policy["recent_message_limit"])
                        if session_policy.get("recent_message_limit") is not None
                        else None
                    ),
                    session_policy=session_policy,
                    application_execution_policy=execution_policy,
                    agent_runtime_kind=runtime_selection.runtime_kind,
                    agent_runtime_protocol_version=runtime_selection.protocol_version,
                )
            )
            result = {"job": _job_projection(c, job.id)}
            _record_idempotency(
                c,
                actor_id=principal.user_id,
                operation=operation,
                key=idempotency_key,
                payload=request_payload,
                response=result,
            )
            c.audit_service.record(
                "admin.debug_job.created",
                status="SUCCEEDED",
                summary="Governed debug Agent Job created",
                actor_id=principal.user_id,
                job_id=job.id,
                payload={
                    "job_id": job.id,
                    "application_code": str(application.get("code") or ""),
                    "environment": payload.environment,
                    "application_publication_id": str(publication.get("id") or ""),
                },
            )
            return result
        except Exception as exc:
            raise handle_exception(exc) from exc

    return router


def _require_owned_job(
    container: Container,
    *,
    user_id: str,
    job_id: str,
) -> dict[str, Any]:
    try:
        detail = container.agent_repository.get_job_detail(job_id)
    except NotFound as exc:
        raise HTTPException(status_code=404, detail="未找到 Agent Job") from exc
    owners = {
        str(detail.get("internal_user_id") or ""),
        str(detail.get("requester_id") or ""),
        str(detail.get("user_id") or ""),
    }
    if user_id not in owners:
        # Use the same response for an unknown and a foreign object to prevent
        # identifier enumeration.
        raise HTTPException(status_code=404, detail="未找到 Agent Job")
    return detail


def _require_admin_job(
    container: Container,
    *,
    user_id: str,
    job_id: str,
) -> dict[str, Any]:
    try:
        detail = container.agent_repository.get_job_detail(job_id)
    except NotFound as exc:
        raise HTTPException(status_code=404, detail="未找到 Agent Job") from exc
    if not _admin_scope(container, user_id).permits(detail):
        raise HTTPException(status_code=404, detail="未找到 Agent Job")
    return detail


def _admin_scope(container: Container, user_id: str) -> AdminScope:
    roles = container.identity_repository.role_codes_for_user(user_id)
    return AdminScope(
        strict_business_scope_summary(
            container.database,
            user_id=user_id,
            global_access="platform-admin" in roles,
        ),
        user_id,
    )


def _job_evidence(
    container: Container,
    *,
    job_id: str,
    job: dict[str, Any],
) -> dict[str, Any]:
    dispatch = container.agent_repository.get_dispatch_event_for_job(job_id)
    return {
        "job": _job_projection(container, job_id, detail=job),
        "session_ref": {"id": str(job["session_id"])},
        "dispatch": asdict(dispatch) if dispatch else None,
        "steps": container.agent_repository.list_steps(job_id),
        "mcp_tool_calls": _mcp_provenance(container, job_id),
        "deliveries": {
            "events": container.agent_repository.list_delivery_events(job_id),
            "attempts": container.agent_repository.list_delivery_attempts(job_id),
            "chunks": container.agent_repository.list_delivery_chunks(job_id),
        },
    }


def _job_projection(
    container: Container,
    job_id: str,
    *,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    job = detail or container.agent_repository.get_job_detail(job_id)
    agent = container.database.execute_one(
        """
        select d.code
          from agent_job j
          left join agent_definition d on d.id = j.agent_definition_id
         where j.id = ?
        """,
        (job_id,),
    )
    route = job.get("business_application_route_decision", {})
    return {
        "id": str(job["id"]),
        "session_id": str(job["session_id"]),
        "status": str(job["status"]),
        "source_channel": str(job.get("source_channel") or ""),
        "source_connector_id": str(job.get("source_connector_id") or ""),
        "source_connector_name": str(job.get("source_connector_name") or ""),
        "internal_user_id": str(job.get("internal_user_id") or ""),
        "requester_id": str(job.get("requester_id") or ""),
        "agent_code": str((agent or {}).get("code") or "agent"),
        "agent_publication_id": str(job.get("agent_publication_id") or ""),
        "agent_revision": job.get("agent_revision"),
        "agent_config_hash": str(job.get("agent_config_hash") or ""),
        "business_application_id": str(job.get("business_application_id") or ""),
        "business_application_code": str(job.get("business_application_code") or ""),
        "business_application_publication_id": str(
            job.get("business_application_publication_id") or ""
        ),
        "business_application_deployment_id": str(
            job.get("business_application_deployment_id") or ""
        ),
        "business_application_config_hash": str(
            job.get("business_application_config_hash") or ""
        ),
        "business_application_runtime_status": str(
            job.get("business_application_runtime_status") or ""
        ),
        "agent_runtime_kind": str(job.get("agent_runtime_kind") or ""),
        "agent_runtime_protocol_version": str(
            job.get("agent_runtime_protocol_version") or ""
        ),
        "execution_policy": dict(job.get("execution_policy") or {}),
        "tool_call_count": int(job.get("tool_call_count") or 0),
        "execution_policy_exhausted": bool(job.get("execution_policy_exhausted")),
        "last_error_code": str(job.get("last_error_code") or ""),
        "created_at": str(job.get("created_at") or ""),
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "correlation_id": str(route.get("correlation_id") or ""),
        "error_summary": str(job.get("error_message") or "")[:500],
    }


def _mcp_provenance(container: Container, job_id: str) -> list[dict[str, Any]]:
    rows = container.database.execute(
        """
        select id, job_id, mcp_server_code, server_version, tool_name,
               tool_schema_hash, subject_snapshot_id, resource_deployment_id,
               resource_revision_id, credential_revision, request_summary_json,
               result_hash, result_size, status, duration_ms, correlation_id,
               occurred_at
          from mcp_tool_call_provenance
         where job_id = ?
         order by occurred_at, id
        """,
        (job_id,),
    )
    result: list[dict[str, Any]] = []
    for row in rows:
        attempts = container.database.execute(
            """
            select attempt, status, error_code, duration_ms, created_at
              from mcp_tool_call_attempt
             where provenance_id = ?
             order by attempt
            """,
            (row["id"],),
        )
        try:
            summary = json.loads(str(row.get("request_summary_json") or "{}"))
        except (TypeError, json.JSONDecodeError):
            summary = {}
        result.append(
            {
                **{key: value for key, value in row.items() if key != "request_summary_json"},
                "request_summary": summary if isinstance(summary, dict) else {},
                "attempts": attempts,
            }
        )
    return result


def _container(request: Any) -> Container:
    container = getattr(request.app.state, "container", None)
    if not isinstance(container, Container):
        raise RuntimeError("Application container is not initialized")
    return container


def _encode_cursor(created_at: str, job_id: str) -> str:
    raw = json.dumps(
        {"created_at": created_at, "id": job_id},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str, str]:
    if not cursor:
        return "", ""
    try:
        padding = "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(f"{cursor}{padding}").decode())
        created_at = str(value.get("created_at") or "")
        job_id = str(value.get("id") or "")
        if not created_at or not job_id:
            raise ValueError("missing cursor fields")
        return created_at, job_id
    except (ValueError, TypeError, json.JSONDecodeError):
        raise HTTPException(status_code=422, detail="分页游标无效") from None


def _operation_key(*, actor_id: str, operation: str, key: str) -> str:
    return hashlib.sha256(f"{actor_id}\0{operation}\0{key}".encode()).hexdigest()


def _request_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _idempotency_replay(
    container: Container,
    *,
    actor_id: str,
    operation: str,
    key: str,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    stored_key = _operation_key(actor_id=actor_id, operation=operation, key=key)
    row = container.database.execute_one(
        "select * from management_operation_idempotency where idempotency_key = ?",
        (stored_key,),
    )
    if row is None:
        return None
    if (
        str(row["actor_id"]) != actor_id
        or str(row["operation"]) != operation
        or str(row["request_hash"]) != _request_hash(payload)
    ):
        raise NonRetryableExecutionError(
            "Idempotency key was reused with a different request",
            safe_message="幂等键已用于不同请求",
            error_code="idempotency_conflict",
        )
    parsed = json.loads(str(row["response_json"]))
    return dict(parsed) if isinstance(parsed, dict) else None


def _record_idempotency(
    container: Container,
    *,
    actor_id: str,
    operation: str,
    key: str,
    payload: dict[str, Any],
    response: dict[str, Any],
) -> None:
    stored_key = _operation_key(actor_id=actor_id, operation=operation, key=key)
    container.database.execute(
        """
        insert into management_operation_idempotency
          (idempotency_key, operation, actor_id, request_hash, response_json, created_at)
        values (?, ?, ?, ?, ?, ?)
        """,
        (
            stored_key,
            operation,
            actor_id,
            _request_hash(payload),
            json.dumps(response, ensure_ascii=False, sort_keys=True),
            now_iso(),
        ),
    )
