from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Literal, cast

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.modules.identity.api.dependencies import (
    container,
    handle_exception,
    require_action,
)
from app.modules.managed_channel.domain import (
    ChannelIngressSubmission,
    DingTalkApplicationInput,
    RuntimeConnectorState,
)

_RUNTIME_RATE_LOCK = threading.Lock()
_RUNTIME_RATE_WINDOWS: dict[str, deque[float]] = {}


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DingTalkApplicationRequest(StrictRequest):
    expected_revision: int = Field(default=0, ge=0)
    name: str = Field(min_length=2, max_length=120)
    client_id: str = Field(min_length=1, max_length=128)
    client_secret: str = Field(default="", max_length=512)
    dingtalk_enterprise_id: str = Field(min_length=1, max_length=200)
    allow_private_chat: bool = True
    allow_group_chat: bool = True
    require_group_at: bool = True
    work_notification_agent_id: int | None = Field(default=None, ge=1)
    enterprise_robot_code: str = Field(default="", max_length=128)
    external_action_confirmation_card_template_id: str | None = Field(default=None, max_length=256)
    enabled: bool = False
    rotate_secret: bool = False


class RevisionRequest(StrictRequest):
    expected_revision: int = Field(ge=1)


class DingTalkEnterpriseCreateRequest(StrictRequest):
    name: str = Field(min_length=1, max_length=120)


class DingTalkEnterpriseRenameRequest(StrictRequest):
    name: str = Field(min_length=1, max_length=120)
    expected_revision: int = Field(ge=1)


class DingTalkEnterpriseImpactResponse(StrictRequest):
    connector_id: str
    connector_name: str
    connector_enabled: bool
    application_id: str
    application_name: str
    application_revision: int | None = None


class DingTalkEnterpriseResponse(StrictRequest):
    id: str
    name: str
    corp_id: str
    status: Literal[
        "PENDING_VERIFICATION",
        "ACTIVE",
        "DISABLED",
        "ARCHIVED",
    ]
    verified_at: str | None = None
    revision: int = Field(ge=1)
    connector_count: int = Field(ge=0)
    enabled_connector_count: int = Field(ge=0)
    created_at: str
    updated_at: str
    impacts: list[DingTalkEnterpriseImpactResponse] = Field(default_factory=list)


class DingTalkEnterpriseListResponse(StrictRequest):
    items: list[DingTalkEnterpriseResponse]


class DingTalkEnterpriseItemResponse(StrictRequest):
    enterprise: DingTalkEnterpriseResponse


class WebhookApplicationRequest(StrictRequest):
    code: str = Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")
    name: str = Field(min_length=1, max_length=200)
    trigger_type: Literal["grafana", "generic"]
    connector_id: str = Field(min_length=1, max_length=200)


class RuntimeLeaseRequest(StrictRequest):
    runtime_id: str = Field(min_length=1, max_length=128)
    lease_token: str = Field(default="", max_length=512)


class RuntimeStateItem(StrictRequest):
    connector_id: str = Field(min_length=1, max_length=160)
    revision: int = Field(ge=1)
    status: Literal[
        "STOPPED",
        "STARTING",
        "CONNECTED",
        "REGISTERED",
        "RECONNECTING",
        "AUTH_FAILED",
        "ERROR",
    ]
    connected: bool
    registered: bool
    error_code: str = Field(default="", max_length=120)
    error_summary: str = Field(default="", max_length=500)


class RuntimeStateRequest(RuntimeLeaseRequest):
    states: list[RuntimeStateItem] = Field(default_factory=list, max_length=200)


class RuntimeInboxRequest(RuntimeLeaseRequest):
    connector_id: str = Field(min_length=1, max_length=160)
    external_event_id: str = Field(min_length=1, max_length=256)
    correlation_id: str = Field(min_length=1, max_length=128)
    normalized_event: dict[str, Any]
    safe_summary: dict[str, Any] = Field(default_factory=dict)
    payload_hash: str = Field(default="", max_length=128)
    request_bytes: int = Field(ge=0)


class RuntimeCardActionRequest(RuntimeLeaseRequest):
    connector_id: str = Field(min_length=1, max_length=160)
    corp_id: str = Field(min_length=1, max_length=128)
    out_track_id: str = Field(min_length=1, max_length=128)
    user_id: str = Field(min_length=1, max_length=256)
    action: Literal["agree", "reject", "revise"]
    revision: int = Field(ge=1, le=1000000)
    intent_token: str = Field(min_length=1, max_length=256)


