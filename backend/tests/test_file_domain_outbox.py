from __future__ import annotations

import asyncio
from typing import Any

from app.modules.audit.application.audit_service import AuditService
from app.modules.file_workspace.domain_outbox import FileDomainOutboxPublisher
from app.modules.file_workspace.domain_outbox import AuditFileDomainEventSink
from app.modules.file_workspace.lifecycle_service import FileLifecycleService
from app.modules.job.infrastructure.repositories import AuditRepository
from backend.tests.test_file_commit_streaming import _body, _fixture, _new_intent


class _CaptureSink:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.fail_once = False

    def publish(self, event: dict[str, Any]) -> None:
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("synthetic safe sink failure")
        self.events.append(event)


def test_attachment_import_domain_outbox_is_supported() -> None:
    repository, _, _, _ = _fixture()
    repository.add_domain_outbox(
        event_type="file.attachment.imported",
        aggregate_type="managed_file_version",
        aggregate_id="file-version-imported",
        payload={
            "attachment_id": "attachment-imported",
            "file_id": "managed-file-imported",
            "version_id": "file-version-imported",
            "workspace_id": "workspace-imported",
            "size_bytes": 12,
            "content_sha256": "a" * 64,
        },
    )
    sink = _CaptureSink()

    result = FileDomainOutboxPublisher(repository, sink).publish_pending()

    assert result.published == 1
    assert result.failed == 0
    assert sink.events[0]["event_type"] == "file.attachment.imported"
    assert sink.events[0]["payload"]["attachment_id"] == "attachment-imported"


def test_attachment_import_audit_projection_has_no_fake_job_binding() -> None:
    repository, _, _, _ = _fixture()
    repository.add_domain_outbox(
        event_type="file.attachment.imported",
        aggregate_type="managed_file_version",
        aggregate_id="file-version-audited",
        payload={
            "attachment_id": "attachment-audited",
            "file_id": "managed-file-audited",
            "version_id": "file-version-audited",
            "workspace_id": "workspace-audited",
            "size_bytes": 12,
            "content_sha256": "b" * 64,
        },
    )
    audit = AuditService(AuditRepository(repository.database))

    result = FileDomainOutboxPublisher(
        repository, AuditFileDomainEventSink(audit)
    ).publish_pending()

    assert result.published == 1
    row = repository.database.execute_one(
        "select job_id, event_type from audit_event order by created_at desc limit 1"
    )
    assert row == {"job_id": None, "event_type": "file.domain_event.published"}


def test_audit_record_treats_blank_job_id_as_unbound() -> None:
    repository, _, _, _ = _fixture()
    audit = AuditService(AuditRepository(repository.database))
    audit.record(
        "delivery.dispatch.failed",
        status="FAILED",
        summary="Delivery dispatch failed safely",
        job_id="",
        actor_id="delivery-dispatcher",
        payload={"delivery_kind": "system_notice"},
    )
    row = repository.database.execute_one(
        "select job_id, event_type from audit_event order by created_at desc limit 1"
    )
    assert row == {"job_id": None, "event_type": "delivery.dispatch.failed"}


def test_file_domain_outbox_is_published_once_by_maintenance() -> None:
    repository, streaming, context, storage = _fixture()
    committed = asyncio.run(
        streaming.upload_commit(
            commit_id=_new_intent(streaming, context, handle="outbox-output"),
            token="file-principal-token",
            body=_body(b"outbox event\n"),
        )
    )
    sink = _CaptureSink()
    publisher = FileDomainOutboxPublisher(repository, sink)
    lifecycle = FileLifecycleService(repository, storage, domain_outbox=publisher)

    result = lifecycle.run_once()

    assert result["domain_outbox_published"] == 1
    assert result["domain_outbox_failed"] == 0
    assert len(sink.events) == 1
    assert sink.events[0]["aggregate_id"] == committed["version_id"]
    assert sink.events[0]["payload"]["file_id"] == committed["file_id"]
    assert sink.events[0]["payload"]["format_code"] == "TXT"
    assert repository.database.execute_one(
        "select status, attempt_count from file_domain_outbox"
    ) == {"status": "PUBLISHED", "attempt_count": 1}
    assert lifecycle.run_once()["domain_outbox_published"] == 0
    assert len(sink.events) == 1
    assert lifecycle.metrics()["domain_outbox_backlog"] == 0


def test_failed_file_domain_outbox_projection_remains_visible_and_retries() -> None:
    repository, streaming, context, storage = _fixture()
    asyncio.run(
        streaming.upload_commit(
            commit_id=_new_intent(streaming, context, handle="outbox-retry"),
            token="file-principal-token",
            body=_body(b"retry event\n"),
        )
    )
    sink = _CaptureSink()
    sink.fail_once = True
    lifecycle = FileLifecycleService(
        repository,
        storage,
        domain_outbox=FileDomainOutboxPublisher(repository, sink),
    )

    failed = lifecycle.run_once()
    assert failed["domain_outbox_failed"] == 1
    metrics = lifecycle.metrics()
    assert metrics["domain_outbox_backlog"] == 1
    assert metrics["domain_outbox_earliest_created_at"]
    assert metrics["domain_outbox_failure_code"] == "file_domain_outbox_runtimeerror"

    recovered = lifecycle.run_once()
    assert recovered["domain_outbox_published"] == 1
    assert lifecycle.metrics()["domain_outbox_backlog"] == 0
    assert len(sink.events) == 1
