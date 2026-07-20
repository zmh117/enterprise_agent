from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from app.modules.identity.api.dependencies import container, handle_exception, require_action


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AuthenticationRequest(StrictRequest):
    type: Literal["bearer_v1", "hmac_sha256_v1"]
    secret_ref: str = Field(min_length=1, max_length=500)
    timestamp_header: str = Field(default="x-webhook-timestamp", max_length=100)
    nonce_header: str = Field(default="x-webhook-nonce", max_length=100)
    signature_header: str = Field(default="x-webhook-signature", max_length=100)
    window_seconds: int = Field(default=300, ge=30, le=900)


class FilterRequest(StrictRequest):
    pointer: str = Field(max_length=512)
    operator: Literal["exists", "equals", "in", "not_equals"]
    value: Any = None


class MappingRequest(StrictRequest):
    variables: dict[str, str] = Field(default_factory=dict)
    filters: list[FilterRequest] = Field(default_factory=list, max_length=50)
    message_template: str = Field(default="", max_length=10000)
    event_id_pointer: str = Field(default="", max_length=512)
    status_pointer: str = Field(default="", max_length=512)


class RoutingRuleRequest(StrictRequest):
    mode: Literal["fixed", "extract"]
    value: str = Field(default="", max_length=200)
    pointer: str = Field(default="", max_length=512)
    allowed_values: list[str] = Field(default_factory=list, max_length=500)


class RoutingRequest(StrictRequest):
    project_code: RoutingRuleRequest
    environment: RoutingRuleRequest
    base: RoutingRuleRequest
    workshop: RoutingRuleRequest
    service: RoutingRuleRequest


class AgentRequest(StrictRequest):
    code: str = Field(default="default-diagnostic-agent", max_length=120)
    publication_id: str = Field(min_length=1, max_length=200)


class DeliveryRequest(StrictRequest):
    type: str = Field(min_length=1, max_length=120)
    connector_id: str = Field(min_length=1, max_length=200)
    target: dict[str, Any] = Field(default_factory=dict)
    options: dict[str, Any] = Field(default_factory=dict)


class IdempotencyRequest(StrictRequest):
    cooldown_seconds: int = Field(default=300, ge=0, le=86400)


class LimitsRequest(StrictRequest):
    requests_per_minute: int = Field(default=60, ge=1, le=10000)
    max_in_flight: int = Field(default=10, ge=1, le=1000)
    max_alerts: int = Field(default=20, ge=1, le=100)


class TriggerConfigRequest(StrictRequest):
    schema_version: Literal[1] = 1
    adapter: Literal["grafana_alertmanager_v1", "generic_json_v1"]
    authentication: AuthenticationRequest
    mapping: MappingRequest
    routing: RoutingRequest
    agent: AgentRequest
    delivery: DeliveryRequest
    idempotency: IdempotencyRequest = Field(default_factory=IdempotencyRequest)
    limits: LimitsRequest = Field(default_factory=LimitsRequest)


class CreateTriggerRequest(StrictRequest):
    code: str = Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")
    name: str = Field(min_length=1, max_length=200)
    trigger_type: Literal["grafana", "generic"]
    connector_id: str = Field(min_length=1, max_length=200)
    config: TriggerConfigRequest | None = None


class UpdateTriggerRequest(StrictRequest):
    expected_revision: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=200)
    connector_id: str = Field(min_length=1, max_length=200)
    status: Literal["enabled", "disabled"]


class SaveRevisionRequest(StrictRequest):
    expected_revision: int = Field(ge=0)
    config: TriggerConfigRequest


class PreviewRequest(StrictRequest):
    sample_payload: dict[str, Any]


class RollbackRequest(StrictRequest):
    publication_id: str
    expected_revision: int = Field(ge=1)


class RotateRequest(StrictRequest):
    expected_revision: int = Field(ge=1)
    confirm: bool


class ServiceAccountStatusRequest(StrictRequest):
    expected_revision: int = Field(ge=1)
    enabled: bool


