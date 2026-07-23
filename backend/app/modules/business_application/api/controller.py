from __future__ import annotations

from typing import Any, Literal, cast

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.modules.identity.api.dependencies import (
    container,
    current_principal,
    require_csrf,
)
from app.shared.exceptions import AppError, NotFound, PermissionDenied


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ValidationErrorResponse(BaseModel):
    field: str
    message: str


class ValidationResponse(BaseModel):
    valid: bool = False
    errors: list[ValidationErrorResponse] = Field(default_factory=list)


class TriggerResponse(BaseModel):
    trigger_type: str
    connector_id: str
    routing_key: str
    normalized_routing_key: str = ""
    actor_policy: str
    service_account_user_id: str = ""
    enabled: bool
    config: dict[str, Any] = Field(default_factory=dict)


class DeliveryResponse(BaseModel):
    delivery_type: str
    connector_id: str
    enabled: bool
    config: dict[str, Any] = Field(default_factory=dict)


class CapabilityResponse(BaseModel):
    capability_code: str
    version_constraint: str = ""
    enabled: bool


class RevisionResponse(BaseModel):
    id: str
    application_id: str
    revision: int
    status: str
    agent_publication_id: str = ""
    workflow_publication_id: str = ""
    session_policy: dict[str, Any] = Field(default_factory=dict)
    execution_policy: dict[str, Any] = Field(default_factory=dict)
    validation: ValidationResponse = Field(default_factory=ValidationResponse)
    config_hash: str = ""
    triggers: list[TriggerResponse] = Field(default_factory=list)
    deliveries: list[DeliveryResponse] = Field(default_factory=list)
    capabilities: list[CapabilityResponse] = Field(default_factory=list)
    created_by: str = ""
    created_at: str = ""
    updated_at: str = ""


class PublicationResponse(BaseModel):
    id: str
    application_id: str
    revision_id: str
    revision: int
    schema_version: int
    snapshot: dict[str, Any] = Field(default_factory=dict)
    config_hash: str
    published_by: str
    published_at: str


class DeploymentResponse(BaseModel):
    id: str
    application_id: str
    environment: str
    publication_id: str = ""
    active: bool
    revision: int
    activated_by: str = ""
    activated_at: str = ""
    deactivated_by: str = ""
    deactivated_at: str = ""
    updated_at: str = ""
    runtime_wired: bool = False


class ApplicationSummaryResponse(BaseModel):
    id: str
    code: str
    name: str
    description: str
    project_code: str
    owner_user_id: str = ""
    status: str
    revision: int
    latest_publication_revision: int | None = None
    active_environments: list[str] = Field(default_factory=list)
    runtime_wired: bool = False


class ApplicationResponse(ApplicationSummaryResponse):
    draft: RevisionResponse | None = None
    publications: list[PublicationResponse] = Field(default_factory=list)
    deployments: list[DeploymentResponse] = Field(default_factory=list)
    capability_catalog_connected: bool = False


class ApplicationListResponse(BaseModel):
    items: list[ApplicationSummaryResponse]
    runtime_wired: bool = False


class ApplicationEnvelope(BaseModel):
    application: ApplicationResponse


class RevisionEnvelope(BaseModel):
    revision: RevisionResponse
    runtime_wired: bool = False


class PublicationEnvelope(BaseModel):
    publication: PublicationResponse
    runtime_wired: bool = False


class DeploymentEnvelope(BaseModel):
    deployment: DeploymentResponse


class PublicationListResponse(BaseModel):
    items: list[PublicationResponse]


class ComponentReferenceResponse(BaseModel):
    id: str
    code: str
    revision: int
    project_code: str
    status: str
    config_hash: str
    direction: str = ""
    component_type: str = ""


class CatalogResponse(BaseModel):
    agents: list[ComponentReferenceResponse]
    workflows: list[ComponentReferenceResponse]
    connectors: list[ComponentReferenceResponse]
    capabilities: list[dict[str, Any]]
    capability_catalog_connected: bool = False


class EffectiveApplicationResponse(BaseModel):
    id: str
    code: str
    project_code: str


class EffectiveResponse(BaseModel):
    application: EffectiveApplicationResponse
    deployment: DeploymentResponse
    publication: PublicationResponse
    runtime_wired: bool = False


class CreateApplicationRequest(StrictRequest):
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
    conversation_mode: Literal["channel", "actor", "application"] = "channel"
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


class CapabilityRequest(StrictRequest):
    capability_code: str = Field(min_length=2, max_length=120)
    version_constraint: str = Field(default="", max_length=80)
    enabled: bool = True