def build_managed_channel_router() -> APIRouter:
    router = APIRouter(prefix="/api/admin/managed-channels", tags=["managed-channels"])

    @router.get("")
    def list_channels(request: Request) -> dict[str, Any]:
        require_action(request, resource_type="channel_connector", resource_code="*", action="read")
        try:
            return {"items": container(request).managed_channel_service.list_channels()}
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.get("/eligible")
    def eligible(request: Request, trigger_type: str) -> dict[str, Any]:
        require_action(request, resource_type="channel_connector", resource_code="*", action="read")
        try:
            return {"items": container(request).managed_channel_service.eligible(trigger_type)}
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.get("/webhook-connector-options")
    def webhook_connector_options(request: Request) -> dict[str, Any]:
        require_action(request, resource_type="channel_connector", resource_code="*", action="read")
        try:
            return {"items": container(request).managed_channel_service.webhook_connector_options()}
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.get(
        "/dingtalk-enterprises",
        response_model=DingTalkEnterpriseListResponse,
    )
    def list_dingtalk_enterprises(request: Request) -> dict[str, Any]:
        require_action(
            request,
            resource_type="channel_connector",
            resource_code="*",
            action="read",
        )
        try:
            return {"items": container(request).managed_channel_service.list_dingtalk_enterprises()}
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.post(
        "/dingtalk-enterprises",
        response_model=DingTalkEnterpriseItemResponse,
    )
    def create_dingtalk_enterprise(
        request: Request,
        payload: DingTalkEnterpriseCreateRequest,
    ) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="channel_connector",
            resource_code="*",
            action="manage",
            csrf=True,
        )
        try:
            item = container(request).managed_channel_service.create_dingtalk_enterprise(
                name=payload.name,
                actor_id=principal.user_id,
            )
            return {"enterprise": item}
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.get(
        "/dingtalk-enterprises/{enterprise_id}",
        response_model=DingTalkEnterpriseItemResponse,
    )
    def dingtalk_enterprise_detail(
        request: Request,
        enterprise_id: str,
    ) -> dict[str, Any]:
        require_action(
            request,
            resource_type="channel_connector",
            resource_code="*",
            action="read",
        )
        try:
            return {
                "enterprise": container(request).managed_channel_service.get_dingtalk_enterprise(
                    enterprise_id
                )
            }
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.patch(
        "/dingtalk-enterprises/{enterprise_id}",
        response_model=DingTalkEnterpriseItemResponse,
    )
    def rename_dingtalk_enterprise(
        request: Request,
        enterprise_id: str,
        payload: DingTalkEnterpriseRenameRequest,
    ) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="channel_connector",
            resource_code="*",
            action="manage",
            csrf=True,
        )
        try:
            item = container(request).managed_channel_service.rename_dingtalk_enterprise(
                enterprise_id,
                name=payload.name,
                expected_revision=payload.expected_revision,
                actor_id=principal.user_id,
            )
            return {"enterprise": item}
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.post(
        "/dingtalk-enterprises/{enterprise_id}/disable",
        response_model=DingTalkEnterpriseItemResponse,
    )
    @router.post(
        "/dingtalk-enterprises/{enterprise_id}/archive",
        response_model=DingTalkEnterpriseItemResponse,
    )
    @router.post(
        "/dingtalk-enterprises/{enterprise_id}/restore",
        response_model=DingTalkEnterpriseItemResponse,
    )
    def govern_dingtalk_enterprise(
        request: Request,
        enterprise_id: str,
        payload: RevisionRequest,
    ) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="channel_connector",
            resource_code="*",
            action="manage",
            csrf=True,
        )
        action = request.url.path.rsplit("/", 1)[-1]
        service = container(request).managed_channel_service
        try:
            if action == "disable":
                item = service.disable_dingtalk_enterprise(
                    enterprise_id,
                    expected_revision=payload.expected_revision,
                    actor_id=principal.user_id,
                )
            elif action == "archive":
                item = service.archive_dingtalk_enterprise(
                    enterprise_id,
                    expected_revision=payload.expected_revision,
                    actor_id=principal.user_id,
                )
            else:
                item = service.restore_dingtalk_enterprise(
                    enterprise_id,
                    expected_revision=payload.expected_revision,
                    actor_id=principal.user_id,
                )
            return {"enterprise": item}
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.get("/{channel_id}")
    def detail(request: Request, channel_id: str) -> dict[str, Any]:
        require_action(request, resource_type="channel_connector", resource_code="*", action="read")
        try:
            return {"channel": container(request).managed_channel_service.get_channel(channel_id)}
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.post("/dingtalk-app-robots")
    def create(request: Request, payload: DingTalkApplicationRequest) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="channel_connector",
            resource_code="*",
            action="manage",
            csrf=True,
        )
        if payload.expected_revision != 0:
            raise HTTPException(status_code=409, detail="新建渠道的 expected_revision 必须为 0")
        try:
            item = container(request).managed_channel_service.create_dingtalk(
                _application_input(payload),
                actor_id=principal.user_id,
                enabled=payload.enabled,
            )
            return {"channel": item}
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.post("/webhooks")
    def create_webhook(request: Request, payload: WebhookApplicationRequest) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="channel_connector",
            resource_code="*",
            action="manage",
            csrf=True,
        )
        try:
            created = container(request).managed_channel_service.create_webhook(
                actor_id=principal.user_id,
                code=payload.code,
                name=payload.name,
                trigger_type=payload.trigger_type,
                connector_id=payload.connector_id,
            )
            return {"webhook": created}
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.put("/dingtalk-app-robots/{connector_id}")
    def update(
        request: Request, connector_id: str, payload: DingTalkApplicationRequest
    ) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="channel_connector",
            resource_code="*",
            action="manage",
            csrf=True,
        )
        try:
            item = container(request).managed_channel_service.update_dingtalk(
                connector_id,
                _application_input(payload),
                expected_revision=payload.expected_revision,
                actor_id=principal.user_id,
                rotate_secret=payload.rotate_secret,
            )
            return {"channel": item}
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.post("/{connector_id}/enable")
    @router.post("/{connector_id}/disable")
    def set_status(request: Request, connector_id: str, payload: RevisionRequest) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="channel_connector",
            resource_code="*",
            action="manage",
            csrf=True,
        )
        enabled = request.url.path.endswith("/enable")
        try:
            item = container(request).managed_channel_service.set_enabled(
                connector_id,
                enabled=enabled,
                expected_revision=payload.expected_revision,
                actor_id=principal.user_id,
            )
            return {"channel": item}
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.post("/{connector_id}/restart")
    def restart(request: Request, connector_id: str, payload: RevisionRequest) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="channel_connector",
            resource_code="*",
            action="restart",
            csrf=True,
        )
        try:
            item = container(request).managed_channel_service.restart(
                connector_id,
                expected_revision=payload.expected_revision,
                actor_id=principal.user_id,
            )
            return {"channel": item}
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.post("/{connector_id}/test")
    def test_configuration(request: Request, connector_id: str) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="channel_connector",
            resource_code="*",
            action="manage",
            csrf=True,
        )
        try:
            result = container(request).managed_channel_service.test_configuration(
                connector_id,
                actor_id=principal.user_id,
            )
            return {"result": result}
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.delete("/{connector_id}")
    def delete(request: Request, connector_id: str, expected_revision: int) -> dict[str, Any]:
        principal = require_action(
            request,
            resource_type="channel_connector",
            resource_code="*",
            action="delete",
            csrf=True,
        )
        try:
            container(request).managed_channel_service.delete(
                connector_id,
                expected_revision=expected_revision,
                actor_id=principal.user_id,
            )
            return {"status": "deleted"}
        except Exception as exc:
            raise handle_exception(exc) from exc

    return router


