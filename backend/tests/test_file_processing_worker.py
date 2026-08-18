from __future__ import annotations

from dataclasses import replace
from typing import Any

from app.modules.document_processing.file_service_client import ClaimedDocumentRun
from app.modules.document_processing.provider import (
    DocumentProcessorFailure,
    DocumentProcessorResult,
    ProcessorTask,
    ProcessorTaskState,
)
from app.modules.document_processing.worker_service import FileProcessingWorkerService
from app.modules.message_bus.application.message_publisher import (
    FileProcessingDisposition,
    FileProcessingTaskMessage,
)
from app.workers.file_processing_worker import document_processing_readiness


MESSAGE = FileProcessingTaskMessage(
    contract_version="file-processing/v1",
    run_id="run-1",
    source_version_id="version-1",
    profile_hash="337dc23bd405e7225e8ffca06b72852ed19121723bc8b1abeafdc05cf5ceac42",
    attempt=0,
    correlation_id="correlation-1",
)
RUN = ClaimedDocumentRun(
    run_id="run-1",
    tenant_id="tenant-1",
    source_version_id="version-1",
    profile_hash=MESSAGE.profile_hash,
    status="RUNNING",
    attempt=1,
    external_task_id="",
    display_name="sample.pdf",
    media_type="application/pdf",
    format_code="PDF",
    size_bytes=9,
    content_sha256="0" * 64,
)
RESULT = DocumentProcessorResult(
    markdown=b"# output\n",
    docling_json=b'{"pages":{"1":{}},"schema_name":"DoclingDocument"}',
    partial=False,
    no_text=False,
    page_count=1,
    processing_time_ms=1200,
)


class _FileService:
    def __init__(self, run: ClaimedDocumentRun = RUN) -> None:
        self.run = run
        self.calls: list[tuple[str, Any]] = []

    def claim(self, message: FileProcessingTaskMessage) -> ClaimedDocumentRun:
        self.calls.append(("claim", message.run_id))
        return self.run

    def download_source(self, run: ClaimedDocumentRun) -> bytes:
        self.calls.append(("download", run.run_id))
        return b"%PDF-1.7\n"

    def mark_submitted(self, run_id: str, external_task_id: str) -> None:
        self.calls.append(("submitted", (run_id, external_task_id)))

    def upload_representation(self, **values: Any) -> None:
        self.calls.append(("upload", (values["kind"], values["content"])))

    def finalize(self, **values: Any) -> None:
        self.calls.append(("finalize", values))

    def no_text(self, **values: Any) -> None:
        self.calls.append(("no_text", values))

    def retry(self, **values: Any) -> None:
        self.calls.append(("retry", values))

    def fail(self, **values: Any) -> None:
        self.calls.append(("fail", values))


class _Processor:
    def __init__(self) -> None:
        self.poll_states = [ProcessorTaskState.STARTED, ProcessorTaskState.SUCCESS]
        self.submit_failure: DocumentProcessorFailure | None = None
        self.result = RESULT
        self.calls: list[tuple[str, Any]] = []

    def submit(self, **values: Any) -> ProcessorTask:
        self.calls.append(("submit", values["filename"]))
        if self.submit_failure is not None:
            raise self.submit_failure
        return ProcessorTask("task-1", ProcessorTaskState.PENDING)

    def poll(self, task_id: str) -> ProcessorTask:
        self.calls.append(("poll", task_id))
        return ProcessorTask(task_id, self.poll_states.pop(0))

    def fetch(self, task_id: str, **_: Any) -> DocumentProcessorResult:
        self.calls.append(("fetch", task_id))
        return self.result


def _worker(
    files: _FileService,
    processor: _Processor,
    *,
    monotonic=lambda: 0.0,
) -> FileProcessingWorkerService:
    return FileProcessingWorkerService(
        file_service=files,  # type: ignore[arg-type]
        processor=processor,
        poll_interval_seconds=0.1,
        total_timeout_seconds=600,
        max_attempts=3,
        retry_base_seconds=30,
        monotonic=monotonic,
        sleep=lambda _: None,
    )


