from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from app.modules.identity.api.dependencies import (
    container,
    handle_exception,
    require_action,
)
from app.shared.exceptions import NonRetryableExecutionError


DEFAULT_AGENT_CODE = "default-diagnostic-agent"


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelConnectionConfigRequest(StrictRequest):
    protocol: Literal["anthropic_compatible"] = "anthropic_compatible"
    base_url: str = Field(min_length=1, max_length=500)
    model: str = Field(min_length=1, max_length=200)
    default_opus_model: str = Field(default="", max_length=200)
    default_sonnet_model: str = Field(default="", max_length=200)
    default_haiku_model: str = Field(default="", max_length=200)
    subagent_model: str = Field(default="", max_length=200)
    effort_level: Literal["low", "medium", "high", "max"] = "max"


class SaveModelConnectionRequest(StrictRequest):
    expected_revision: int = Field(ge=0)
    config: ModelConnectionConfigRequest


class RotateModelCredentialRequest(StrictRequest):
    expected_revision: int = Field(ge=0)
    api_key: str = Field(min_length=1, max_length=4000)


class TestModelConnectionRequest(StrictRequest):
    revision_id: str = Field(min_length=1, max_length=200)
    timeout_seconds: int = Field(default=15, ge=3, le=30)


def build_model_connection_router() -> APIRouter:
    router = APIRouter(
        prefix="/api/admin/model-connections",
        tags=["model-connections"],
    )

    @router.get("")
    def list_connections(request: Request) -> dict[str, Any]:
        require_action(
            request,
            resource_type="agent",
            resource_code=DEFAULT_AGENT_CODE,
            action="edit",
        )
        return {"connections": container(request).model_connection_service.list_connections()}

    @router.get("/{code}")
    def get_connection(request: Request, code: str) -> dict[str, Any]:
        require_action(
            request,
            resource_type="agent",
            resource_code=DEFAULT_AGENT_CODE,
            action="edit",
        )
        try:
            value = container(request).model_connection_service.get(code)
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"connection": value}

    @router.put("/{code}/revision")
    def save_connection(
        request: Request,
        code: str,
        payload: SaveModelConnectionRequest,
    ) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="agent",
            resource_code=DEFAULT_AGENT_CODE,
            action="edit",
            csrf=True,
        )
        try:
            revision = container(request).model_connection_service.save_revision(
                actor_id=principal.user_id,
                code=code,
                expected_revision=payload.expected_revision,
                config=payload.config.model_dump(),
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"revision": revision}

    @router.put("/{code}/credential")
    def rotate_credential(
        request: Request,
        code: str,
        payload: RotateModelCredentialRequest,
    ) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="agent",
            resource_code=DEFAULT_AGENT_CODE,
            action="edit",
            csrf=True,
        )
        require_action(
            request,
            resource_type="secret",
            resource_code="*",
            action="manage",
            csrf=True,
        )
        try:
            revision = container(request).model_connection_service.rotate_credential(
                actor_id=principal.user_id,
                code=code,
                expected_revision=payload.expected_revision,
                api_key=payload.api_key,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"revision": revision}

    @router.post("/{code}/test")
    def test_connection(
        request: Request,
        code: str,
        payload: TestModelConnectionRequest,
    ) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="agent",
            resource_code=DEFAULT_AGENT_CODE,
            action="edit",
            csrf=True,
        )
        require_action(
            request,
            resource_type="secret",
            resource_code="*",
            action="manage",
            csrf=True,
        )
        try:
            connection = container(request).model_connection_service.get(code)
            revisions = {str(item["id"]) for item in connection.get("revisions") or []}
            if payload.revision_id not in revisions:
                raise NonRetryableExecutionError(
                    "Model connection revision belongs to another connection",
                    safe_message="Model connection revision is invalid",
                    error_code="validation_failed",
                )
            result = container(request).model_connection_service.test_saved_revision(
                actor_id=principal.user_id,
                revision_id=payload.revision_id,
                timeout_seconds=payload.timeout_seconds,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"result": result}

    return router
