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


class RuntimeComponentResponse(BaseModel):
    status: Literal[
        "wired",
        "partially_wired",
        "stored_only",
        "unsupported",
        "blocked",
    ]
    reason_code: str
    message: str
    fields: dict[str, str] = Field(default_factory=dict)
    impact: Literal["runtime", "governance"] = "runtime"


class RuntimeStateResponse(BaseModel):
    runtime_wired: bool = False
    runtime_status: Literal[
        "not_wired",
        "partially_wired",
        "wired",
        "blocked",
    ] = "not_wired"
    runtime_environment: str = ""
    deployment_environment: str = ""
    reason_code: str = "no_active_deployment"
    message: str = ""
    runtime_components: dict[str, RuntimeComponentResponse] = Field(default_factory=dict)
    affected_routes: list[dict[str, str]] = Field(default_factory=list)
    legacy_fallback_enabled: bool = False


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


class TaskFileFeaturesResponse(StrictRequest):
    workspace_enabled: bool = False
    file_mcp_enabled: bool = False
    runtime_file_edit_enabled: bool = False
    default_file_delivery_enabled: bool = False


class RevisionResponse(BaseModel):
    id: str
    application_id: str
    revision: int
    status: str
    agent_publication_id: str = ""
    workflow_publication_id: str = ""
    task_workspace_retention_period: Literal["DAY", "WEEK", "MONTH"] = "WEEK"
    document_processing_profile_code: Literal[
        "NONE", "docling-layout-ocr-v2"
    ] = "NONE"
    document_processing_status: Literal[
        "DISABLED", "CONFIGURED_UNAVAILABLE", "READY"
    ] = "DISABLED"
    document_processing_reason_code: str = "profile_disabled"
    task_file_features: TaskFileFeaturesResponse = Field(default_factory=TaskFileFeaturesResponse)
    session_policy: dict[str, Any] = Field(default_factory=dict)
    execution_policy: dict[str, Any] = Field(default_factory=dict)
    validation: ValidationResponse = Field(default_factory=ValidationResponse)
    config_hash: str = ""
    triggers: list[TriggerResponse] = Field(default_factory=list)
    deliveries: list[DeliveryResponse] = Field(default_factory=list)
    mcp_tools: list[dict[str, Any]] = Field(default_factory=list)
    created_by: str = ""
    created_at: str = ""
    updated_at: str = ""


class PublicationResponse(RuntimeStateResponse):
    id: str
    application_id: str
    revision_id: str
    revision: int
    schema_version: int
    snapshot: dict[str, Any] = Field(default_factory=dict)
    config_hash: str
    published_by: str
    published_at: str
    task_workspace_retention_period: Literal["DAY", "WEEK", "MONTH"] = "WEEK"
    task_workspace_retention_source: Literal["publication_snapshot"] = "publication_snapshot"
    document_processing_profile_code: Literal[
        "NONE", "docling-layout-ocr-v2"
    ] = "NONE"
    document_processing_profile_version: str = ""
    document_processing_profile_hash: str = ""
    document_processing_profile_source: Literal["publication_snapshot"] = (
        "publication_snapshot"
    )
    document_processing_status: Literal[
        "DISABLED", "CONFIGURED_UNAVAILABLE", "READY"
    ] = "DISABLED"
    document_processing_reason_code: str = "profile_disabled"
    task_file_features: TaskFileFeaturesResponse = Field(default_factory=TaskFileFeaturesResponse)
    task_file_features_source: Literal["publication_snapshot"] = "publication_snapshot"


class DeploymentResponse(RuntimeStateResponse):
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


class ApplicationSummaryResponse(RuntimeStateResponse):
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
    task_workspace_retention_period: Literal["DAY", "WEEK", "MONTH"] = "WEEK"
    document_processing_profile_code: Literal[
        "NONE", "docling-layout-ocr-v2"
    ] = "NONE"
    document_processing_status: Literal[
        "DISABLED", "CONFIGURED_UNAVAILABLE", "READY"
    ] = "DISABLED"
    document_processing_reason_code: str = "profile_disabled"


class ApplicationResponse(ApplicationSummaryResponse):
    draft: RevisionResponse | None = None
    publications: list[PublicationResponse] = Field(default_factory=list)
    deployments: list[DeploymentResponse] = Field(default_factory=list)


class ApplicationListResponse(RuntimeStateResponse):
    items: list[ApplicationSummaryResponse]


class ApplicationEnvelope(BaseModel):
    application: ApplicationResponse


class RevisionEnvelope(RuntimeStateResponse):
    revision: RevisionResponse


class PublicationEnvelope(RuntimeStateResponse):
    publication: PublicationResponse


class DeploymentEnvelope(BaseModel):
    deployment: DeploymentResponse


class PublicationListResponse(RuntimeStateResponse):
    items: list[PublicationResponse]


class ComponentReferenceResponse(BaseModel):
    id: str
    code: str
    revision: int
    project_code: str
    status: str
    config_hash: str
    runtime_kind: Literal["python-v1"] | None = None
    runtime_protocol_versions: list[Literal["1.3"]] | None = None
    direction: str = ""
    component_type: str = ""


class CatalogResponse(BaseModel):
    agents: list[ComponentReferenceResponse]
    workflows: list[ComponentReferenceResponse]
    connectors: list[ComponentReferenceResponse]
    document_processing_profiles: list[dict[str, Any]] = Field(default_factory=list)
    mcp_tools_by_agent_publication: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)


class EffectiveApplicationResponse(BaseModel):
    id: str
    code: str
    project_code: str


