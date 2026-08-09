from __future__ import annotations

from dataclasses import asdict
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from app.bootstrap import Container
from app.modules.identity.api.dependencies import current_principal
from app.shared.exceptions import NotFound


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
        **job,
        "agent_code": str((agent or {}).get("code") or "agent"),
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