class SaveDraftRequest(StrictRequest):
    expected_revision: int = Field(ge=1)
    agent_publication_id: str = Field(default="", max_length=200)
    workflow_publication_id: str = Field(default="", max_length=200)
    session_policy: SessionPolicyRequest = Field(default_factory=SessionPolicyRequest)
    execution_policy: ExecutionPolicyRequest = Field(
        default_factory=ExecutionPolicyRequest
    )
    triggers: list[TriggerRequest] = Field(default_factory=list, max_length=20)
    deliveries: list[DeliveryRequest] = Field(default_factory=list, max_length=20)
    capabilities: list[CapabilityRequest] = Field(default_factory=list, max_length=100)


class ValidateRequest(StrictRequest):
    revision_id: str = Field(default="", max_length=200)


class PublishRequest(StrictRequest):
    revision_id: str = Field(min_length=1, max_length=200)


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

    @router.get("/_status")
    def status(request: Request) -> dict[str, Any]:
        principal = current_principal(request)
        return {
            "enabled": bool(
                container(
                    request
                ).settings.feature_configuration.business_application_control_plane_enabled
            ),
            "runtime_wired": False,
            "subject_id": principal.user_id,
        }

    @router.get("", response_model=ApplicationListResponse)
    def list_applications(
        request: Request,
        project_code: str = Query(default="", max_length=120),
        include_archived: bool = False,
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0, le=10000),
    ) -> dict[str, Any]:
        _require_enabled(request)
        principal = current_principal(request)
        try:
            values = container(request).business_application_service.list_applications(
                actor_id=principal.user_id,
                project_code=project_code,
                include_archived=include_archived,
                limit=limit,
                offset=offset,
            )
        except Exception as exc:
            raise _http_error(exc) from exc
        return {"items": values, "runtime_wired": False}

    @router.post("", response_model=ApplicationEnvelope)
    def create_application(
        request: Request, payload: CreateApplicationRequest
    ) -> dict[str, Any]:
        _require_enabled(request)
        principal = _write_principal(request)
        try:
            application = container(request).business_application_service.create(
                actor_id=principal.user_id,
                **payload.model_dump(),
            )
        except Exception as exc:
            raise _http_error(exc) from exc
        return {"application": application}

    @router.get("/{code}", response_model=ApplicationEnvelope)
    def get_application(request: Request, code: str) -> dict[str, Any]:
        _require_enabled(request)
        principal = current_principal(request)
        try:
            application = container(request).business_application_service.detail(
                actor_id=principal.user_id, code=code
            )
        except PermissionDenied as exc:
            raise HTTPException(status_code=404, detail="Business Application not found") from exc
        except Exception as exc:
            raise _http_error(exc) from exc
        return {"application": application}

    @router.put("/{code}", response_model=ApplicationEnvelope)
    def update_application(
        request: Request, code: str, payload: UpdateApplicationRequest
    ) -> dict[str, Any]:
        _require_enabled(request)
        principal = _write_principal(request)
        try:
            application = container(request).business_application_service.update_metadata(
                actor_id=principal.user_id,
                code=code,
                **payload.model_dump(),
            )
        except Exception as exc:
            raise _http_error(exc) from exc
        return {"application": application}

    @router.put("/{code}/draft", response_model=RevisionEnvelope)
    def save_draft(
        request: Request, code: str, payload: SaveDraftRequest
    ) -> dict[str, Any]:
        _require_enabled(request)
        principal = _write_principal(request)
        body = payload.model_dump()
        expected_revision = int(body.pop("expected_revision"))
        try:
            revision = container(request).business_application_service.save_draft(
                actor_id=principal.user_id,
                code=code,
                expected_revision=expected_revision,
                payload=body,
            )
        except Exception as exc:
            raise _http_error(exc) from exc
        return {"revision": revision, "runtime_wired": False}

    @router.post("/{code}/validate", response_model=RevisionEnvelope)
    def validate_application(
        request: Request, code: str, payload: ValidateRequest
    ) -> dict[str, Any]:
        _require_enabled(request)
        principal = _write_principal(request)
        try:
            revision = container(request).business_application_service.validate(
                actor_id=principal.user_id,
                code=code,
                revision_id=payload.revision_id,
            )
        except Exception as exc:
            raise _http_error(exc) from exc
        return {"revision": revision}

    @router.post("/{code}/publish", response_model=PublicationEnvelope)
    def publish_application(
        request: Request, code: str, payload: PublishRequest
    ) -> dict[str, Any]:
        _require_enabled(request)
        principal = _write_principal(request)
        try:
            publication = container(request).business_application_service.publish(
                actor_id=principal.user_id,
                code=code,
                revision_id=payload.revision_id,
            )
        except Exception as exc:
            raise _http_error(exc) from exc
        return {"publication": publication, "runtime_wired": False}

    @router.get("/{code}/publications", response_model=PublicationListResponse)
    def publications(request: Request, code: str) -> dict[str, Any]:
        _require_enabled(request)
        principal = current_principal(request)
        try:
            values = container(request).business_application_service.publications(
                actor_id=principal.user_id, code=code
            )
        except PermissionDenied as exc:
            raise HTTPException(status_code=404, detail="Business Application not found") from exc
        except Exception as exc:
            raise _http_error(exc) from exc
        return {"items": values}

    @router.get("/{code}/catalog", response_model=CatalogResponse)
    def catalog(request: Request, code: str) -> dict[str, Any]:
        _require_enabled(request)
        principal = current_principal(request)
        try:
            return cast(
                dict[str, Any],
                container(request).business_application_service.catalog(
                    actor_id=principal.user_id, code=code
                ),
            )
        except PermissionDenied as exc:
            raise HTTPException(status_code=404, detail="Business Application not found") from exc
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.post(
        "/{code}/environments/{environment}/activate",
        response_model=DeploymentEnvelope,
    )
    def activate(
        request: Request,
        code: str,
        environment: str,
        payload: ActivateRequest,
    ) -> dict[str, Any]:
        _require_enabled(request)
        principal = _write_principal(request)
        try:
            deployment = container(request).business_application_service.activate(
                actor_id=principal.user_id,
                code=code,
                environment=environment,
                publication_id=payload.publication_id,
                expected_revision=payload.expected_revision,
            )
        except Exception as exc:
            raise _http_error(exc) from exc
        return {"deployment": deployment}

    @router.post(
        "/{code}/environments/{environment}/deactivate",
        response_model=DeploymentEnvelope,
    )
    def deactivate(
        request: Request,
        code: str,
        environment: str,
        payload: DeactivateRequest,
    ) -> dict[str, Any]:
        _require_enabled(request)
        principal = _write_principal(request)
        try:
            deployment = container(request).business_application_service.deactivate(
                actor_id=principal.user_id,
                code=code,
                environment=environment,
                expected_revision=payload.expected_revision,
            )
        except Exception as exc:
            raise _http_error(exc) from exc
        return {"deployment": deployment}

    @router.get("/{code}/effective", response_model=EffectiveResponse)
    def effective(
        request: Request,
        code: str,
        environment: str = Query(default="test", max_length=40),
    ) -> dict[str, Any]:
        _require_enabled(request)
        principal = current_principal(request)
        try:
            container(request).business_application_service.detail(
                actor_id=principal.user_id, code=code
            )
            return cast(
                dict[str, Any],
                container(request).business_application_resolver.resolve_active(
                    code, environment
                ),
            )
        except PermissionDenied as exc:
            raise HTTPException(status_code=404, detail="Business Application not found") from exc
        except Exception as exc:
            raise _http_error(exc) from exc

    return router


