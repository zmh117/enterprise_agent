from __future__ import annotations

from typing import Any, Literal, cast

from fastapi import APIRouter, Header, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.modules.identity.api.dependencies import (
    container,
    current_principal,
    handle_exception,
    require_action,
)


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateApplicationRequest(StrictRequest):
    expected_revision: Literal[0]
    code: str = Field(min_length=2, max_length=120)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    project_code: str = Field(min_length=2, max_length=120)
    owner_user_id: str = Field(default="", max_length=200)


class UpdateApplicationRequest(StrictRequest):
    expected_revision: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    project_code: str = Field(min_length=2, max_length=120)
    owner_user_id: str = Field(default="", max_length=200)
    status: Literal["enabled", "disabled", "archived"]


class SessionPolicyRequest(StrictRequest):
    conversation_mode: Literal["channel"] = "channel"
    recent_message_limit: int = Field(default=20, ge=1, le=100)
    retention_days: int = Field(default=30, ge=1, le=3650)
    continuous_conversation_enabled: bool = False
    attachments_enabled: bool = False


class ExecutionPolicyRequest(StrictRequest):
    max_turns: int = Field(default=12, ge=1, le=100)
    timeout_seconds: int = Field(default=300, ge=10, le=3600)
    max_tool_calls: int = Field(default=30, ge=0, le=200)


class TriggerConfigRequest(StrictRequest):
    conversation_type: str = Field(default="", max_length=80)
    require_mention: bool = False
    webhook_definition_id: str = Field(default="", max_length=200)


class TriggerRequest(StrictRequest):
    trigger_type: Literal["dingtalk_private", "dingtalk_group", "webhook"]
    connector_id: str = Field(min_length=1, max_length=200)
    routing_key: str = Field(min_length=1, max_length=240)
    actor_policy: Literal["CURRENT_SENDER", "SERVICE_ACCOUNT"]
    service_account_user_id: str = Field(default="", max_length=200)
    enabled: bool = True
    config: TriggerConfigRequest = Field(default_factory=TriggerConfigRequest)


class DeliveryConfigRequest(StrictRequest):
    target_reference: str = Field(default="", max_length=240)
    reply_mode: str = Field(default="", max_length=80)


class DeliveryRequest(StrictRequest):
    delivery_type: Literal[
        "reply_original", "dingtalk_private", "dingtalk_group", "webhook_callback"
    ]
    connector_id: str = Field(min_length=1, max_length=200)
    enabled: bool = True
    config: DeliveryConfigRequest = Field(default_factory=DeliveryConfigRequest)


class SaveDraftRequest(StrictRequest):
    expected_revision: int = Field(ge=1)
    agent_publication_id: str = Field(min_length=1, max_length=200)
    mcp_tool_publication_ids: list[str] = Field(default_factory=list, max_length=100)
    session_policy: SessionPolicyRequest = Field(default_factory=SessionPolicyRequest)
    execution_policy: ExecutionPolicyRequest = Field(default_factory=ExecutionPolicyRequest)
    triggers: list[TriggerRequest] = Field(default_factory=list, max_length=20)
    deliveries: list[DeliveryRequest] = Field(default_factory=list, max_length=20)


class ValidateRequest(StrictRequest):
    revision_id: str = Field(default="", max_length=200)
    expected_revision: int = Field(ge=1)


class PublishRequest(StrictRequest):
    revision_id: str = Field(min_length=1, max_length=200)
    expected_revision: int = Field(ge=1)


class ActivateRequest(StrictRequest):
    publication_id: str = Field(min_length=1, max_length=200)
    expected_revision: int = Field(ge=0)


class DeactivateRequest(StrictRequest):
    expected_revision: int = Field(ge=1)


