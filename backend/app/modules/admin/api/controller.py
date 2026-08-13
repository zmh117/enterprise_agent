from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from app.modules.admin.application import AdminCapabilityService, PageWindow, TimeWindow
from app.modules.admin.application.dashboard_service import DashboardQueryService
from app.modules.admin.application.channel_provider_service import ChannelProviderService
from app.modules.admin.application.scope import (
    AdminScope,
    strict_business_scope_summary,
)
from app.modules.admin.infrastructure import (
    AdminConnectorRepository,
    AdminReadRepository,
    RabbitMQQueueStatusAdapter,
)
from app.modules.identity.api.dependencies import (
    container,
    current_principal,
    handle_exception,
    require_action,
)


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChannelConnectorRequest(StrictRequest):
    expected_revision: int = Field(ge=0)
    id: str = ""
    connector_type: str
    name: str = Field(min_length=2, max_length=120)
    base_url: str = ""
    enabled: bool = True
    allow_ingress: bool = False
    allow_delivery: bool = False
    secret_ref: str = ""
    endpoint_ref: str = ""
    host_allowlist: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RevisionStatusRequest(StrictRequest):
    expected_revision: int = Field(ge=0)
    status: Literal["enabled", "disabled"]


def build_admin_router() -> APIRouter:
    router = APIRouter(prefix="/api/admin", tags=["administration"])

    @router.get("/capabilities")
    def capabilities(request: Request) -> dict[str, Any]:
        principal = current_principal(request)
        c = container(request)
        try:
            summary = AdminCapabilityService(
                c.identity_repository,
                c.authorization_evaluator,
            ).summary(principal.user_id)
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {
            "subject": {
                "id": principal.user_id,
                "username": principal.username,
                "display_name": principal.display_name,
            },
            **summary,
        }

    @router.get("/dashboard")
    def dashboard(request: Request, start: str = "", end: str = "") -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="admin_dashboard",
            resource_code="*",
            action="read",
        )
        c = container(request)
        try:
            scope_summary = strict_business_scope_summary(
                c.database,
                user_id=principal.user_id,
                global_access="platform-admin" in principal.role_codes,
            )
            service = DashboardQueryService(
                AdminReadRepository(c.database),
                RabbitMQQueueStatusAdapter(c.settings.rabbitmq_url, c.settings.queue),
            )
            return service.query(
                window=TimeWindow.parse(start=start, end=end),
                scope=AdminScope(scope_summary, principal.user_id),
            )
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.get("/skills")
    def skills(request: Request) -> dict[str, Any]:
        require_action(request, resource_type="skill_catalog", resource_code="*", action="read")
        return {"skills": container(request).agent_config_service.skill_catalog()}

    @router.get("/skills/{skill_code}")
    def skill_detail(request: Request, skill_code: str) -> dict[str, Any]:
        require_action(request, resource_type="skill_catalog", resource_code="*", action="read")
        items = container(request).agent_config_service.skill_catalog()
        item = next((value for value in items if value["code"] == skill_code), None)
        if item is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="未找到技能")
        return {"skill": item}

    @router.get("/channel-providers")
    def channel_providers(request: Request) -> dict[str, Any]:
        require_action(request, resource_type="channel_connector", resource_code="*", action="read")
        return {"providers": ChannelProviderService().catalog()}

    @router.get("/connectors")
    def connectors(request: Request, limit: int = 25, cursor: str = "") -> dict[str, Any]:
        require_action(request, resource_type="channel_connector", resource_code="*", action="read")
        try:
            page = PageWindow.parse(limit=limit, cursor=cursor)
            items = AdminConnectorRepository(container(request).database).list()
            if page.cursor:
                after = PageWindow.decode(page.cursor)
                items = [item for item in items if str(item["id"]) > after]
            selected = items[: page.limit + 1]
            has_more = len(selected) > page.limit
            selected = selected[: page.limit]
            return {
                "connectors": selected,
                "items": selected,
                "page": {
                    "limit": page.limit,
                    "has_more": has_more,
                    "next_cursor": PageWindow.encode(str(selected[-1]["id"]))
                    if has_more and selected
                    else None,
                },
            }
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.get("/connectors/{connector_id}")
    def connector(request: Request, connector_id: str) -> dict[str, Any]:
        require_action(request, resource_type="channel_connector", resource_code="*", action="read")
        try:
            return {
                "connector": AdminConnectorRepository(container(request).database).get(connector_id)
            }
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.post("/connectors")
    @router.put("/connectors/{connector_id}")
    def save_connector(
        request: Request,
        payload: ChannelConnectorRequest,
        connector_id: str = "",
    ) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="channel_connector",
            resource_code="*",
            action="manage",
            csrf=True,
        )
        data = payload.model_dump()
        if connector_id and data["id"] and connector_id != data["id"]:
            from fastapi import HTTPException

            raise HTTPException(status_code=422, detail="路径与请求内容中的连接器 ID 不一致")
        if connector_id:
            data["id"] = connector_id
        try:
            ChannelProviderService().validate(data)
            expected = int(data.pop("expected_revision"))
            c = container(request)
            with c.database.unit_of_work():
                item = AdminConnectorRepository(c.database).save(data, expected_revision=expected)
                c.audit_service.record(
                    "admin.channel_connector.saved",
                    status="SUCCEEDED",
                    summary="Channel connector configuration saved",
                    actor_id=principal.user_id,
                    payload={
                        "connector_id": item["id"],
                        "connector_type": item["connector_type"],
                        "correlation_id": _correlation_id(request),
                    },
                )
            return {"connector": item}
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.put("/connectors/{connector_id}/status")
    def set_connector_status(
        request: Request, connector_id: str, payload: RevisionStatusRequest
    ) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="channel_connector",
            resource_code="*",
            action="manage",
            csrf=True,
        )
        c = container(request)
        repository = AdminConnectorRepository(c.database)
        try:
            with c.database.unit_of_work():
                existing = repository.get(connector_id)
                item = repository.save(
                    {**existing, "enabled": payload.status == "enabled"},
                    expected_revision=payload.expected_revision,
                )
                c.audit_service.record(
                    "admin.channel_connector.status_changed",
                    status="SUCCEEDED",
                    summary="Channel connector status changed",
                    actor_id=principal.user_id,
                    payload={
                        "connector_id": connector_id,
                        "status": payload.status,
                        "correlation_id": _correlation_id(request),
                    },
                )
            return {"connector": item}
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.post("/connectors/validate")
    def validate_connector(request: Request, payload: ChannelConnectorRequest) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="channel_connector",
            resource_code="*",
            action="manage",
            csrf=True,
        )
        try:
            result = ChannelProviderService().validate(payload.model_dump())
            container(request).audit_service.record(
                "admin.channel_connector.validated",
                status="SUCCEEDED",
                summary="Channel connector configuration validated without delivery",
                actor_id=principal.user_id,
                payload={
                    "connector_type": payload.connector_type,
                    "correlation_id": _correlation_id(request),
                },
            )
            return {"result": {**result, "correlation_id": _correlation_id(request)}}
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.get("/queues")
    def queues(request: Request) -> dict[str, Any]:
        require_action(request, resource_type="queue_status", resource_code="*", action="read")
        c = container(request)
        return RabbitMQQueueStatusAdapter(c.settings.rabbitmq_url, c.settings.queue).collect()

    @router.get("/jobs")
    def jobs(
        request: Request,
        start: str = "",
        end: str = "",
        status: str = "",
        user_id: str = "",
        username: str = "",
        application_name: str = "",
        agent: str = "",
        channel: str = "",
        project: str = "",
        session_id: str = "",
        correlation_id: str = "",
        execution_status: str = "",
        delivery_status: str = "",
        failure_stage: str = "",
        model: str = "",
        limit: int = 25,
        cursor: str = "",
    ) -> dict[str, Any]:
        principal = require_action(
            request, resource_type="agent_job", resource_code="*", action="read"
        )
        try:
            c = container(request)
            window = TimeWindow.parse(start=start, end=end)
            page = PageWindow.parse(limit=limit, cursor=cursor)
            start_at, end_at = window.as_iso()
            values = [
                item
                for item in AdminReadRepository(c.database).jobs_in_window(
                    start_at,
                    end_at,
                    username=username,
                    application_name=application_name,
                )
                if _scope(c, principal).permits(item)
                and (not status or item["status"] in set(status.split(",")))
                and (not user_id or user_id in {item.get("internal_user_id"), item.get("user_id")})
                and (not agent or item.get("agent_code") == agent)
                and (not channel or item.get("source_channel") == channel)
                and (not project or item.get("project_code") == project)
                and (not session_id or item.get("session_id") == session_id)
                and (not correlation_id or item.get("correlation_id") == correlation_id)
                and (
                    not execution_status
                    or item["execution_summary"]["execution_status"]
                    in set(execution_status.split(","))
                )
                and (
                    not delivery_status
                    or item["execution_summary"]["delivery_status"]
                    in set(delivery_status.split(","))
                )
                and (
                    not failure_stage
                    or item["execution_summary"]["display_failure_stage"]
                    in set(failure_stage.split(","))
                )
                and (not model or model in item["execution_summary"]["models"])
            ]
            values = _after_cursor(values, page.cursor, "created_at")
            return _page(values, page, "created_at") | {
                "window": {"start": start_at, "end": end_at}
            }
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.get("/jobs/summary")
    def job_summary(request: Request, start: str = "", end: str = "") -> dict[str, Any]:
        principal = require_action(
            request, resource_type="agent_job", resource_code="*", action="read"
        )
        c = container(request)
        try:
            window = TimeWindow.parse(start=start, end=end)
            dashboard = DashboardQueryService(
                AdminReadRepository(c.database),
                RabbitMQQueueStatusAdapter(c.settings.rabbitmq_url, c.settings.queue),
            ).query(window=window, scope=_scope(c, principal))
            return {
                "window": dashboard["window"],
                "generated_at": dashboard["generated_at"],
                **dashboard["jobs"],
            }
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.get("/deliveries/metrics")
    def delivery_metrics(request: Request) -> dict[str, Any]:
        require_action(
            request,
            resource_type="agent_job",
            resource_code="*",
            action="read",
        )
        return {"delivery": container(request).agent_repository.delivery_metrics()}

    @router.get("/jobs/{job_id}")
    def job_detail(request: Request, job_id: str) -> dict[str, Any]:
        principal = require_action(
            request, resource_type="agent_job", resource_code="*", action="read"
        )
        c = container(request)
        evidence = AdminReadRepository(c.database).job_evidence(job_id)
        if evidence is None or not _scope(c, principal).permits(evidence["job"]):
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="未找到 Agent 任务")
        return evidence

    @router.get("/conversations")
    def conversations(
        request: Request,
        start: str = "",
        end: str = "",
        channel: str = "",
        user_id: str = "",
        external_conversation_id: str = "",
        agent: str = "",
        job_status: str = "",
        limit: int = 25,
        cursor: str = "",
    ) -> dict[str, Any]:
        principal = require_action(
            request, resource_type="conversation", resource_code="*", action="read"
        )
        c = container(request)
        try:
            window = TimeWindow.parse(start=start, end=end)
            page = PageWindow.parse(limit=limit, cursor=cursor)
            start_at, end_at = window.as_iso()
            repository = AdminReadRepository(c.database)
            values = []
            for item in repository.recent_sessions(start_at, end_at, limit=500):
                if not _scope(c, principal).permits(item):
                    continue
                jobs_for_session = repository.session_jobs(str(item["id"]))
                if channel and item.get("source_channel") != channel:
                    continue
                if user_id and item.get("requester_id") != user_id:
                    continue
                if (
                    external_conversation_id
                    and item.get("external_conversation_id") != external_conversation_id
                ):
                    continue
                if agent and not any(job.get("agent_code") == agent for job in jobs_for_session):
                    continue
                if job_status and not any(
                    job.get("status") == job_status for job in jobs_for_session
                ):
                    continue
                values.append(
                    {
                        **item,
                        "job_count": len(jobs_for_session),
                        "latest_job_status": jobs_for_session[-1]["status"]
                        if jobs_for_session
                        else "",
                    }
                )
            values = _after_cursor(values, page.cursor, "updated_at")
            return _page(values, page, "updated_at") | {
                "window": {"start": start_at, "end": end_at}
            }
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.get("/conversations/{session_id}")
    def conversation_detail(request: Request, session_id: str) -> dict[str, Any]:
        principal = require_action(
            request, resource_type="conversation", resource_code="*", action="read"
        )
        c = container(request)
        repository = AdminReadRepository(c.database)
        session = repository.session_detail(session_id)
        if session is None or not _scope(c, principal).permits(session):
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="未找到会话")
        jobs_for_session = repository.session_jobs(session_id)
        attachments = [
            item
            for item in repository.attachments_in_window(
                "1970-01-01T00:00:00+00:00", "9999-12-31T23:59:59+00:00"
            )
            if item["session_id"] == session_id
        ][:100]
        return {
            "session": session,
            "messages": repository.session_messages(session_id),
            "jobs": jobs_for_session,
            "attachments": attachments,
            "delivery_refs": [
                {"job_id": job["id"], "href": f"/api/admin/jobs/{job['id']}"}
                for job in jobs_for_session
            ],
        }

    @router.get("/attachments")
    def attachments(
        request: Request,
        start: str = "",
        end: str = "",
        session_id: str = "",
        user_id: str = "",
        mime: str = "",
        status: str = "",
        limit: int = 25,
        cursor: str = "",
    ) -> dict[str, Any]:
        principal = require_action(
            request, resource_type="attachment", resource_code="*", action="read"
        )
        c = container(request)
        try:
            window = TimeWindow.parse(start=start, end=end)
            page = PageWindow.parse(limit=limit, cursor=cursor)
            start_at, end_at = window.as_iso()
            values = [
                item
                for item in AdminReadRepository(c.database).attachments_in_window(start_at, end_at)
                if _scope(c, principal).permits(item)
                and (not session_id or item["session_id"] == session_id)
                and (not user_id or user_id in {item.get("internal_user_id"), item.get("user_id")})
                and (not mime or mime in {item.get("declared_mime"), item.get("detected_mime")})
                and (not status or item.get("status") == status)
            ]
            values = _after_cursor(values, page.cursor, "created_at")
            return _page(values, page, "created_at") | {
                "window": {"start": start_at, "end": end_at}
            }
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.get("/attachments/{attachment_id}")
    def attachment(request: Request, attachment_id: str) -> dict[str, Any]:
        principal = require_action(
            request, resource_type="attachment", resource_code="*", action="read"
        )
        c = container(request)
        item = AdminReadRepository(c.database).attachment_detail(attachment_id)
        if item is None or not _scope(c, principal).permits(item):
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="未找到附件")
        return {"attachment": item}

    return router


