from __future__ import annotations

from typing import Any, Literal, cast

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.modules.identity.api.dependencies import (
    container,
    handle_exception,
    require_action,
)


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CapabilityDraftFields(StrictRequest):
    connection_revision_id: str = Field(min_length=1, max_length=200)
    authentication_profile_revision_id: str = Field(
        min_length=1,
        max_length=200,
    )
    capability: dict[str, Any]
    handler: dict[str, Any]
    mapping_ast: dict[str, Any]


class CreateCapabilityRequest(CapabilityDraftFields):
    identifier: str = Field(min_length=18, max_length=128)


class SaveCapabilityDraftRequest(CapabilityDraftFields):
    expected_revision: int = Field(ge=1)


class CapabilityTestRequest(StrictRequest):
    draft_revision: int = Field(ge=1)
    draft_hash: str = Field(min_length=64, max_length=64)
    agent_input: dict[str, Any]


class PublishCapabilityRequest(StrictRequest):
    draft_revision: int = Field(ge=1)
    draft_hash: str = Field(min_length=64, max_length=64)
    idempotency_key: str = Field(min_length=1, max_length=200)
    release_note: str = Field(default="", max_length=2000)


class CapabilityReleaseStatusRequest(StrictRequest):
    status: Literal["ACTIVE", "DEPRECATED", "DISABLED", "ARCHIVED"]
    reason: str = Field(default="", max_length=2000)
    replacement_release_id: str = Field(default="", max_length=200)


class CopyReleaseRequest(StrictRequest):
    expected_revision: int = Field(ge=1)


class InitializeOnesSearchRequest(StrictRequest):
    connection_revision_id: str = Field(min_length=1, max_length=200)
    authentication_profile_revision_id: str = Field(
        min_length=1,
        max_length=200,
    )


def build_api_capability_router() -> APIRouter:
    router = APIRouter(
        prefix="/api/admin/api-capabilities",
        tags=["api-capabilities"],
    )

    @router.get("")
    def list_capabilities(request: Request) -> dict[str, Any]:
        principal = _require(request, "read")
        try:
            items = container(request).api_capability_service.list(actor_id=principal.user_id)
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"items": items}

    @router.get("/catalog")
    def release_catalog(
        request: Request,
        selectable_only: bool = Query(default=False),
    ) -> dict[str, Any]:
        principal = _require(request, "read")
        try:
            items = container(request).api_capability_service.catalog(
                actor_id=principal.user_id,
                selectable_only=selectable_only,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"items": items}

    @router.post("/templates/ones-work-item-search")
    def initialize_ones_work_item_search(
        request: Request,
        payload: InitializeOnesSearchRequest,
    ) -> dict[str, Any]:
        principal = _require(request, "manage", csrf=True)
        try:
            value = container(request).api_capability_service.initialize_ones_work_item_search(
                actor_id=principal.user_id,
                correlation_id=_correlation_id(request),
                **payload.model_dump(),
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"capability": value}

    @router.post("")
    def create_capability(
        request: Request,
        payload: CreateCapabilityRequest,
    ) -> dict[str, Any]:
        principal = _require(request, "manage", csrf=True)
        try:
            value = container(request).api_capability_service.create(
                actor_id=principal.user_id,
                correlation_id=_correlation_id(request),
                **payload.model_dump(),
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"capability": value}

    @router.get("/{capability_id}")
    def get_capability(
        request: Request,
        capability_id: str,
    ) -> dict[str, Any]:
        principal = _require(request, "read")
        try:
            value = container(request).api_capability_service.get(
                capability_id,
                actor_id=principal.user_id,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"capability": value}

    @router.put("/{capability_id}/draft")
    def save_capability_draft(
        request: Request,
        capability_id: str,
        payload: SaveCapabilityDraftRequest,
    ) -> dict[str, Any]:
        principal = _require(request, "manage", csrf=True)
        try:
            value = container(request).api_capability_service.save_draft(
                capability_id,
                actor_id=principal.user_id,
                correlation_id=_correlation_id(request),
                **payload.model_dump(),
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"capability": value}

    @router.post("/{capability_id}/test")
    def test_capability(
        request: Request,
        capability_id: str,
        payload: CapabilityTestRequest,
    ) -> dict[str, Any]:
        principal = _require(request, "test", csrf=True)
        try:
            preview = container(request).api_capability_service.test(
                capability_id,
                actor_id=principal.user_id,
                correlation_id=_correlation_id(request),
                **payload.model_dump(),
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"preview": preview}

    @router.post("/{capability_id}/verify")
    def verify_capability(
        request: Request,
        capability_id: str,
        payload: CapabilityTestRequest,
    ) -> dict[str, Any]:
        principal = _require(request, "verify", csrf=True)
        try:
            return cast(
                dict[str, Any],
                container(request).api_capability_service.verify(
                    capability_id,
                    actor_id=principal.user_id,
                    correlation_id=_correlation_id(request),
                    **payload.model_dump(),
                ),
            )
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.post("/{capability_id}/publish")
    def publish_capability(
        request: Request,
        capability_id: str,
        payload: PublishCapabilityRequest,
    ) -> dict[str, Any]:
        principal = _require(request, "publish", csrf=True)
        try:
            release = container(request).api_capability_service.publish(
                capability_id,
                actor_id=principal.user_id,
                correlation_id=_correlation_id(request),
                **payload.model_dump(),
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"release": release}

    @router.put("/releases/{release_id}/status")
    def set_release_status(
        request: Request,
        release_id: str,
        payload: CapabilityReleaseStatusRequest,
    ) -> dict[str, Any]:
        principal = _require(request, "manage", csrf=True)
        try:
            release = container(request).api_capability_service.set_release_status(
                release_id,
                actor_id=principal.user_id,
                correlation_id=_correlation_id(request),
                **payload.model_dump(),
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"release": release}

    @router.post("/releases/{release_id}/copy-to-draft")
    def copy_release_to_draft(
        request: Request,
        release_id: str,
        payload: CopyReleaseRequest,
    ) -> dict[str, Any]:
        principal = _require(request, "manage", csrf=True)
        try:
            value = container(request).api_capability_service.copy_release_to_draft(
                release_id,
                actor_id=principal.user_id,
                expected_revision=payload.expected_revision,
                correlation_id=_correlation_id(request),
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"capability": value}

    return router


def _require(request: Request, action: str, *, csrf: bool = False) -> Any:
    return require_action(
        request,
        resource_type="api_capability",
        resource_code="*",
        action=action,
        csrf=csrf,
    )


def _correlation_id(request: Request) -> str:
    return str(getattr(request.state, "correlation_id", "") or "")
