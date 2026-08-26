from __future__ import annotations

import json
from typing import Any

from app.modules.admin.application.file_operations_service import (
    FileOperationsStatusService,
)
from app.modules.admin.infrastructure.rabbitmq_status import RabbitMQQueueStatusAdapter
from app.shared.config import QueueSettings


class _Database:
    def __init__(self) -> None:
        self.retention_params: tuple[object, ...] = ()

    def execute_one(self, sql: str, params: tuple[object, ...] = ()) -> dict[str, Any] | None:
        normalized = " ".join(sql.split())
        if "from file_cleanup_fact" in normalized and "sum(case" in normalized:
            return {
                "cleanup": 7,
                "staging": 2,
                "attachment": 3,
                "earliest_due": "2026-08-15T01:00:00+00:00",
            }
        if "from task_workspace" in normalized:
            return {"value": 1}
        if "from file_retention_fact" in normalized:
            self.retention_params = params
            assert "current_timestamp" not in normalized
            return {"value": 4}
        if "from file_conflict_candidate" in normalized:
            return {"value": 2}
        if "from file_domain_outbox" in normalized:
            return {
                "backlog": 9,
                "earliest_created_at": "2026-08-14T23:00:00+00:00",
                "failure_code": "file_domain_outbox_runtimeerror",
            }
        if "order by updated_at desc" in normalized:
            return {
                "status": "RETRY",
                "resource_type": "STAGING_OBJECT",
                "reason": "STAGING_EXPIRED",
                "failure_code": "TimeoutError",
                "updated_at": "2026-08-15T02:00:00+00:00",
            }
        raise AssertionError(normalized)

    def execute(
        self, sql: str, params: tuple[object, ...] = ()
    ) -> list[dict[str, Any]]:
        normalized = " ".join(sql.split())
        if "group by r.tenant_id" in normalized:
            return [
                {
                    "tenant_id": "tenant-safe",
                    "application_id": "application-safe",
                    "application_code": "diagnostic-safe",
                    "publication_id": "publication-safe",
                    "profile_code": "docling-layout-ocr-v2",
                    "status": "FAILED",
                    "count": 2,
                    "total_attempts": 4,
                    "source_size_bytes": 1200,
                    "output_size_bytes": 0,
                    "earliest_created_at": "2026-08-15T00:00:00+00:00",
                    "latest_updated_at": "2026-08-15T02:00:00+00:00",
                }
            ]
        run = {
            "run_id": "run-safe",
            "source_version_id": "version-safe",
            "tenant_id": "tenant-safe",
            "job_id": "job-safe",
            "application_id": "application-safe",
            "application_code": "diagnostic-safe",
            "publication_id": "publication-safe",
            "profile_code": "docling-layout-ocr-v2",
            "profile_hash": "a" * 64,
            "status": "FAILED",
            "attempt": 2,
            "error_code": "docling_format_rejected",
            "page_count": 3,
            "processing_time_ms": 2000,
            "updated_at": "2026-08-15T02:00:00+00:00",
        }
        if "where r.status = 'FAILED'" in normalized:
            return [run]
        if "r.processor_build_digest" in normalized:
            return [
                {
                    **run,
                    "processor_code": "docling-serve",
                    "processor_version": "1.30.0",
                    "processor_build_digest": "sha256:" + "b" * 64,
                    "source_size_bytes": 600,
                    "created_at": "2026-08-15T00:00:00+00:00",
                }
            ]
        if "where processing_run_id in" in normalized:
            assert params == ("run-safe",)
            return [
                {
                    "id": "representation-safe",
                    "processing_run_id": "run-safe",
                    "source_version_id": "version-safe",
                    "kind": "MARKDOWN",
                    "media_type": "text/markdown",
                    "status": "AVAILABLE",
                    "size_bytes": 42,
                    "content_sha256": "c" * 64,
                    "profile_hash": "a" * 64,
                    "created_at": "2026-08-15T01:00:00+00:00",
                    "content_deleted_at": None,
                }
            ]
        raise AssertionError(normalized)


class _Queues:
    def collect(self) -> dict[str, Any]:
        return {
            "items": [
                {
                    "name": "agent.attachment.queue",
                    "availability": "available",
                    "ready": 5,
                    "unacked": 1,
                    "consumers": 1,
                },
                {
                    "name": "agent.file.processing.queue",
                    "availability": "available",
                    "ready": 2,
                    "unacked": 0,
                    "consumers": 2,
                },
                {
                    "name": "agent.file.processing.retry.queue",
                    "availability": "available",
                    "ready": 1,
                    "unacked": 0,
                    "consumers": 0,
                },
                {
                    "name": "agent.file.processing.dead.queue",
                    "availability": "available",
                    "ready": 3,
                    "unacked": 0,
                    "consumers": 0,
                },
            ]
        }


def test_rabbitmq_operations_allowlist_contains_document_processing_topology() -> None:
    settings = QueueSettings()
    items = RabbitMQQueueStatusAdapter("amqp://guest:guest@rabbitmq:5672/", settings)._allowlist()
    by_name = {str(item["name"]): item for item in items}

    assert by_name[settings.file_processing_queue] == {
        "name": settings.file_processing_queue,
        "purpose": "Document processing",
        "retry_of": None,
        "dead_letter_of": None,
    }
    assert by_name[settings.file_processing_retry_queue]["retry_of"] == (
        settings.file_processing_queue
    )
    assert by_name[settings.file_processing_dead_queue]["dead_letter_of"] == (
        settings.file_processing_queue
    )


