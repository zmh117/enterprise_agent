from __future__ import annotations

from typing import Any, Literal, cast

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.modules.identity.api.dependencies import (
    container,
    current_principal,
    handle_exception,
    require_action,
)


DEFAULT_AGENT_CODE = "default-diagnostic-agent"


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelConfigRequest(StrictRequest):
    schema_version: Literal[1] = 1
    protocol: Literal["anthropic_compatible"] = "anthropic_compatible"
    base_url: str = Field(min_length=1, max_length=500)
    model: str = Field(min_length=1, max_length=200)
    default_opus_model: str = Field(min_length=1, max_length=200)
    default_sonnet_model: str = Field(min_length=1, max_length=200)
    default_haiku_model: str = Field(min_length=1, max_length=200)
    subagent_model: str = Field(min_length=1, max_length=200)
    effort_level: Literal["low", "medium", "high", "max"] = "max"


class SaveRevisionRequest(StrictRequest):
    expected_revision: int = Field(ge=0)
    config: ModelConfigRequest


class RotateCredentialRequest(StrictRequest):
    expected_revision: int = Field(ge=1)
    api_key: str = Field(min_length=1, max_length=8192)


class StatusRequest(StrictRequest):
    expected_revision: int = Field(ge=1)
    enabled: bool


class TestRevisionRequest(StrictRequest):
    expected_revision: int = Field(ge=1)
    timeout_seconds: int = Field(default=15, ge=3, le=20)


def _allowed(request: Request, resource_type: str, action: str) -> bool:
    principal = current_principal(request)
    return cast(
        bool,
        container(request)
        .authorization_evaluator.decide(
            user_id=principal.user_id,
            resource_type=resource_type,
            resource_code="*" if resource_type == "secret" else DEFAULT_AGENT_CODE,
            action=action,
        )
        .allowed,
    )


def _read(request: Request, *, hide: bool = False) -> str:
    principal = current_principal(request)
    if not (_allowed(request, "agent", "read") or _allowed(request, "agent", "edit")):
        if hide:
            raise HTTPException(status_code=404, detail="未找到模型连接")
        raise HTTPException(status_code=403, detail="你无权执行此操作")
    return principal.user_id


def _edit(request: Request) -> str:
    principal = require_action(
        request,
        resource_type="agent",
        resource_code=DEFAULT_AGENT_CODE,
        action="edit",
        csrf=True,
    )
    return principal.user_id


def _credential(request: Request) -> str:
    actor_id = _edit(request)
    require_action(
        request,
        resource_type="secret",
        resource_code="*",
        action="manage",
    )
    return actor_id


def _safe_detail(
    value: dict[str, Any],
    *,
    can_edit: bool,
    can_manage_credential: bool,
) -> dict[str, Any]:
    result = dict(value)
    for key in ("current_revision", "revisions"):
        revisions = result.get(key)
        items = revisions if isinstance(revisions, list) else [revisions]
        safe_items: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            item = dict(item)
            config = item.get("config")
            if isinstance(config, dict):
                public_config = dict(config)
                public_config.pop("base_url", None)
                item["config"] = public_config
            credential = item.get("credential")
            if isinstance(credential, dict) and not can_manage_credential:
                item["credential"] = {
                    "configured": bool(credential.get("configured")),
                    "rotation_required": bool(credential.get("rotation_required")),
                }
            safe_items.append(item)
        result[key] = (
            safe_items if isinstance(revisions, list) else (safe_items[0] if safe_items else None)
        )
    result["permissions"] = {
        "can_edit": can_edit,
        "can_manage_credential": can_manage_credential,
        "can_test": can_manage_credential,
    }
    return result


def build_model_connection_router() -> APIRouter:
    router = APIRouter(
        prefix="/api/admin/model-connections",
        tags=["model-connections"],
    )

    @router.get("")
    def list_connections(request: Request) -> dict[str, Any]:
        _read(request)
        return {
            "items": container(request).model_connection_service.list_connections(),
            "permissions": {
                "can_edit": _allowed(request, "agent", "edit"),
                "can_manage_credential": _allowed(request, "secret", "manage"),
            },
        }

    @router.get("/{code}")
    def get_connection(request: Request, code: str) -> dict[str, Any]:
        _read(request, hide=True)
        try:
            value = container(request).model_connection_service.get(code)
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {
            "connection": _safe_detail(
                value,
                can_edit=_allowed(request, "agent", "edit"),
                can_manage_credential=_allowed(request, "secret", "manage"),
            )
        }

    @router.put("/{code}/revision")
    def save_revision(
        request: Request,
        code: str,
        payload: SaveRevisionRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict[str, Any]:
        actor_id = _edit(request)
        try:
            revision = container(request).model_connection_service.save_revision(
                actor_id=actor_id,
                code=code,
                expected_revision=payload.expected_revision,
                config=payload.config.model_dump(),
                idempotency_key=idempotency_key,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {
            "revision": _safe_detail(
                {"revisions": [revision]},
                can_edit=True,
                can_manage_credential=_allowed(request, "secret", "manage"),
            )["revisions"][0]
        }

    @router.post("/{code}/credential")
    def rotate_credential(
        request: Request,
        code: str,
        payload: RotateCredentialRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict[str, Any]:
        actor_id = _credential(request)
        try:
            revision = container(request).model_connection_service.rotate_credential(
                actor_id=actor_id,
                code=code,
                expected_revision=payload.expected_revision,
                api_key=payload.api_key,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {
            "revision": _safe_detail(
                {"revisions": [revision]},
                can_edit=True,
                can_manage_credential=True,
            )["revisions"][0]
        }

    @router.post("/{code}/status")
    def set_status(
        request: Request,
        code: str,
        payload: StatusRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict[str, Any]:
        actor_id = _edit(request)
        try:
            connection = container(request).model_connection_service.set_enabled(
                actor_id=actor_id,
                code=code,
                expected_revision=payload.expected_revision,
                enabled=payload.enabled,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"connection": connection}

    @router.post("/{code}/revisions/{revision_id}/test")
    def test_revision(
        request: Request,
        code: str,
        revision_id: str,
        payload: TestRevisionRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict[str, Any]:
        actor_id = _credential(request)
        try:
            connection = container(request).model_connection_service.get(code)
            revision_ids = {str(item["id"]) for item in connection["revisions"]}
            if revision_id not in revision_ids:
                raise HTTPException(status_code=404, detail="未找到模型连接版本")
            result = container(request).model_connection_service.test_saved_revision(
                actor_id=actor_id,
                revision_id=revision_id,
                expected_revision=payload.expected_revision,
                timeout_seconds=payload.timeout_seconds,
                idempotency_key=idempotency_key,
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise handle_exception(exc) from exc
        return {"result": result}

    return router
