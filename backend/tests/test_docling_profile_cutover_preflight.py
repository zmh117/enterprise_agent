from __future__ import annotations

from datetime import UTC, datetime

from app.modules.document_processing.cutover import (
    DoclingProfileCutoverPreflight,
    DoclingQuarantineRecovery,
)
from app.modules.document_processing.profile import DOCLING_LAYOUT_OCR_V2
from app.modules.document_processing.service import GovernedDocumentProcessingService
from app.shared.database import Database
from backend.tests.test_document_processing_service import _service as _document_service


def _service() -> tuple[Database, GovernedDocumentProcessingService, str, str]:
    database, _storage, service, file_id, version_id, _body = _document_service()
    return database, service, file_id, version_id


def test_cutover_preflight_blocks_only_old_hash_non_terminal_work() -> None:
    database, service, file_id, version_id = _service()
    run = service.request_processing(
        tenant_id="tenant-default",
        source_file_id=file_id,
        source_version_id=version_id,
        actor_id="file-worker",
        correlation_id="cutover",
    )
    database.execute(
        "update file_processing_run set profile_hash = ? where id = ?",
        ("7" * 64, run["id"]),
    )

    blocked = DoclingProfileCutoverPreflight(database).run()
    assert blocked["status"] == "blocked"
    assert blocked["parent_non_terminal"] == {"QUEUED": 1}
    assert blocked["picture_non_terminal_total"] == 0

    database.execute(
        """
        update file_processing_run
           set status = 'FAILED', completed_at = ?, updated_at = ?
         where id = ?
        """,
        (datetime(2026, 8, 25, tzinfo=UTC).isoformat(),) * 2 + (run["id"],),
    )
    ready = DoclingProfileCutoverPreflight(database).run()
    assert ready["status"] == "ready"
    assert ready["parent_non_terminal_total"] == 0
    database.close()


def test_cutover_preflight_allows_fresh_database_without_processing_schema() -> None:
    database = Database("sqlite:///:memory:")
    report = DoclingProfileCutoverPreflight(database).run()
    assert report["status"] == "ready"
    assert report["schema_present"] is False
    database.close()


def test_quarantine_recovery_requires_expired_workers_and_docling_restart() -> None:
    database, service, file_id, version_id = _service()
    run = service.request_processing(
        tenant_id="tenant-default",
        source_file_id=file_id,
        source_version_id=version_id,
        actor_id="file-worker",
        correlation_id="quarantine",
    )
    acquired = service.acquire_docling_slot(
        owner_kind="PARENT_RUN",
        owner_id=str(run["id"]),
        worker_instance_id="worker-recovery-0001",
        service_principal_id="file-processing-worker",
        now=datetime(2026, 8, 25, 12, 0, tzinfo=UTC),
    )
    assert acquired["acquired"] is True
    service.quarantine_docling_slot(
        owner_kind="PARENT_RUN",
        owner_id=str(run["id"]),
        worker_instance_id="worker-recovery-0001",
        reason_code="docling_task_state_unknown",
        service_principal_id="file-processing-worker",
        now=datetime(2026, 8, 25, 12, 0, tzinfo=UTC),
    )
    service.record_processing_worker_heartbeat(
        instance_id="worker-recovery-0001",
        profile_hash=DOCLING_LAYOUT_OCR_V2.profile_hash,
        queue_contract="file-processing/v1",
        docling_local_workers=2,
        status="READY",
        reason_code="ready",
        service_principal_id="file-processing-worker",
        now=datetime(2026, 8, 25, 12, 0, tzinfo=UTC),
    )

    not_confirmed = DoclingQuarantineRecovery(
        database,
        now=datetime(2026, 8, 25, 12, 2, tzinfo=UTC),
    ).run(docling_restarted=False)
    assert not_confirmed["reason_code"] == "docling_restart_not_confirmed"

    worker_active = DoclingQuarantineRecovery(
        database,
        now=datetime(2026, 8, 25, 12, 1, tzinfo=UTC),
    ).run(docling_restarted=True)
    assert worker_active["reason_code"] == "file_processing_workers_still_active"

    recovered = DoclingQuarantineRecovery(
        database,
        now=datetime(2026, 8, 25, 12, 2, tzinfo=UTC),
    ).run(docling_restarted=True)
    assert recovered == {
        "status": "recovered",
        "reason_code": "ready",
        "active_workers": 0,
        "quarantined_slots": 1,
        "recovered_slots": 1,
    }
    assert service.docling_concurrency_readiness()["slots_quarantined"] == 0
    database.close()
