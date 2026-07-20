from __future__ import annotations

import hmac
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

from app.bootstrap import Container
from app.modules.channel.domain.channel_event import (
    ChannelEvent,
    ChannelSource,
    ReplyRoute,
    RoutingContext,
    safe_payload_summary,
)
from app.shared.exceptions import PermissionDenied
from app.shared.logging import new_correlation_id


def build_channel_router() -> Any:
    router = APIRouter(prefix="/webhooks", tags=["channel"])

    @router.post("/channel/agent")
    async def generic_channel(
        request: Request,
        x_channel_token: str = Header(default=""),
    ) -> dict[str, Any]:
        container = _container(request)
        payload = await _json_payload(request)
        event = _generic_event(
            payload,
            correlation_id=request.headers.get("x-correlation-id") or new_correlation_id(),
        )
        _verify_connector_token(container, event.source.connector_id, x_channel_token)
        try:
            job = container.channel_ingress_service.accept(event)
        except PermissionDenied as exc:
            raise HTTPException(status_code=403, detail=exc.safe_message) from exc
        return {"accepted": True, "status": job.status.value, "job_id": job.id}

    @router.post("/grafana/alert")
    async def grafana_alert(
        request: Request,
        x_grafana_token: str = Header(default=""),
        x_connector_id: str = Header(default="connector-grafana-default"),
    ) -> Any:
        container = _container(request)
        try:
            from app.modules.webhook.api.public_controller import (
                acknowledgement_payload,
                bounded_raw_body,
                public_error_response,
            )
            from fastapi.responses import JSONResponse

            trigger = container.webhook_trigger_repository.get_enabled_grafana_by_connector(
                x_connector_id
            )
            if not trigger:
                from app.shared.exceptions import NotFound

                raise NotFound(
                    "Managed Grafana Trigger not found",
                    safe_message="Grafana Webhook endpoint is unavailable",
                    error_code="webhook_not_found",
                )
            raw_body = await bounded_raw_body(
                request, container.settings.webhooks.max_body_bytes
            )
            acknowledgement = container.webhook_ingress_service.receive(
                public_id=str(trigger["public_id"]),
                raw_body=raw_body,
                content_type=request.headers.get("content-type", ""),
                headers={**dict(request.headers), "authorization": f"Bearer {x_grafana_token}"},
                correlation_id=request.headers.get("x-correlation-id")
                or new_correlation_id(),
                remote_address=request.client.host if request.client else "",
            )
            if acknowledgement.accepted:
                container.webhook_outbox_publisher.publish_pending(limit=1)
                # The deprecated route preserves its historical contract of
                # returning a created job. The queued dispatcher delivery is
                # intentionally idempotent and will observe the same job later.
                from app.modules.message_bus.application.message_publisher import (
                    WebhookEventMessage,
                )

                container.webhook_dispatcher.handle(
                    WebhookEventMessage(
                        webhook_event_id=acknowledgement.event_id,
                        correlation_id=acknowledgement.correlation_id,
                    )
                )
            event = container.webhook_event_repository.get(acknowledgement.event_id)
            payload = acknowledgement_payload(acknowledgement)
            payload.update(
                {
                    "status": "ignored" if acknowledgement.ignored else "PENDING",
                    "job_id": event.get("job_id"),
                    "deprecated": True,
                    "replacement": f"/webhooks/v1/{trigger['public_id']}",
                }
            )
            return JSONResponse(
                status_code=200,
                content=payload,
                headers={"Deprecation": "true"},
            )
        except Exception as exc:
            if "public_error_response" in locals():
                return public_error_response(exc)
            raise

    return router


def _generic_event(payload: dict[str, Any], *, correlation_id: str) -> ChannelEvent:
    source_payload = _dict_value(payload.get("from"))
    delivery_payload = _dict_value(payload.get("delivery"))
    routing = RoutingContext.from_dict(_dict_value(payload.get("routing")))
    message = str(payload.get("message") or "").strip()
    if not source_payload.get("type") or not message:
        raise HTTPException(status_code=400, detail="Fields 'from.type' and 'message' are required")
    source_type = str(source_payload["type"])
    connector_id = str(source_payload.get("connector_id") or f"connector-{source_type}")
    event_id = str(source_payload.get("event_id") or new_correlation_id())
    actor_id = str(source_payload.get("actor_id") or "unknown")
    return ChannelEvent(
        source=ChannelSource(
            type=source_type,
            connector_id=connector_id,
            event_id=event_id,
            actor_id=actor_id,
            conversation_id=str(source_payload.get("conversation_id") or ""),
            metadata=_dict_value(source_payload.get("metadata")),
        ),
        delivery=ReplyRoute.from_dict(delivery_payload),
        routing=routing,
        message=message,
        raw_payload_summary=safe_payload_summary(payload),
        idempotency_key=str(payload.get("idempotency_key") or ""),
        correlation_id=correlation_id,
    )


def _verify_connector_token(container: Container, connector_id: str, provided: str) -> None:
    try:
        connector = container.connector_registry.require_ingress(connector_id)
    except PermissionDenied as exc:
        container.audit_service.record(
            "channel.ingress_denied",
            status="DENIED",
            summary=exc.safe_message,
            actor_id=connector_id,
            payload={"connector_id": connector_id},
        )
        raise HTTPException(status_code=403, detail=exc.safe_message) from exc
    expected = container.connector_registry.resolve_secret(connector)
    if expected and not hmac.compare_digest(expected, provided):
        container.audit_service.record(
            "channel.signature_failed",
            status="FAILED",
            summary="Channel credential verification failed",
            actor_id=connector_id,
            payload={"connector_id": connector_id},
        )
        raise HTTPException(status_code=401, detail="Invalid channel credential")
    container.audit_service.record(
        "channel.signature_verified",
        status="SUCCEEDED",
        summary="Channel credential verified",
        actor_id=connector_id,
        payload={"connector_id": connector_id},
    )


async def _json_payload(request: Any) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object")
    return payload


def _grafana_labels(payload: dict[str, Any]) -> dict[str, Any]:
    common = payload.get("commonLabels")
    if isinstance(common, dict) and common:
        return common
    alerts = payload.get("alerts")
    if isinstance(alerts, list) and alerts:
        labels = alerts[0].get("labels") if isinstance(alerts[0], dict) else None
        if isinstance(labels, dict):
            return labels
    labels = payload.get("labels")
    return labels if isinstance(labels, dict) else {}


def _grafana_event_id(payload: dict[str, Any]) -> str:
    if payload.get("groupKey"):
        return str(payload["groupKey"])
    alerts = payload.get("alerts")
    if isinstance(alerts, list) and alerts:
        first = alerts[0]
        if isinstance(first, dict) and first.get("fingerprint"):
            return str(first["fingerprint"])
    return str(payload.get("external_event_id") or new_correlation_id())


def _grafana_message(payload: dict[str, Any]) -> str:
    annotations = payload.get("commonAnnotations")
    if isinstance(annotations, dict):
        summary = annotations.get("summary") or annotations.get("description")
        if summary:
            return str(summary)
    title = str(payload.get("title") or "Grafana firing alert")
    return f"{title}\n\n{safe_payload_summary(payload)}"


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _container(request: Any) -> Container:
    container = getattr(request.app.state, "container", None)
    if not isinstance(container, Container):
        raise RuntimeError("Application container is not initialized")
    return container