class EffectiveResponse(RuntimeStateResponse):
    application: EffectiveApplicationResponse
    deployment: DeploymentResponse
    publication: PublicationResponse


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
    agent_publication_id: str = Field(default="", max_length=200)
    workflow_publication_id: str = Field(default="", max_length=200)
    task_workspace_retention_period: Literal["DAY", "WEEK", "MONTH"] = "WEEK"
    document_processing_profile_code: Literal[
        "NONE", "docling-layout-ocr-v2"
    ] = "NONE"
    task_file_features: TaskFileFeaturesResponse = Field(default_factory=TaskFileFeaturesResponse)
    session_policy: SessionPolicyRequest = Field(default_factory=SessionPolicyRequest)
    execution_policy: ExecutionPolicyRequest = Field(default_factory=ExecutionPolicyRequest)
    triggers: list[TriggerRequest] = Field(default_factory=list, max_length=20)
    deliveries: list[DeliveryRequest] = Field(default_factory=list, max_length=20)
    mcp_tools: list[str] = Field(default_factory=list, max_length=100)


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
        runtime = (
            container(request).business_application_service.runtime_evaluator.empty().to_dict()
        )
        return {
            "enabled": bool(
                container(
                    request
                ).settings.feature_configuration.business_application_control_plane_enabled
            ),
            **runtime,
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
        return {"items": values, **_aggregate_runtime(values, request)}

    @router.post("", response_model=ApplicationEnvelope)
    def create_application(request: Request, payload: CreateApplicationRequest) -> dict[str, Any]:
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
            raise HTTPException(status_code=404, detail="未找到业务应用") from exc
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
    def save_draft(request: Request, code: str, payload: SaveDraftRequest) -> dict[str, Any]:
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
        return {
            "revision": revision,
            **container(request).business_application_service.runtime_evaluator.empty().to_dict(),
        }

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
        return {
            "revision": revision,
            **container(request).business_application_service.runtime_evaluator.empty().to_dict(),
        }

    @router.post("/{code}/publish", response_model=PublicationEnvelope)
    def publish_application(request: Request, code: str, payload: PublishRequest) -> dict[str, Any]:
        _require_enabled(request)
        principal = _write_principal(request)
        try:
            publication = container(request).business_application_service.publish(
                actor_id=principal.user_id,
                code=code,
                revision_id=payload.revision_id,
                correlation_id=str(getattr(request.state, "correlation_id", "") or ""),
            )
        except Exception as exc:
            raise _http_error(exc) from exc
        runtime = container(request).business_application_service.runtime_evaluator.evaluate(
            snapshot=dict(publication.get("snapshot") or {}),
            deployment=None,
        )
        return {"publication": publication, **runtime.to_dict()}

    @router.get("/{code}/publications", response_model=PublicationListResponse)
    def publications(request: Request, code: str) -> dict[str, Any]:
        _require_enabled(request)
        principal = current_principal(request)
        try:
            values = container(request).business_application_service.publications(
                actor_id=principal.user_id, code=code
            )
        except PermissionDenied as exc:
            raise HTTPException(status_code=404, detail="未找到业务应用") from exc
        except Exception as exc:
            raise _http_error(exc) from exc
        return {"items": values, **_aggregate_runtime(values, request)}

    @router.get(
        "/{code}/catalog",
        response_model=CatalogResponse,
        response_model_exclude_none=True,
    )
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
            raise HTTPException(status_code=404, detail="未找到业务应用") from exc
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
        environment: str = Query(default="local", max_length=40),
    ) -> dict[str, Any]:
        _require_enabled(request)
        principal = current_principal(request)
        try:
            container(request).business_application_service.detail(
                actor_id=principal.user_id, code=code
            )
            return cast(
                dict[str, Any],
                container(request).business_application_resolver.resolve_active(code, environment),
            )
        except PermissionDenied as exc:
            raise HTTPException(status_code=404, detail="未找到业务应用") from exc
        except Exception as exc:
            raise _http_error(exc) from exc

    return router


def _write_principal(request: Request) -> Any:
    principal = current_principal(request)
    require_csrf(request, principal)
    return principal


def _require_enabled(request: Request) -> None:
    if not (
        container(request).settings.feature_configuration.business_application_control_plane_enabled
    ):
        raise HTTPException(
            status_code=404,
            detail={
                "code": "business_application_control_plane_disabled",
                "message": "业务应用控制面已停用",
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
        }.get(exc.error_code, 400)
        detail: dict[str, Any] = {
            "code": exc.error_code or "invalid_request",
            "message": exc.safe_message,
            "field_errors": exc.field_errors,
        }
        if exc.error_code == "revision_conflict":
            detail["current_revision"] = exc.diagnostics.get("current_revision")
        if exc.error_code == "route_conflict":
            detail["conflict_application_id"] = exc.diagnostics.get("conflict_application_id")
        return HTTPException(status_code=status, detail=detail)
    if isinstance(exc, ValueError):
        return HTTPException(
            status_code=422,
            detail={"code": "validation_failed", "message": str(exc)},
        )
    return HTTPException(status_code=500, detail="服务器内部错误")


def _aggregate_runtime(values: list[dict[str, Any]], request: Request) -> dict[str, Any]:
    if not values:
        return cast(
            dict[str, Any],
            container(request).business_application_service.runtime_evaluator.empty().to_dict(),
        )
    rank = {
        "wired": 4,
        "partially_wired": 3,
        "blocked": 2,
        "not_wired": 1,
    }
    selected = max(
        values,
        key=lambda value: rank.get(str(value.get("runtime_status") or ""), 0),
    )
    return {
        key: selected[key]
        for key in (
            "runtime_wired",
            "runtime_status",
            "runtime_environment",
            "deployment_environment",
            "reason_code",
            "message",
            "runtime_components",
            "affected_routes",
            "legacy_fallback_enabled",
        )
        if key in selected
    }