def build_webhook_admin_router() -> APIRouter:
    router = APIRouter(prefix="/api/admin", tags=["webhook-administration"])

    @router.get("/webhook-triggers")
    def list_triggers(request: Request) -> dict[str, Any]:
        principal = require_action(
            request, resource_type="webhook_trigger", resource_code="*", action="read"
        )
        try:
            return {"triggers": container(request).webhook_trigger_service.list(actor_id=principal.user_id)}
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.get("/webhook-triggers/catalog")
    def catalog(request: Request) -> dict[str, Any]:
        require_action(
            request, resource_type="webhook_trigger", resource_code="*", action="read"
        )
        c = container(request)
        try:
            publication = c.agent_config_service.current_publication(
                c.settings.identity.default_agent_code
            )
            definition = c.agent_config_service.repository.get_definition(
                c.settings.identity.default_agent_code
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {
            "agent": {
                "code": definition["code"],
                "name": definition["name"],
                "publication_id": publication["id"],
                "revision": publication["revision"],
                "config_hash": publication["config_hash"],
                "read_only_tools": sorted(
                    c.agent_config_service.repository.publication_tools(
                        str(publication["id"])
                    )
                ),
            },
            "connectors": c.agent_config_service.repository.connector_catalog(),
        }

    @router.post("/webhook-triggers")
    def create_trigger(request: Request, payload: CreateTriggerRequest) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="webhook_trigger",
            resource_code="*",
            action="edit",
            csrf=True,
        )
        try:
            created = container(request).webhook_trigger_service.create(
                actor_id=principal.user_id,
                code=payload.code,
                name=payload.name,
                trigger_type=payload.trigger_type,
                connector_id=payload.connector_id,
                config=payload.config.model_dump() if payload.config else None,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"trigger": created}

    @router.get("/webhook-triggers/{code}")
    def get_trigger(request: Request, code: str) -> dict[str, Any]:
        principal = require_action(
            request, resource_type="webhook_trigger", resource_code=code, action="read"
        )
        try:
            value = container(request).webhook_trigger_service.get(
                actor_id=principal.user_id, code=code
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"trigger": value}

    @router.patch("/webhook-triggers/{code}")
    def update_trigger(
        request: Request, code: str, payload: UpdateTriggerRequest
    ) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="webhook_trigger",
            resource_code=code,
            action="edit",
            csrf=True,
        )
        try:
            value = container(request).webhook_trigger_service.update_definition(
                actor_id=principal.user_id,
                code=code,
                expected_revision=payload.expected_revision,
                name=payload.name,
                connector_id=payload.connector_id,
                status=payload.status,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"definition": value}

    @router.post("/webhook-triggers/{code}/revisions")
    def save_revision(
        request: Request, code: str, payload: SaveRevisionRequest
    ) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="webhook_trigger",
            resource_code=code,
            action="edit",
            csrf=True,
        )
        try:
            revision = container(request).webhook_trigger_service.save_draft(
                actor_id=principal.user_id,
                code=code,
                expected_revision=payload.expected_revision,
                config=payload.config.model_dump(),
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"revision": revision}

    @router.post("/webhook-triggers/{code}/revisions/{revision_id}/validate")
    def validate_revision(request: Request, code: str, revision_id: str) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="webhook_trigger",
            resource_code=code,
            action="edit",
            csrf=True,
        )
        try:
            revision = container(request).webhook_trigger_service.validate_revision(
                actor_id=principal.user_id, code=code, revision_id=revision_id
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"revision": revision}

    @router.post("/webhook-triggers/{code}/revisions/{revision_id}/preview")
    def preview_revision(
        request: Request, code: str, revision_id: str, payload: PreviewRequest
    ) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="webhook_trigger",
            resource_code=code,
            action="edit",
            csrf=True,
        )
        try:
            preview = container(request).webhook_trigger_service.preview(
                actor_id=principal.user_id,
                code=code,
                revision_id=revision_id,
                sample_payload=payload.sample_payload,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"preview": preview}

    @router.post("/webhook-triggers/{code}/revisions/{revision_id}/publish")
    def publish_revision(request: Request, code: str, revision_id: str) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="webhook_trigger",
            resource_code=code,
            action="publish",
            csrf=True,
        )
        try:
            publication = container(request).webhook_trigger_service.publish(
                actor_id=principal.user_id, code=code, revision_id=revision_id
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"publication": publication}

    @router.post("/webhook-triggers/{code}/publications/{publication_id}/rollback")
    def rollback(
        request: Request, code: str, publication_id: str, payload: RollbackRequest
    ) -> dict[str, Any]:
        if payload.publication_id != publication_id:
            from app.shared.exceptions import NonRetryableExecutionError

            raise handle_exception(
                NonRetryableExecutionError(
                    "Publication path and body mismatch", safe_message="Publication ID mismatch"
                )
            )
        principal = require_action(
            request,
            resource_type="webhook_trigger",
            resource_code=code,
            action="publish",
            csrf=True,
        )
        try:
            publication = container(request).webhook_trigger_service.rollback(
                actor_id=principal.user_id,
                code=code,
                publication_id=publication_id,
                expected_revision=payload.expected_revision,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"publication": publication}

    @router.post("/webhook-triggers/{code}/rotate-public-id")
    def rotate_public_id(request: Request, code: str, payload: RotateRequest) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="webhook_trigger",
            resource_code=code,
            action="rotate",
            csrf=True,
        )
        try:
            definition = container(request).webhook_trigger_service.rotate_public_id(
                actor_id=principal.user_id,
                code=code,
                expected_revision=payload.expected_revision,
                confirm=payload.confirm,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {
            "definition": definition,
            "ingress_path": f"/webhooks/v1/{definition['public_id']}",
        }

    @router.put("/webhook-triggers/{code}/service-account")
    def service_account_status(
        request: Request, code: str, payload: ServiceAccountStatusRequest
    ) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="webhook_trigger",
            resource_code=code,
            action="manage_service_account",
            csrf=True,
        )
        try:
            definition = container(request).webhook_trigger_service.set_service_account_enabled(
                actor_id=principal.user_id,
                code=code,
                expected_revision=payload.expected_revision,
                enabled=payload.enabled,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"definition": definition}

    @router.get("/webhook-triggers/{code}/events")
    def events(
        request: Request,
        code: str,
        status: str = "",
        job_id: str = "",
        received_from: str = "",
        received_to: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        require_action(
            request, resource_type="webhook_trigger", resource_code=code, action="read"
        )
        c = container(request)
        try:
            definition = c.webhook_trigger_repository.get_definition(code)
            values = c.webhook_event_repository.list_events(
                trigger_id=str(definition["id"]),
                status=status,
                job_id=job_id,
                received_from=received_from,
                received_to=received_to,
                limit=limit,
                offset=offset,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"events": values, "limit": min(max(limit, 1), 200), "offset": max(offset, 0)}

    @router.get("/webhook-events/{event_id}")
    def event_detail(request: Request, event_id: str) -> dict[str, Any]:
        principal = require_action(
            request, resource_type="webhook_trigger", resource_code="*", action="read"
        )
        del principal
        c = container(request)
        try:
            event = c.webhook_event_repository.get(event_id)
            evidence = _event_evidence(c, event)
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"event": event, "evidence": evidence}

    return router


