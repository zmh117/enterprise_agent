from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.modules.identity.api.dependencies import (
    container,
    handle_exception,
    require_action,
)


DEFAULT_AGENT_CODE = "default-diagnostic-agent"
MODEL_PROBE_REQUESTS_PER_MINUTE = 10
_MODEL_PROBE_RATE_WINDOWS: dict[str, deque[float]] = {}
_MODEL_PROBE_RATE_LOCK = threading.Lock()

CredentialSource = Literal["submitted", "existing"]


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


class CredentialProbeRequest(StrictRequest):
    credential_source: CredentialSource
    api_key: str = Field(default="", max_length=4000)
    timeout_seconds: int = Field(default=15, ge=3, le=30)


class DiscoverModelsRequest(CredentialProbeRequest):
    base_url: str = Field(min_length=1, max_length=500)


class TestDraftRequest(CredentialProbeRequest):
    runtime_kind: Literal["python-v1", "typescript-v1"] = "typescript-v1"
    config: ModelConnectionConfigRequest


class ConfigureModelConnectionRequest(TestDraftRequest):
    expected_revision: int = Field(ge=0)


class StrictResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelOptionResponse(StrictResponse):
    id: str
    display_name: str


class ModelDiscoveryResultResponse(StrictResponse):
    provider_host: str
    normalized_base_url: str
    models: list[ModelOptionResponse]
    duration_ms: int
    credential_source: CredentialSource


class ModelDiscoveryResponse(StrictResponse):
    result: ModelDiscoveryResultResponse


class ModelDraftTestResultResponse(StrictResponse):
    success: bool
    provider_host: str
    model: str
    duration_ms: int
    runtime: Literal["claude_agent_sdk"]
    detail: str


class ModelDraftTestResponse(StrictResponse):
    result: ModelDraftTestResultResponse


class ModelSavedTestRequest(StrictRequest):
    runtime_kind: Literal["python-v1", "typescript-v1"] = "typescript-v1"
    timeout_seconds: int = Field(default=15, ge=3, le=20)


class ModelSavedTestResultResponse(StrictResponse):
    success: bool
    connection_revision_id: str
    provider_host: str
    model: str
    duration_ms: int
    runtime: Literal["python-v1", "typescript-v1"]
    runtime_version: str
    sdk_version: str


class ModelSavedTestResponse(StrictResponse):
    result: ModelSavedTestResultResponse


class PublicCredentialResponse(StrictResponse):
    configured: bool
    masked: str
    version: int
    updated_at: str
    rotation_required: bool


class PublicModelConnectionConfigResponse(ModelConnectionConfigRequest):
    schema_version: Literal[1]


class PublicModelConnectionRevisionResponse(StrictResponse):
    id: str
    connection_id: str
    connection_code: str
    revision: int
    status: str
    config: PublicModelConnectionConfigResponse
    config_hash: str
    provider_host: str
    credential: PublicCredentialResponse
    created_by: str
    created_at: str


class ConfigureModelConnectionResponse(StrictResponse):
    revision: PublicModelConnectionRevisionResponse


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

    @router.post("/{code}/discover", response_model=ModelDiscoveryResponse)
    def discover_models(
        request: Request,
        code: str,
        payload: DiscoverModelsRequest,
    ) -> dict[str, Any]:
        actor_id = _require_model_connection_admin(request)
        _enforce_model_probe_rate_limit(
            request,
            actor_id=actor_id,
            code=code,
            action="discover",
        )
        try:
            result = container(request).model_connection_service.discover_models(
                actor_id=actor_id,
                code=code,
                base_url=payload.base_url,
                credential_source=payload.credential_source,
                api_key=payload.api_key,
                timeout_seconds=payload.timeout_seconds,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"result": result}

    @router.post("/{code}/test-draft", response_model=ModelDraftTestResponse)
    def test_draft(
        request: Request,
        code: str,
        payload: TestDraftRequest,
    ) -> dict[str, Any]:
        actor_id = _require_model_connection_admin(request)
        _enforce_model_probe_rate_limit(
            request,
            actor_id=actor_id,
            code=code,
            action="test-draft",
        )
        try:
            result = container(request).model_connection_service.test_draft(
                actor_id=actor_id,
                code=code,
                credential_source=payload.credential_source,
                api_key=payload.api_key,
                config=payload.config.model_dump(),
                timeout_seconds=payload.timeout_seconds,
                runtime_kind=payload.runtime_kind,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"result": result}

    @router.put("/{code}/configure", response_model=ConfigureModelConnectionResponse)
    def configure_connection(
        request: Request,
        code: str,
        payload: ConfigureModelConnectionRequest,
    ) -> dict[str, Any]:
        actor_id = _require_model_connection_admin(request)
        _enforce_model_probe_rate_limit(
            request,
            actor_id=actor_id,
            code=code,
            action="configure",
        )
        try:
            revision = container(request).model_connection_service.configure(
                actor_id=actor_id,
                code=code,
                expected_revision=payload.expected_revision,
                credential_source=payload.credential_source,
                api_key=payload.api_key,
                config=payload.config.model_dump(),
                timeout_seconds=payload.timeout_seconds,
                runtime_kind=payload.runtime_kind,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"revision": revision}

    @router.post(
        "/{code}/revisions/{revision_id}/test",
        response_model=ModelSavedTestResponse,
    )
    def test_saved_revision(
        request: Request,
        code: str,
        revision_id: str,
        payload: ModelSavedTestRequest,
    ) -> dict[str, Any]:
        actor_id = _require_model_connection_admin(request)
        _enforce_model_probe_rate_limit(
            request,
            actor_id=actor_id,
            code=code,
            action="test-saved",
        )
        try:
            connection = container(request).model_connection_service.get(code)
            revision_ids = {str(item["id"]) for item in connection["revisions"]}
            if revision_id not in revision_ids:
                raise HTTPException(status_code=404, detail="未找到模型连接版本")
            result = container(request).model_connection_service.test_saved_revision(
                actor_id=actor_id,
                revision_id=revision_id,
                runtime_kind=payload.runtime_kind,
                timeout_seconds=payload.timeout_seconds,
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"result": result}

    return router


def _require_model_connection_admin(request: Request) -> str:
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
    return principal.user_id


def _enforce_model_probe_rate_limit(
    request: Request,
    *,
    actor_id: str,
    code: str,
    action: str,
) -> None:
    key = f"{actor_id}:{code}"
    now = time.monotonic()
    limited = False
    with _MODEL_PROBE_RATE_LOCK:
        window = _MODEL_PROBE_RATE_WINDOWS.setdefault(key, deque())
        while window and window[0] <= now - 60:
            window.popleft()
        if len(window) >= MODEL_PROBE_REQUESTS_PER_MINUTE:
            limited = True
        else:
            window.append(now)
    if not limited:
        return
    container(request).model_connection_service.audit_service.record(
        "model.connection.rate_limited",
        status="FAILED",
        summary="Model connection probe rate limited",
        actor_id=actor_id,
        payload={
            "actor_id": actor_id,
            "connection_code": code,
            "action": action,
            "result": "rate_limited",
            "error_code": "model_connection_rate_limited",
        },
    )
    raise HTTPException(
        status_code=429,
        detail={
            "code": "model_connection_rate_limited",
            "message": "模型连接检测过于频繁，请稍后重试",
        },
    )