def build_business_application_router() -> APIRouter:
    router = APIRouter(
        prefix="/api/admin/business-applications",
        tags=["business-applications"],
    )

    @router.get("")
    def list_applications(
        request: Request,
        project_code: str = Query(default="", max_length=120),
        include_archived: bool = False,
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0, le=10000),
    ) -> dict[str, Any]:
        principal = current_principal(request)
        try:
            items = container(request).business_application_service.list_applications(
                actor_id=principal.user_id,
                project_code=project_code,
                include_archived=include_archived,
                limit=limit,
                offset=offset,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        can_create = (
            container(request)
            .authorization_evaluator.decide(
                user_id=principal.user_id,
                resource_type="business_application",
                resource_code="*",
                action="create",
            )
            .allowed
        )
        return {"items": items, "permissions": {"can_create": can_create}}

    @router.post("")
    def create_application(
        request: Request,
        payload: CreateApplicationRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="business_application",
            resource_code="*",
            action="create",
            csrf=True,
        )
        try:
            application = container(request).business_application_service.create(
                actor_id=principal.user_id,
                expected_revision=payload.expected_revision,
                idempotency_key=idempotency_key,
                **payload.model_dump(exclude={"expected_revision"}),
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"application": application}

    @router.get("/{code}")
    def get_application(request: Request, code: str) -> dict[str, Any]:
        principal = current_principal(request)
        try:
            application = container(request).business_application_service.detail(
                actor_id=principal.user_id,
                code=code,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        authorization = container(request).authorization_evaluator
        application["permissions"] = {
            action: authorization.decide(
                user_id=principal.user_id,
                resource_type="business_application",
                resource_code=code,
                action=action,
            ).allowed
            for action in ("edit", "publish", "activate")
        }
        return {"application": application}

    @router.put("/{code}")
    def update_application(
        request: Request,
        code: str,
        payload: UpdateApplicationRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="business_application",
            resource_code=code,
            action="edit",
            csrf=True,
        )
        try:
            application = container(request).business_application_service.update_metadata(
                actor_id=principal.user_id,
                code=code,
                idempotency_key=idempotency_key,
                **payload.model_dump(),
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"application": application}

    @router.put("/{code}/draft")
    def save_draft(
        request: Request,
        code: str,
        payload: SaveDraftRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="business_application",
            resource_code=code,
            action="edit",
            csrf=True,
        )
        body = payload.model_dump()
        expected_revision = int(body.pop("expected_revision"))
        try:
            revision = container(request).business_application_service.save_draft(
                actor_id=principal.user_id,
                code=code,
                expected_revision=expected_revision,
                payload=body,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"revision": revision}

    @router.post("/{code}/validate")
    def validate_application(
        request: Request,
        code: str,
        payload: ValidateRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="business_application",
            resource_code=code,
            action="edit",
            csrf=True,
        )
        try:
            revision = container(request).business_application_service.validate(
                actor_id=principal.user_id,
                code=code,
                revision_id=payload.revision_id,
                expected_revision=payload.expected_revision,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"revision": revision}

    @router.post("/{code}/publish")
    def publish_application(
        request: Request,
        code: str,
        payload: PublishRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="business_application",
            resource_code=code,
            action="publish",
            csrf=True,
        )
        try:
            publication = container(request).business_application_service.publish(
                actor_id=principal.user_id,
                code=code,
                revision_id=payload.revision_id,
                expected_revision=payload.expected_revision,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"publication": publication}

    @router.get("/{code}/publications")
    def publications(request: Request, code: str) -> dict[str, Any]:
        principal = current_principal(request)
        try:
            items = container(request).business_application_service.publications(
                actor_id=principal.user_id,
                code=code,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"items": items}

    @router.post("/{code}/environments/{environment}/activate")
    def activate_application(
        request: Request,
        code: str,
        environment: str,
        payload: ActivateRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="business_application",
            resource_code=code,
            action="activate",
            csrf=True,
        )
        try:
            deployment = container(request).business_application_service.activate(
                actor_id=principal.user_id,
                code=code,
                environment=environment,
                idempotency_key=idempotency_key,
                **payload.model_dump(),
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"deployment": deployment}

    @router.post("/{code}/environments/{environment}/deactivate")
    def deactivate_application(
        request: Request,
        code: str,
        environment: str,
        payload: DeactivateRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="business_application",
            resource_code=code,
            action="activate",
            csrf=True,
        )
        try:
            deployment = container(request).business_application_service.deactivate(
                actor_id=principal.user_id,
                code=code,
                environment=environment,
                expected_revision=payload.expected_revision,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"deployment": deployment}

    @router.get("/{code}/environments/{environment}/effective")
    def effective(request: Request, code: str, environment: str) -> dict[str, Any]:
        principal = current_principal(request)
        try:
            return cast(
                dict[str, Any],
                container(request).business_application_service.effective(
                    actor_id=principal.user_id,
                    code=code,
                    environment=environment,
                ),
            )
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.get("/{code}/catalog")
    def catalog(request: Request, code: str) -> dict[str, Any]:
        principal = current_principal(request)
        try:
            return cast(
                dict[str, Any],
                container(request).business_application_service.catalog(
                    actor_id=principal.user_id,
                    code=code,
                ),
            )
        except Exception as exc:
            raise handle_exception(exc) from exc

    return router