def test_worker_replays_submit_poll_fetch_stage_and_atomic_finalize() -> None:
    files = _FileService()
    processor = _Processor()
    result = _worker(files, processor)(MESSAGE)

    assert result.disposition is FileProcessingDisposition.ACK
    assert [name for name, _ in processor.calls] == ["submit", "poll", "poll", "fetch"]
    assert [name for name, _ in files.calls] == [
        "claim",
        "download",
        "submitted",
        "upload",
        "upload",
        "finalize",
    ]
    assert files.calls[3][1][0] == "MARKDOWN"
    assert files.calls[4][1][0] == "DOCLING_JSON"


def test_worker_restart_resumes_persisted_external_task_without_resubmission() -> None:
    files = _FileService(replace(RUN, status="SUBMITTED", external_task_id="task-existing"))
    processor = _Processor()
    processor.poll_states = [ProcessorTaskState.SUCCESS]

    result = _worker(files, processor)(replace(MESSAGE, redelivered=True))

    assert result.disposition is FileProcessingDisposition.ACK
    assert ("download", "run-1") not in files.calls
    assert not any(name == "submit" for name, _ in processor.calls)
    assert processor.calls[0] == ("poll", "task-existing")


def test_worker_maps_no_text_without_creating_half_visible_representations() -> None:
    files = _FileService()
    processor = _Processor()
    processor.poll_states = [ProcessorTaskState.SUCCESS]
    processor.result = replace(RESULT, markdown=b"", no_text=True)

    result = _worker(files, processor)(MESSAGE)

    assert result.disposition is FileProcessingDisposition.ACK
    assert any(name == "no_text" for name, _ in files.calls)
    assert not any(name in {"upload", "finalize"} for name, _ in files.calls)


def test_worker_retries_bounded_transient_failure_then_dead_letters_at_attempt_limit() -> None:
    files = _FileService()
    processor = _Processor()
    processor.submit_failure = DocumentProcessorFailure(
        "docling_service_unavailable", retryable=True
    )
    result = _worker(files, processor)(MESSAGE)
    assert result.disposition is FileProcessingDisposition.RETRY
    assert result.delay_seconds == 30
    assert files.calls[-1][0] == "retry"

    exhausted_files = _FileService(replace(RUN, attempt=3))
    exhausted = _worker(exhausted_files, processor)(replace(MESSAGE, attempt=2))
    assert exhausted.disposition is FileProcessingDisposition.DEAD
    assert exhausted.error_code == "docling_service_unavailable"
    assert exhausted_files.calls[-1][0] == "fail"


def test_worker_total_timeout_is_retryable_and_never_logs_or_returns_content() -> None:
    files = _FileService()
    processor = _Processor()
    clock = iter((0.0, 601.0))
    result = _worker(files, processor, monotonic=lambda: next(clock))(MESSAGE)
    assert result.disposition is FileProcessingDisposition.RETRY
    assert result.error_code == "docling_processing_timeout"
    assert "PDF" not in result.error_code


def test_worker_maps_unexpected_failure_to_bounded_retry() -> None:
    files = _FileService()
    processor = _Processor()

    def unexpected(**_: Any) -> ProcessorTask:
        raise RuntimeError("confidential document body")

    processor.submit = unexpected  # type: ignore[method-assign]
    result = _worker(files, processor)(MESSAGE)
    assert result.disposition is FileProcessingDisposition.RETRY
    assert result.error_code == "document_processing_unexpected"
    assert files.calls[-1][0] == "retry"


def test_worker_readiness_requires_fresh_heartbeat_and_every_dependency() -> None:
    ready = document_processing_readiness(
        {"rabbitmq": "ready", "file_service": "ready", "docling": "ready"},
        30,
    )
    assert ready == {
        "status": "ok",
        "ready": True,
        "reason_code": "ready",
        "components": {
            "rabbitmq": "ready",
            "file_service": "ready",
            "docling": "ready",
        },
    }

    docling_down = document_processing_readiness(
        {"rabbitmq": "ready", "file_service": "ready", "docling": "unavailable"},
        30,
    )
    assert docling_down["ready"] is False
    assert docling_down["reason_code"] == "docling_unavailable"

    stale = document_processing_readiness(
        {"rabbitmq": "ready", "file_service": "ready", "docling": "ready"},
        121,
    )
    assert stale["ready"] is False
    assert stale["reason_code"] == "file_processing_worker_heartbeat_stale"
