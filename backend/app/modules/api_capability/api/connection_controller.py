from __future__ import annotations

from typing import Any, Literal, cast

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.modules.identity.api.dependencies import (
    container,
    handle_exception,
    require_action,
)


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OriginRequest(StrictRequest):
    scheme: Literal["https", "http"]
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(ge=1, le=65535)
    allow_insecure_local_http: bool = False
    connect_timeout_ms: int = Field(default=3000, ge=100, le=30000)
    read_timeout_ms: int = Field(default=10000, ge=100, le=60000)
    max_response_bytes: int = Field(
        default=1048576,
        ge=1024,
        le=5242880,
    )


class ConnectionDraftRequest(StrictRequest):
    expected_revision: int = Field(ge=1)
    origin: OriginRequest
    authentication: dict[str, Any]


class CreateConnectionRequest(StrictRequest):
    code: str = Field(min_length=2, max_length=80)
    name: str = Field(min_length=2, max_length=120)
    origin: OriginRequest
    authentication: dict[str, Any]


class VerifyConnectionRequest(StrictRequest):
    draft_revision: int = Field(ge=1)
    draft_hash: str = Field(min_length=64, max_length=64)
    email: str = Field(min_length=3, max_length=320)
    password: SecretStr


class PublishConnectionRequest(StrictRequest):
    draft_revision: int = Field(ge=1)
    draft_hash: str = Field(min_length=64, max_length=64)


class ConnectionRevisionStatusRequest(StrictRequest):
    status: Literal["PUBLISHED", "DISABLED", "ARCHIVED"]


def build_api_connection_router() -> APIRouter:
    router = APIRouter(
        prefix="/api/admin/api-connections",
        tags=["api-capabilities"],
    )

    @router.get("")
    def list_connections(request: Request) -> dict[str, Any]:
        principal = _require(request, "read")
        try:
            values = container(request).api_connection_service.list(actor_id=principal.user_id)
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"items": values}

    @router.post("")
    def create_connection(
        request: Request,
        payload: CreateConnectionRequest,
    ) -> dict[str, Any]:
        principal = _require(request, "manage", csrf=True)
        try:
            value = container(request).api_connection_service.create(
                actor_id=principal.user_id,
                code=payload.code,
                name=payload.name,
                origin=payload.origin.model_dump(),
                authentication=payload.authentication,
                correlation_id=_correlation_id(request),
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"connection": value}

    @router.get("/{connection_id}")
    def get_connection(
        request: Request,
        connection_id: str,
    ) -> dict[str, Any]:
        principal = _require(request, "read")
        try:
            value = container(request).api_connection_service.get(
                connection_id,
                actor_id=principal.user_id,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"connection": value}

    @router.put("/{connection_id}/draft")
    def save_connection_draft(
        request: Request,
        connection_id: str,
        payload: ConnectionDraftRequest,
    ) -> dict[str, Any]:
        principal = _require(request, "manage", csrf=True)
        try:
            value = container(request).api_connection_service.save_draft(
                connection_id,
                actor_id=principal.user_id,
                expected_revision=payload.expected_revision,
                origin=payload.origin.model_dump(),
                authentication=payload.authentication,
                correlation_id=_correlation_id(request),
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"connection": value}

    @router.post("/{connection_id}/verify")
    def verify_connection(
        request: Request,
        connection_id: str,
        payload: VerifyConnectionRequest,
    ) -> dict[str, Any]:
        principal = _require(request, "verify", csrf=True)
        try:
            return cast(
                dict[str, Any],
                container(request).api_connection_service.verify_bootstrap(
                    connection_id,
                    actor_id=principal.user_id,
                    draft_revision=payload.draft_revision,
                    draft_hash=payload.draft_hash,
                    email=payload.email,
                    password=payload.password.get_secret_value(),
                    correlation_id=_correlation_id(request),
                ),
            )
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.post("/{connection_id}/publish")
    def publish_connection(
        request: Request,
        connection_id: str,
        payload: PublishConnectionRequest,
    ) -> dict[str, Any]:
        principal = _require(request, "publish", csrf=True)
        try:
            value = container(request).api_connection_service.publish(
                connection_id,
                actor_id=principal.user_id,
                draft_revision=payload.draft_revision,
                draft_hash=payload.draft_hash,
                correlation_id=_correlation_id(request),
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"revision": value}

    @router.put("/revisions/{revision_id}/status")
    def set_revision_status(
        request: Request,
        revision_id: str,
        payload: ConnectionRevisionStatusRequest,
    ) -> dict[str, Any]:
        principal = _require(request, "manage", csrf=True)
        try:
            value = container(request).api_connection_service.set_revision_status(
                revision_id,
                actor_id=principal.user_id,
                status=payload.status,
                correlation_id=_correlation_id(request),
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"revision": value}

    return router


def _require(request: Request, action: str, *, csrf: bool = False) -> Any:
    return require_action(
        request,
        resource_type="api_connection",
        resource_code="*",
        action=action,
        csrf=csrf,
    )


def _correlation_id(request: Request) -> str:
    return str(getattr(request.state, "correlation_id", "") or "")