def test_file_operations_projection_is_safe_bounded_and_worker_aware() -> None:
    database = _Database()
    status = FileOperationsStatusService(
        database,  # type: ignore[arg-type]
        _Queues(),
        attachment_queue="agent.attachment.queue",
        file_processing_queue="agent.file.processing.queue",
        file_processing_retry_queue="agent.file.processing.retry.queue",
        file_processing_dead_queue="agent.file.processing.dead.queue",
        file_service_base_url="http://file-service:9105",
        file_service_allowed_hosts=("file-service",),
        file_processing_worker_base_url="http://file-processing-worker:9106",
        file_processing_worker_allowed_hosts=("file-processing-worker",),
        file_service_probe=lambda: {
            "configured": True,
            "ready": True,
            "reason_code": "ready",
        },
        file_processing_worker_probe=lambda: {
            "configured": True,
            "ready": True,
            "reason_code": "ready",
            "components": {
                "rabbitmq": "ready",
                "file_service": "ready",
                "docling": "ready",
            },
        },
    ).query()

    assert status["file_service"]["ready"] is True
    assert status["file_worker"]["ready"] is True
    assert status["file_worker"]["attachment_queue"] == {
        "availability": "available",
        "ready": 5,
        "unacked": 1,
        "consumers": 1,
    }
    assert status["document_processing"]["configured"] is True
    assert status["document_processing"]["ready"] is True
    assert status["document_processing"]["reason_code"] == "ready"
    assert status["document_processing"]["file_processing_worker"] == {
            "configured": True,
            "ready": True,
            "reason_code": "ready",
            "components": {
                "rabbitmq": "ready",
                "file_service": "ready",
                "docling": "ready",
            },
        }
    assert status["document_processing"]["queues"] == {
            "processing": {
                "availability": "available",
                "ready": 2,
                "unacked": 0,
                "consumers": 2,
            },
            "retry": {
                "availability": "available",
                "ready": 1,
                "unacked": 0,
                "consumers": 0,
            },
            "dead": {
                "availability": "available",
                "ready": 3,
                "unacked": 0,
                "consumers": 0,
            },
    }
    operations = status["document_processing"]["operations"]
    assert operations["groups"] == [
        {
            "tenant_id": "tenant-safe",
            "application_id": "application-safe",
            "application_code": "diagnostic-safe",
            "publication_id": "publication-safe",
            "profile_code": "docling-layout-ocr-v2",
            "status": "FAILED",
            "count": 2,
            "total_attempts": 4,
            "source_size_bytes": 1200,
            "output_size_bytes": 0,
            "earliest_created_at": "2026-08-15T00:00:00+00:00",
            "latest_updated_at": "2026-08-15T02:00:00+00:00",
        }
    ]
    assert operations["recent_failures"][0]["error_code"] == "docling_format_rejected"
    assert operations["traces"][0]["representations"] == [
        {
            "representation_id": "representation-safe",
            "source_version_id": "version-safe",
            "kind": "MARKDOWN",
            "media_type": "text/markdown",
            "status": "AVAILABLE",
            "size_bytes": 42,
            "content_sha256": "c" * 64,
            "profile_hash": "a" * 64,
            "created_at": "2026-08-15T01:00:00+00:00",
            "content_deleted_at": "",
        }
    ]
    assert status["backlog"] == {
        "cleanup": 7,
        "staging": 2,
        "attachment": 3,
        "workspace": 1,
        "retained": 4,
        "conflict": 2,
        "domain_outbox": 9,
    }
    assert status["domain_outbox_earliest_created_at"] == "2026-08-14T23:00:00+00:00"
    assert status["domain_outbox_failure_code"] == "file_domain_outbox_runtimeerror"
    assert len(database.retention_params) == 1
    assert "+00:00" in str(database.retention_params[0])
    serialized = json.dumps(status)
    for forbidden in (
        "display_name",
        "object_key",
        "secret",
        "access_key",
        "file body",
    ):
        assert forbidden not in serialized.lower()


def test_file_operations_never_reports_document_processing_ready_when_worker_is_down() -> None:
    status = FileOperationsStatusService(
        _Database(),  # type: ignore[arg-type]
        _Queues(),
        attachment_queue="agent.attachment.queue",
        file_processing_queue="agent.file.processing.queue",
        file_processing_retry_queue="agent.file.processing.retry.queue",
        file_processing_dead_queue="agent.file.processing.dead.queue",
        file_service_base_url="http://file-service:9105",
        file_service_allowed_hosts=("file-service",),
        file_processing_worker_base_url="http://file-processing-worker:9106",
        file_processing_worker_allowed_hosts=("file-processing-worker",),
        file_service_probe=lambda: {
            "configured": True,
            "ready": True,
            "reason_code": "ready",
        },
        file_processing_worker_probe=lambda: {
            "configured": True,
            "ready": False,
            "reason_code": "docling_unavailable",
            "components": {
                "rabbitmq": "ready",
                "file_service": "ready",
                "docling": "unavailable",
            },
        },
    ).query()

    assert status["document_processing"]["ready"] is False
    assert status["document_processing"]["reason_code"] == "docling_unavailable"