def _correlation_id(request: Request) -> str:
    return str(getattr(request.state, "correlation_id", "-"))


def _scope(c: Any, principal: Any) -> AdminScope:
    return AdminScope(
        strict_business_scope_summary(
            c.database,
            user_id=principal.user_id,
            global_access="platform-admin" in principal.role_codes,
        ),
        principal.user_id,
    )


def _after_cursor(
    items: list[dict[str, Any]], cursor: str, time_field: str
) -> list[dict[str, Any]]:
    if not cursor:
        return items
    timestamp, _, identifier = PageWindow.decode(cursor).partition("|")
    return [
        item
        for item in items
        if (str(item.get(time_field) or ""), str(item.get("id") or "")) < (timestamp, identifier)
    ]


def _page(items: list[dict[str, Any]], page: PageWindow, time_field: str) -> dict[str, Any]:
    selected = items[: page.limit + 1]
    has_more = len(selected) > page.limit
    selected = selected[: page.limit]
    next_cursor = None
    if has_more and selected:
        last = selected[-1]
        next_cursor = PageWindow.encode(f"{last.get(time_field) or ''}|{last.get('id') or ''}")
    return {
        "items": selected,
        "page": {"limit": page.limit, "has_more": has_more, "next_cursor": next_cursor},
    }