def _event_evidence(c: Any, event: dict[str, Any]) -> dict[str, Any]:
    job_id = str(event.get("job_id") or "")
    if not job_id:
        return {
            "job": None,
            "tool_calls": [],
            "audit": [],
            "delivery_attempts": [],
            "delivery_chunks": [],
        }
    job = c.agent_repository.get_job_detail(job_id)
    job.pop("result", None)
    job.pop("user_message", None)
    tool_calls = [
        {
            "id": item["id"],
            "tool_name": item["tool_name"],
            "status": item["status"],
            "duration_ms": item["duration_ms"],
            "risk_level": item["risk_level"],
            "created_at": item["created_at"],
        }
        for item in c.agent_repository.list_tool_calls(job_id)
    ]
    audit = c.database.execute(
        """
        select id, event_type, status, summary, created_at
        from audit_event where job_id = ? order by created_at, id
        """,
        (job_id,),
    )
    delivery = c.database.execute(
        """
        select id, route_type, connector_id, target_summary, status,
               error_message, created_at, finished_at
        from delivery_attempt where job_id = ? order by created_at, id
        """,
        (job_id,),
    )
    chunks = c.database.execute(
        """
        select c.id, c.attempt_id, c.chunk_index, c.chunk_count, c.status,
               c.payload_summary, c.error_message, c.created_at
        from delivery_chunk c
        join delivery_attempt a on a.id = c.attempt_id
        where a.job_id = ? order by c.created_at, c.id
        """,
        (job_id,),
    )
    return {
        "job": job,
        "tool_calls": tool_calls,
        "audit": audit,
        "delivery_attempts": delivery,
        "delivery_chunks": chunks,
    }