def build_runtime_control_router() -> APIRouter:
    router = APIRouter(
        prefix="/api/internal/dingtalk-runtime",
        tags=["dingtalk-runtime-internal"],
    )

    @router.post("/lease/acquire")
    def acquire(request: Request, payload: RuntimeLeaseRequest) -> dict[str, Any]:
        _require_runtime_auth(request)
        lease = container(request).runtime_control_service.acquire(payload.runtime_id)
        if lease is None:
            raise HTTPException(
                status_code=409,
                detail={"code": "runtime_lease_held", "message": "Runtime 租约已被占用"},
            )
        return {"lease": lease}

    @router.post("/lease/renew")
    def renew(request: Request, payload: RuntimeLeaseRequest) -> dict[str, Any]:
        _require_runtime_auth(request)
        lease = container(request).runtime_control_service.renew(
            payload.runtime_id, payload.lease_token
        )
        if lease is None:
            raise HTTPException(
                status_code=409,
                detail={"code": "runtime_lease_invalid", "message": "Runtime 租约无效"},
            )
        return {"lease": lease}

    @router.post("/lease/release")
    def release(request: Request, payload: RuntimeLeaseRequest) -> dict[str, Any]:
        _require_runtime_auth(request)
        released = container(request).runtime_control_service.release(
            payload.runtime_id, payload.lease_token
        )
        return {"released": released}

    @router.post("/desired-config")
    def desired_config(request: Request, payload: RuntimeLeaseRequest) -> dict[str, Any]:
        _require_runtime_auth(request)
        try:
            result: dict[str, Any] = container(request).runtime_control_service.desired_snapshot(
                payload.runtime_id, payload.lease_token
            )
            return result
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.post("/states")
    def states(request: Request, payload: RuntimeStateRequest) -> dict[str, Any]:
        _require_runtime_auth(request)
        try:
            container(request).runtime_control_service.report_states(
                payload.runtime_id,
                payload.lease_token,
                [
                    RuntimeConnectorState(
                        connector_id=item.connector_id,
                        revision=item.revision,
                        status=item.status,
                        connected=item.connected,
                        registered=item.registered,
                        error_code=item.error_code,
                        error_summary=item.error_summary,
                    )
                    for item in payload.states
                ],
            )
            return {"status": "accepted"}
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.post("/inbox")
    def inbox(request: Request, payload: RuntimeInboxRequest) -> dict[str, Any]:
        _require_runtime_auth(request)
        try:
            encoded = json.dumps(
                payload.normalized_event,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
            effective_request_bytes = max(payload.request_bytes, len(encoded))
            digest = payload.payload_hash or hashlib.sha256(encoded).hexdigest()
            event, created = container(request).runtime_control_service.receive(
                payload.runtime_id,
                payload.lease_token,
                ChannelIngressSubmission(
                    connector_id=payload.connector_id,
                    external_event_id=payload.external_event_id,
                    correlation_id=payload.correlation_id,
                    normalized_event=payload.normalized_event,
                    safe_summary=payload.safe_summary,
                    payload_hash=digest,
                    request_bytes=effective_request_bytes,
                ),
            )
            return {
                "event_id": event["id"],
                "status": event["status"],
                "created": created,
                "acknowledged": True,
            }
        except Exception as exc:
            raise handle_exception(exc) from exc

    @router.post("/card-actions")
    def card_actions(request: Request, payload: RuntimeCardActionRequest) -> dict[str, Any]:
        _require_runtime_auth(request)
        try:
            return cast(
                dict[str, Any],
                container(request).runtime_control_service.receive_card_action(
                    runtime_id=payload.runtime_id,
                    lease_token=payload.lease_token,
                    connector_id=payload.connector_id,
                    corp_id=payload.corp_id,
                    out_track_id=payload.out_track_id,
                    user_id=payload.user_id,
                    action=payload.action,
                    revision=payload.revision,
                    intent_token=payload.intent_token,
                ),
            )
        except Exception as exc:
            raise handle_exception(exc) from exc

    return router


def _application_input(payload: DingTalkApplicationRequest) -> DingTalkApplicationInput:
    return DingTalkApplicationInput(
        name=payload.name,
        client_id=payload.client_id,
        client_secret=payload.client_secret,
        dingtalk_enterprise_id=payload.dingtalk_enterprise_id,
        allow_private_chat=payload.allow_private_chat,
        allow_group_chat=payload.allow_group_chat,
        require_group_at=payload.require_group_at,
        work_notification_agent_id=payload.work_notification_agent_id,
        enterprise_robot_code=payload.enterprise_robot_code,
        external_action_confirmation_card_template_id=(
            payload.external_action_confirmation_card_template_id
        ),
    )


def _require_runtime_auth(request: Request) -> None:
    settings = container(request).settings.managed_channels
    expected = settings.runtime_auth_token
    if settings.runtime_auth_token_file:
        try:
            expected = Path(settings.runtime_auth_token_file).read_text().strip()
        except OSError:
            expected = ""
    header = request.headers.get("authorization", "")
    supplied = header.removeprefix("Bearer ").strip() if header.startswith("Bearer ") else ""
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        raise HTTPException(
            status_code=401,
            detail={"code": "runtime_auth_failed", "message": "Runtime 认证失败"},
        )
    _enforce_runtime_rate_limit(
        request,
        requests_per_minute=settings.internal_requests_per_minute,
    )


def _enforce_runtime_rate_limit(request: Request, *, requests_per_minute: int) -> None:
    limit = max(1, requests_per_minute)
    key = request.client.host if request.client else "runtime"
    now = time.monotonic()
    with _RUNTIME_RATE_LOCK:
        window = _RUNTIME_RATE_WINDOWS.setdefault(key, deque())
        while window and window[0] <= now - 60:
            window.popleft()
        if len(window) >= limit:
            raise HTTPException(
                status_code=429,
                detail={
                    "code": "runtime_rate_limited",
                    "message": "Runtime 请求过于频繁",
                },
            )
        window.append(now)