def _write_principal(request: Request) -> Any:
    principal = current_principal(request)
    require_csrf(request, principal)
    return principal


def _require_enabled(request: Request) -> None:
    if not (
        container(
            request
        ).settings.feature_configuration.business_application_control_plane_enabled
    ):
        raise HTTPException(
            status_code=404,
            detail={
                "code": "business_application_control_plane_disabled",
                "message": "Business Application control plane is disabled",
            },
        )


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PermissionDenied):
        return HTTPException(
            status_code=403,
            detail={"code": "forbidden", "message": exc.safe_message},
        )
    if isinstance(exc, NotFound):
        return HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": exc.safe_message},
        )
    if isinstance(exc, AppError):
        status = {
            "revision_conflict": 409,
            "route_conflict": 409,
            "application_active": 409,
            "integrity_error": 409,
            "validation_failed": 422,
            "capability_catalog_unavailable": 422,
        }.get(exc.error_code, 400)
        detail: dict[str, Any] = {
            "code": exc.error_code or "invalid_request",
            "message": exc.safe_message,
            "field_errors": exc.field_errors,
        }
        if exc.error_code == "revision_conflict":
            detail["current_revision"] = exc.diagnostics.get("current_revision")
        if exc.error_code == "route_conflict":
            detail["conflict_application_id"] = exc.diagnostics.get(
                "conflict_application_id"
            )
        return HTTPException(status_code=status, detail=detail)
    if isinstance(exc, ValueError):
        return HTTPException(
            status_code=422,
            detail={"code": "validation_failed", "message": str(exc)},
        )
    return HTTPException(status_code=500, detail="Internal server error")
