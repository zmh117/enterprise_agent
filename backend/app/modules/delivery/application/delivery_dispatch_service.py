from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
import sqlite3
import time

from app.modules.audit.application.audit_service import AuditService
from app.modules.channel.domain.channel_event import ReplyRoute
from app.modules.channel.infrastructure.connector_registry import Connector
from app.modules.delivery.application.result_delivery_service import (
    ResultDeliveryService,
)
from app.modules.delivery.domain import DeliveryEvent, DeliveryStatus
from app.modules.delivery.infrastructure.file_delivery_sender import FileDeliverySender
from app.modules.file_workspace.delivery_service import FileVersionDeliveryService
from app.modules.job.infrastructure.repositories import AgentRepository
from app.shared.config import DeliverySettings
from app.shared.exceptions import (
    NonRetryableExecutionError,
    RetryableExecutionError,
)


@dataclass(frozen=True)
class DeliveryDispatchResult:
    succeeded: int = 0
    skipped: int = 0
    retrying: int = 0
    failed: int = 0
    dead: int = 0
    recovered: int = 0


class DeliveryOutboxDispatcher:
    def __init__(
        self,
        *,
        repository: AgentRepository,
        delivery_service: ResultDeliveryService,
        audit_service: AuditService,
        settings: DeliverySettings,
        worker_id: str = "",
        file_delivery_sender: FileDeliverySender | None = None,
        file_delivery_service: FileVersionDeliveryService | None = None,
    ) -> None:
        self.repository = repository
        self.delivery_service = delivery_service
        self.audit_service = audit_service
        self.settings = settings
        self.worker_id = worker_id or f"delivery-dispatcher-{os.getpid()}"
        self.file_delivery_sender = file_delivery_sender
        self.file_delivery_service = file_delivery_service

    def dispatch_pending(self, *, limit: int = 100) -> DeliveryDispatchResult:
        recovered, recovered_dead = self.repository.recover_stale_delivery_claims()
        succeeded = skipped = retrying = failed = dead = 0
        for _ in range(min(max(1, int(limit)), 1000)):
            event = self.repository.claim_delivery_event(
                worker_id=self.worker_id,
                claim_timeout_seconds=(self.settings.outbox_claim_timeout_seconds),
            )
            if event is None:
                break
            attempt = self.repository.create_delivery_attempt(event=event)
            attempt_id = str(attempt["id"])
            try:
                outcome = self._dispatch_claimed(
                    event=event,
                    attempt_id=attempt_id,
                )
            except Exception as exc:
                state = self.repository.mark_delivery_failed(
                    event=event,
                    attempt_id=attempt_id,
                    retryable=_is_retryable(exc),
                    error_code=_safe_error_code(exc),
                    error_summary=_safe_error_summary(exc),
                    retry_base_seconds=(self.settings.outbox_retry_base_seconds),
                )
                if state.status == DeliveryStatus.RETRY_WAIT:
                    retrying += 1
                elif state.status == DeliveryStatus.DEAD:
                    dead += 1
                else:
                    failed += 1
                self.audit_service.record(
                    "delivery.dispatch.failed",
                    status=state.status.value,
                    summary="Delivery dispatch failed safely",
                    job_id=event.job_id,
                    actor_id=self.worker_id,
                    payload={
                        "delivery_id": event.id,
                        "attempt_no": event.attempt_count,
                        "error_code": state.last_error_code,
                        "outbox_status": state.status.value,
                    },
                )
                continue
            if outcome == DeliveryStatus.SKIPPED:
                skipped += 1
            else:
                succeeded += 1
        return DeliveryDispatchResult(
            succeeded=succeeded,
            skipped=skipped,
            retrying=retrying,
            failed=failed,
            dead=dead + recovered_dead,
            recovered=recovered,
        )

    def _dispatch_claimed(
        self,
        *,
        event: DeliveryEvent,
        attempt_id: str,
    ) -> DeliveryStatus:
        job = self.repository.get_job(event.job_id)
        artifact = self.repository.get_artifact(event.result_artifact_id)
        route = ReplyRoute.from_dict(job.reply_route)
        self._require_original_binding(event, route, job.reply_route or {})
        self.audit_service.record(
            "delivery.started",
            status="RUNNING",
            summary="Delivery Dispatcher claimed persisted intent",
            job_id=event.job_id,
            actor_id=self.worker_id,
            payload={
                "delivery_id": event.id,
                "attempt_id": attempt_id,
                "attempt_no": event.attempt_count,
                "route_type": route.type,
                "connector_id": route.connector_id,
            },
        )
        if route.type == "none":
            self.repository.mark_delivery_skipped(
                event=event,
                attempt_id=attempt_id,
            )
            self.audit_service.record(
                "delivery.skipped",
                status="SKIPPED",
                summary="Delivery route is none",
                job_id=event.job_id,
                actor_id=self.worker_id,
                payload={
                    "delivery_id": event.id,
                    "attempt_id": attempt_id,
                },
            )
            return DeliveryStatus.SKIPPED

        self._require_delivery_authorization(job, event, artifact)
        connector = None
        file_version_delivery = (
            str(event.delivery_binding.get("delivery_kind") or "") == "file_version"
        )
        if route.connector_id:
            connector = self.delivery_service.connector_registry.require_delivery(
                route.connector_id
            )
            endpoint = self.delivery_service.connector_registry.endpoint_url(connector)
            self.delivery_service.connector_registry.assert_host_allowed(
                connector,
                endpoint,
            )
            self.audit_service.record(
                "delivery.connector_authorized",
                status="SUCCEEDED",
                summary="Delivery connector authorized",
                job_id=event.job_id,
                actor_id=self.worker_id,
                payload={
                    "delivery_id": event.id,
                    "route_type": route.type,
                    "connector_id": route.connector_id,
                },
            )
        elif file_version_delivery and route.type == "dingtalk_stream_session_webhook":
            connector = (
                self.delivery_service.connector_registry
                .require_dingtalk_stream_file_delivery(
                    str(getattr(job, "source_connector_id", "") or "")
                )
            )
            self.audit_service.record(
                "delivery.connector_authorized",
                status="SUCCEEDED",
                summary=(
                    "Originating DingTalk Stream connector authorized for exact file delivery"
                ),
                job_id=event.job_id,
                actor_id=self.worker_id,
                payload={
                    "delivery_id": event.id,
                    "route_type": route.type,
                    "connector_id": connector.id,
                    "connector_use": "same_conversation_file_version",
                },
            )
        if file_version_delivery:
            return self._dispatch_file_version(
                event=event,
                attempt_id=attempt_id,
                route=route,
                connector=connector,
            )
        adapter = self.delivery_service.adapters.get(route.type)
        if adapter is None:
            raise NonRetryableExecutionError(
                f"Delivery adapter is not installed: {route.type}",
                safe_message="投递适配器未安装",
                error_code="delivery_adapter_not_installed",
            )
        title = str(event.delivery_binding.get("title") or "Agent 诊断结果")
        chunks = self.delivery_service.chunker.titled_chunks(
            title=title,
            text=str(artifact["content"]),
        )
        for index, (chunk_title, chunk_text) in enumerate(chunks, start=1):
            payload_hash = _chunk_payload_hash(chunk_title, chunk_text)
            if self.repository.has_successful_delivery_chunk(
                delivery_id=event.id,
                chunk_index=index,
                payload_hash=payload_hash,
            ):
                self.audit_service.record(
                    "delivery.chunk_deduplicated",
                    status="SUCCEEDED",
                    summary="Previously successful Delivery chunk was not resent",
                    job_id=event.job_id,
                    actor_id=self.worker_id,
                    payload={
                        "delivery_id": event.id,
                        "chunk_index": index,
                        "chunk_count": len(chunks),
                    },
                )
                continue
            try:
                adapter.send(
                    connector=connector,
                    route=route,
                    title=chunk_title,
                    text=chunk_text,
                )
            except Exception as exc:
                self._record_delivery_chunk(
                    event=event,
                    attempt_id=attempt_id,
                    chunk_index=index,
                    chunk_count=len(chunks),
                    payload_hash=payload_hash,
                    payload_summary={
                        "title": chunk_title,
                        "chars": len(chunk_text),
                    },
                    status="FAILED",
                    error_message=_safe_error_summary(exc),
                )
                raise
            self.delivery_service.sent_messages.append(
                {
                    "title": chunk_title,
                    "text": chunk_text,
                    "route_type": route.type,
                }
            )
            self._record_delivery_chunk(
                event=event,
                attempt_id=attempt_id,
                chunk_index=index,
                chunk_count=len(chunks),
                payload_hash=payload_hash,
                payload_summary={
                    "title": chunk_title,
                    "chars": len(chunk_text),
                },
                status="SUCCEEDED",
            )
            self.audit_service.record(
                "delivery.chunk_sent",
                status="SUCCEEDED",
                summary="Delivery chunk sent",
                job_id=event.job_id,
                actor_id=self.worker_id,
                payload={
                    "delivery_id": event.id,
                    "attempt_id": attempt_id,
                    "chunk_index": index,
                    "chunk_count": len(chunks),
                },
            )
        self.repository.mark_delivery_succeeded(
            event=event,
            attempt_id=attempt_id,
        )
        self.audit_service.record(
            "delivery.completed",
            status="SUCCEEDED",
            summary="Persisted Delivery intent completed",
            job_id=event.job_id,
            actor_id=self.worker_id,
            payload={
                "delivery_id": event.id,
                "attempt_id": attempt_id,
                "chunk_count": len(chunks),
            },
        )
        return DeliveryStatus.SUCCEEDED

    def _dispatch_file_version(
        self,
        *,
        event: DeliveryEvent,
        attempt_id: str,
        route: ReplyRoute,
        connector: Connector | None,
    ) -> DeliveryStatus:
        if self.file_delivery_sender is None or self.file_delivery_service is None:
            raise NonRetryableExecutionError(
                "File Delivery adapter is not installed",
                safe_message="文件交付适配器未安装",
                error_code="file_delivery_adapter_not_installed",
            )
        binding = self.file_delivery_service.exact_binding(event.id)
        if binding is None:
            raise NonRetryableExecutionError(
                "File Delivery binding is missing",
                safe_message="文件交付绑定无效",
                error_code="file_delivery_binding_invalid",
            )
        payload_hash = hashlib.sha256(
            json.dumps(
                {
                    "delivery_id": event.id,
                    "file_id": binding["file_id"],
                    "version_id": binding["file_version_id"],
                    "sha256": binding["file_content_sha256"],
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        if not self.repository.has_successful_delivery_chunk(
            delivery_id=event.id,
            chunk_index=1,
            payload_hash=payload_hash,
        ):
            self.file_delivery_sender.send(
                delivery_id=event.id,
                connector=connector,
                route=route,
                idempotency_key=event.event_key,
            )
            self._record_delivery_chunk(
                event=event,
                attempt_id=attempt_id,
                chunk_index=1,
                chunk_count=1,
                payload_hash=payload_hash,
                payload_summary={
                    "file_count": 1,
                    "version_id": str(binding["file_version_id"]),
                },
                status="SUCCEEDED",
            )
        self.repository.mark_delivery_succeeded(event=event, attempt_id=attempt_id)
        self.file_delivery_service.retain_delivered_version(delivery_id=event.id)
        self.audit_service.record(
            "delivery.file.completed",
            status="SUCCEEDED",
            summary="Exact File Version Delivery completed",
            job_id=event.job_id,
            actor_id=self.worker_id,
            payload={
                "delivery_id": event.id,
                "version_id": str(binding["file_version_id"]),
            },
        )
        return DeliveryStatus.SUCCEEDED

    def _record_delivery_chunk(
        self,
        *,
        event: DeliveryEvent,
        attempt_id: str,
        chunk_index: int,
        chunk_count: int,
        payload_hash: str,
        payload_summary: dict[str, object],
        status: str,
        error_message: str = "",
    ) -> str:
        """Persist post-send evidence without converting SQLite locks to retries.

        Production PostgreSQL claims are row-scoped. SQLite test/runtime
        databases take broader writer locks, so a concurrent Dispatcher may
        momentarily block the evidence write after the external adapter has
        already succeeded. Retrying only this idempotent database write avoids
        resending the external chunk.
        """
        for attempt in range(50):
            try:
                return self.repository.record_delivery_chunk(
                    event=event,
                    attempt_id=attempt_id,
                    chunk_index=chunk_index,
                    chunk_count=chunk_count,
                    payload_hash=payload_hash,
                    payload_summary=payload_summary,
                    status=status,
                    error_message=error_message,
                )
            except sqlite3.OperationalError as exc:
                if (
                    self.repository.database.engine != "sqlite"
                    or "locked" not in str(exc).lower()
                    or attempt == 49
                ):
                    raise
                time.sleep(0.01)
        raise AssertionError("unreachable")

    def _require_original_binding(
        self,
        event: DeliveryEvent,
        route: ReplyRoute,
        route_payload: dict[str, object],
    ) -> None:
        canonical = json.dumps(
            route_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        route_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if (
            route_hash != str(event.delivery_binding.get("route_hash") or "")
            or route.type != str(event.delivery_binding.get("route_type") or "")
            or route.connector_id != str(event.delivery_binding.get("connector_id") or "")
        ):
            raise NonRetryableExecutionError(
                "Persisted Delivery binding no longer matches the Job",
                safe_message="固化投递绑定与任务记录不一致",
                error_code="delivery_binding_mismatch",
            )

    def _require_delivery_authorization(
        self,
        job: object,
        event: DeliveryEvent,
        artifact: dict[str, object],
    ) -> None:
        application_id = str(getattr(job, "business_application_id", "") or "")
        if not application_id:
            return
        if (
            str(event.delivery_binding.get("delivery_kind") or "") == "failure"
            and str(event.delivery_binding.get("failure_error_code") or "")
            == "business_application_denied"
            and str(artifact.get("artifact_type") or "") == "failure_notification"
        ):
            self.audit_service.record(
                "authorization.business.denial_notice_delivery_allowed",
                status="SUCCEEDED",
                summary="Safe authorization denial notice allowed on original reply route",
                job_id=str(getattr(job, "id")),
                actor_id=str(getattr(job, "internal_user_id", "") or getattr(job, "user_id", "")),
                payload={
                    "delivery_id": event.id,
                    "error_code": "business_application_denied",
                },
            )
            return
        authorization = self.delivery_service.business_authorization_service
        if authorization is None:
            raise NonRetryableExecutionError(
                "Business authorization service is unavailable for Delivery",
                safe_message="投递授权服务暂时不可用",
                error_code="delivery_authorization_unavailable",
            )
        decision = authorization.decide(
            user_id=str(getattr(job, "internal_user_id", "") or getattr(job, "user_id", "")),
            application_id=application_id,
            stage="delivery",
        )
        if not decision["allowed"]:
            self.audit_service.record(
                "authorization.business.delivery_blocked",
                status="DENIED",
                summary="Business result delivery blocked by authorization",
                job_id=str(getattr(job, "id")),
                actor_id=str(getattr(job, "internal_user_id", "") or getattr(job, "user_id", "")),
                payload=decision,
            )
            raise NonRetryableExecutionError(
                "Business authorization denied Delivery",
                safe_message="投递前业务应用授权已失效",
                error_code="delivery_authorization_denied",
            )


def _chunk_payload_hash(title: str, text: str) -> str:
    payload = json.dumps(
        {"title": title, "text": text},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, NonRetryableExecutionError):
        return False
    if isinstance(
        exc,
        (RetryableExecutionError, TimeoutError, ConnectionError, OSError),
    ):
        return True
    return bool(getattr(exc, "retryable", False))


def _safe_error_code(exc: Exception) -> str:
    code = str(getattr(exc, "error_code", "") or "").strip()
    if code:
        return code[:100]
    return f"delivery_{exc.__class__.__name__.lower()}"[:100]


def _safe_error_summary(exc: Exception) -> str:
    safe_message = str(getattr(exc, "safe_message", "") or "").strip()
    if safe_message:
        return safe_message[:500]
    return f"Delivery failed ({exc.__class__.__name__})"
