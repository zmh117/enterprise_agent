from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Mapping

from app.modules.audit.application.audit_service import AuditService
from app.modules.webhook.application.authentication import WebhookAuthenticator
from app.modules.webhook.application.mapping import WebhookMapper
from app.modules.webhook.domain.models import PUBLIC_ID_RE, WebhookEventStatus, config_hash
from app.modules.webhook.infrastructure import WebhookEventRepository, WebhookTriggerRepository
from app.shared.config import WebhookSettings
from app.shared.exceptions import AppError, NonRetryableExecutionError, NotFound, PermissionDenied
from app.shared.logging import new_correlation_id


@dataclass(frozen=True)
class WebhookAcknowledgement:
    event_id: str
    correlation_id: str
    accepted: bool
    ignored: bool
    duplicate: bool
    status: str
    reason: str = ""


class WebhookIngressService:
    def __init__(
        self,
        *,
        trigger_repository: WebhookTriggerRepository,
        event_repository: WebhookEventRepository,
        authenticator: WebhookAuthenticator,
        mapper: WebhookMapper,
        audit_service: AuditService,
        settings: WebhookSettings,
    ) -> None:
        self.trigger_repository = trigger_repository
        self.event_repository = event_repository
        self.authenticator = authenticator
        self.mapper = mapper
        self.audit_service = audit_service
        self.settings = settings

    def receive(
        self,
        *,
        public_id: str,
        raw_body: bytes,
        content_type: str,
        headers: Mapping[str, str],
        correlation_id: str = "",
        remote_address: str = "",
    ) -> WebhookAcknowledgement:
        correlation_id = correlation_id or new_correlation_id()
        if not self.settings.enabled or not PUBLIC_ID_RE.fullmatch(public_id):
            raise NotFound(
                "Webhook public ID not found",
                safe_message="Webhook endpoint not found",
                error_code="webhook_not_found",
            )
        definition = self.trigger_repository.get_definition_by_public_id(public_id)
        if not definition:
            raise NotFound(
                "Webhook public ID not found",
                safe_message="Webhook endpoint not found",
                error_code="webhook_not_found",
            )
        if (
            str(definition["status"]) != "enabled"
            or str(definition.get("service_account_status") or "") != "enabled"
            or str(definition.get("service_account_type") or "") != "service"
        ):
            raise PermissionDenied(
                "Webhook Trigger or service account is disabled",
                safe_message="Webhook endpoint is unavailable",
                error_code="webhook_disabled",
            )
        try:
            publication = self.trigger_repository.current_publication(str(definition["id"]))
        except NotFound as exc:
            raise PermissionDenied(
                "Webhook Trigger is not published",
                safe_message="Webhook endpoint is unavailable",
                error_code="webhook_not_published",
            ) from exc
        snapshot = publication["snapshot"]
        if config_hash(_revision_config(snapshot)) != str(publication["config_hash"]):
            raise PermissionDenied(
                "Webhook Trigger publication hash mismatch",
                safe_message="Webhook endpoint configuration failed integrity checks",
                error_code="webhook_not_published",
            )
        if not content_type.lower().split(";", 1)[0].strip() == "application/json":
            raise NonRetryableExecutionError(
                "Webhook content type is not JSON",
                safe_message="Content-Type must be application/json",
                error_code="webhook_invalid_content_type",
            )
        if len(raw_body) > self.settings.max_body_bytes:
            raise NonRetryableExecutionError(
                "Webhook request body exceeds configured limit",
                safe_message="Webhook payload is too large",
                error_code="webhook_payload_too_large",
            )
        payload_hash = hashlib.sha256(raw_body).hexdigest()
        try:
            auth_result = self.authenticator.authenticate(
                trigger_id=str(definition["id"]),
                config=snapshot,
                headers=headers,
                raw_body=raw_body,
            )
        except PermissionDenied as exc:
            self._record_rejection(
                definition=definition,
                publication=publication,
                payload_hash=payload_hash,
                request_bytes=len(raw_body),
                correlation_id=correlation_id,
                status=WebhookEventStatus.REJECTED_AUTH,
                error=exc,
                remote_address=remote_address,
            )
            raise
        try:
            payload = json.loads(raw_body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            error = NonRetryableExecutionError(
                "Webhook request body is invalid JSON",
                safe_message="Request body must be a JSON object",
                error_code="webhook_payload_invalid",
            )
            self._record_rejection(
                definition=definition,
                publication=publication,
                payload_hash=payload_hash,
                request_bytes=len(raw_body),
                correlation_id=correlation_id,
                status=WebhookEventStatus.REJECTED,
                error=error,
                remote_address=remote_address,
            )
            raise error from exc
        if not isinstance(payload, dict) or not _within_json_limits(
            payload,
            max_depth=self.settings.max_json_depth,
            max_items=self.settings.max_collection_items,
        ):
            error = NonRetryableExecutionError(
                "Webhook JSON shape exceeds configured limits",
                safe_message="Webhook JSON structure is not allowed",
                error_code="webhook_payload_invalid",
            )
            self._record_rejection(
                definition=definition,
                publication=publication,
                payload_hash=payload_hash,
                request_bytes=len(raw_body),
                correlation_id=correlation_id,
                status=WebhookEventStatus.REJECTED,
                error=error,
                remote_address=remote_address,
            )
            raise error
        request_count, in_flight = self.event_repository.rate_counts(
            trigger_id=str(definition["id"]),
            since=(datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
        )
        limits = snapshot["limits"]
        if request_count >= int(limits["requests_per_minute"]) or in_flight >= int(
            limits["max_in_flight"]
        ):
            rate_error = PermissionDenied(
                "Webhook Trigger rate limit exceeded",
                safe_message="Webhook rate limit exceeded",
                error_code="webhook_rate_limited",
            )
            self._record_rejection(
                definition=definition,
                publication=publication,
                payload_hash=payload_hash,
                request_bytes=len(raw_body),
                correlation_id=correlation_id,
                status=WebhookEventStatus.REJECTED,
                error=rate_error,
                remote_address=remote_address,
            )
            raise rate_error
        try:
            mapped = self.mapper.map(config=snapshot, payload=payload)
        except AppError as exc:
            self._record_rejection(
                definition=definition,
                publication=publication,
                payload_hash=payload_hash,
                request_bytes=len(raw_body),
                correlation_id=correlation_id,
                status=WebhookEventStatus.REJECTED,
                error=exc,
                remote_address=remote_address,
            )
            raise
        status = WebhookEventStatus.IGNORED if mapped.ignored else WebhookEventStatus.ACCEPTED
        normalized = mapped.normalized_event(delivery=snapshot["delivery"])
        cooldown_seconds = int(snapshot.get("idempotency", {}).get("cooldown_seconds") or 0)
        dedup_key = mapped.dedup_key
        if cooldown_seconds > 0:
            import time

            dedup_key = f"{dedup_key}:window:{int(time.time()) // cooldown_seconds}"
        with self.event_repository.database.transaction():
            event, created = self.event_repository.receive(
                trigger_id=str(definition["id"]),
                trigger_publication_id=str(publication["id"]),
                agent_publication_id=str(publication["agent_publication_id"]),
                service_account_id=str(definition["service_account_id"]),
                external_event_id=mapped.external_event_id,
                dedup_key=dedup_key,
                payload_hash=payload_hash,
                request_bytes=len(raw_body),
                safe_summary=mapped.safe_summary,
                normalized_event=normalized,
                correlation_id=correlation_id,
                status=status,
                auth_result=auth_result,
                filter_result=mapped.reason or "matched",
                enqueue=not mapped.ignored,
            )
        self.audit_service.record(
            "webhook.event.received",
            status="SKIPPED" if mapped.ignored else "SUCCEEDED",
            summary="Webhook event persisted",
            actor_id=str(definition["service_account_id"]),
            payload={
                "event_id": event["id"],
                "trigger_id": definition["id"],
                "trigger_publication_id": publication["id"],
                "correlation_id": event["correlation_id"],
                "duplicate": not created,
                "ignored": mapped.ignored,
            },
        )
        return WebhookAcknowledgement(
            event_id=str(event["id"]),
            correlation_id=str(event["correlation_id"]),
            accepted=not mapped.ignored,
            ignored=mapped.ignored,
            duplicate=not created,
            status=str(event["status"]),
            reason=mapped.reason,
        )

    def _record_rejection(
        self,
        *,
        definition: dict[str, Any],
        publication: dict[str, Any],
        payload_hash: str,
        request_bytes: int,
        correlation_id: str,
        status: WebhookEventStatus,
        error: AppError,
        remote_address: str,
    ) -> None:
        remote_hash = hashlib.sha256(remote_address.encode()).hexdigest()[:16] if remote_address else ""
        event, _ = self.event_repository.receive(
            trigger_id=str(definition["id"]),
            trigger_publication_id=str(publication["id"]),
            agent_publication_id=str(publication["agent_publication_id"]),
            service_account_id=str(definition["service_account_id"]),
            external_event_id="",
            dedup_key=None,
            payload_hash=payload_hash,
            request_bytes=request_bytes,
            safe_summary={"remote_hash": remote_hash},
            normalized_event={},
            correlation_id=correlation_id,
            status=status,
            auth_result="failed" if status == WebhookEventStatus.REJECTED_AUTH else "verified",
            filter_result="rejected",
            error_code=error.error_code,
            error_summary=error.safe_message,
        )
        self.audit_service.record(
            "webhook.event.rejected",
            status="DENIED",
            summary=error.safe_message,
            actor_id=str(definition["service_account_id"]),
            payload={
                "event_id": event["id"],
                "trigger_id": definition["id"],
                "error_code": error.error_code,
                "payload_hash": payload_hash,
                "request_bytes": request_bytes,
                "remote_hash": remote_hash,
            },
        )


def _revision_config(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in snapshot.items()
        if key not in {"service_account_id", "source_connector_id"}
    } | {
        "agent": {
            "code": snapshot.get("agent", {}).get("code", ""),
            "publication_id": snapshot.get("agent", {}).get("publication_id", ""),
        }
    }


def _within_json_limits(value: Any, *, max_depth: int, max_items: int) -> bool:
    remaining = max_items
    stack: list[tuple[Any, int]] = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        if depth > max_depth:
            return False
        if isinstance(current, dict):
            remaining -= len(current)
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            remaining -= len(current)
            stack.extend((item, depth + 1) for item in current)
        if remaining < 0:
            return False
    return True
