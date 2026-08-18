from __future__ import annotations

import io
import logging
import time
from collections.abc import Callable

from app.modules.document_processing.file_service_client import (
    ClaimedDocumentRun,
    DocumentProcessingFileServiceClient,
)
from app.modules.document_processing.profile import DOCLING_TEXT_V1
from app.modules.document_processing.provider import (
    DocumentProcessor,
    DocumentProcessorFailure,
    ProcessorTask,
    ProcessorTaskState,
)
from app.modules.message_bus.application.message_publisher import (
    FileProcessingDisposition,
    FileProcessingTaskMessage,
    FileProcessingTaskResult,
)
from app.shared.exceptions import NonRetryableExecutionError, RetryableExecutionError


logger = logging.getLogger(__name__)


class FileProcessingWorkerService:
    def __init__(
        self,
        *,
        file_service: DocumentProcessingFileServiceClient,
        processor: DocumentProcessor,
        poll_interval_seconds: float,
        total_timeout_seconds: int,
        max_attempts: int,
        retry_base_seconds: int,
        monotonic: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        if not 0.1 <= poll_interval_seconds <= 30:
            raise ValueError("File processing poll interval is invalid")
        if not 1 <= total_timeout_seconds <= DOCLING_TEXT_V1.processing_timeout_seconds:
            raise ValueError("File processing total timeout is invalid")
        if max_attempts != DOCLING_TEXT_V1.max_attempts:
            raise ValueError("File processing max attempts must match the frozen profile")
        if not 1 <= retry_base_seconds <= total_timeout_seconds:
            raise ValueError("File processing retry base is invalid")
        self.file_service = file_service
        self.processor = processor
        self.poll_interval_seconds = poll_interval_seconds
        self.total_timeout_seconds = total_timeout_seconds
        self.max_attempts = max_attempts
        self.retry_base_seconds = retry_base_seconds
        self.monotonic = monotonic or time.monotonic
        self.sleep = sleep or time.sleep

    def __call__(self, message: FileProcessingTaskMessage) -> FileProcessingTaskResult:
        run: ClaimedDocumentRun | None = None
        started = self.monotonic()
        try:
            run = self.file_service.claim(message)
            if run.terminal:
                return FileProcessingTaskResult(FileProcessingDisposition.ACK)
            if run.profile_hash != DOCLING_TEXT_V1.profile_hash:
                raise DocumentProcessorFailure("document_profile_mismatch", retryable=False)
            task = self._submit_or_resume(run)
            task = self._poll_until_terminal(task, started=started)
            if task.state is ProcessorTaskState.FAILURE:
                raise DocumentProcessorFailure("docling_conversion_failed", retryable=False)
            result = self.processor.fetch(task.task_id, profile=DOCLING_TEXT_V1)
            if result.no_text:
                self.file_service.no_text(
                    run_id=run.run_id,
                    page_count=result.page_count,
                    processing_time_ms=result.processing_time_ms,
                )
                return FileProcessingTaskResult(FileProcessingDisposition.ACK)
            self.file_service.upload_representation(
                run_id=run.run_id,
                kind="MARKDOWN",
                content=result.markdown,
                media_type="text/markdown",
            )
            self.file_service.upload_representation(
                run_id=run.run_id,
                kind="DOCLING_JSON",
                content=result.docling_json,
                media_type="application/json",
            )
            self.file_service.finalize(
                run_id=run.run_id,
                partial=result.partial,
                page_count=result.page_count,
                processing_time_ms=result.processing_time_ms,
            )
            return FileProcessingTaskResult(FileProcessingDisposition.ACK)
        except DocumentProcessorFailure as exc:
            return self._failure(run, message, exc.error_code, retryable=exc.retryable)
        except RetryableExecutionError as exc:
            return self._failure(
                run,
                message,
                exc.error_code or "document_processing_dependency_unavailable",
                retryable=True,
            )
        except NonRetryableExecutionError as exc:
            return self._failure(
                run,
                message,
                exc.error_code or "document_processing_denied",
                retryable=False,
            )
        except Exception as exc:
            logger.error(
                "Unexpected file processing failure run_id=%s error_class=%s",
                run.run_id if run is not None else message.run_id,
                type(exc).__name__[:128],
            )
            return self._failure(
                run,
                message,
                "document_processing_unexpected",
                retryable=True,
            )

    def _submit_or_resume(self, run: ClaimedDocumentRun) -> ProcessorTask:
        if run.external_task_id:
            return self.processor.poll(run.external_task_id)
        source = self.file_service.download_source(run)
        task = self.processor.submit(
            stream=io.BytesIO(source),
            filename=run.display_name,
            media_type=run.media_type,
            format_code=run.format_code,
            profile=DOCLING_TEXT_V1,
        )
        self.file_service.mark_submitted(run.run_id, task.task_id)
        return task

    def _poll_until_terminal(self, task: ProcessorTask, *, started: float) -> ProcessorTask:
        current = task
        while current.state not in {
            ProcessorTaskState.SUCCESS,
            ProcessorTaskState.FAILURE,
        }:
            if self.monotonic() - started >= self.total_timeout_seconds:
                raise DocumentProcessorFailure("docling_processing_timeout", retryable=True)
            self.sleep(self.poll_interval_seconds)
            current = self.processor.poll(current.task_id)
        return current

    def _failure(
        self,
        run: ClaimedDocumentRun | None,
        message: FileProcessingTaskMessage,
        error_code: str,
        *,
        retryable: bool,
    ) -> FileProcessingTaskResult:
        safe_code = _safe_error_code(error_code)
        attempt = run.attempt if run is not None else message.attempt + 1
        run_id = run.run_id if run is not None else message.run_id
        if retryable and attempt < self.max_attempts:
            delay = min(
                self.retry_base_seconds * (2 ** max(attempt - 1, 0)),
                DOCLING_TEXT_V1.processing_timeout_seconds,
            )
            try:
                self.file_service.retry(
                    run_id=run_id,
                    error_code=safe_code,
                    delay_seconds=delay,
                )
            except RetryableExecutionError:
                logger.warning(
                    "File processing retry state update deferred run_id=%s error_code=%s",
                    run_id,
                    safe_code,
                )
            return FileProcessingTaskResult(
                FileProcessingDisposition.RETRY,
                error_code=safe_code,
                delay_seconds=delay,
            )
        try:
            self.file_service.fail(run_id=run_id, error_code=safe_code)
        except RetryableExecutionError:
            logger.warning(
                "File processing terminal state update deferred run_id=%s error_code=%s",
                run_id,
                safe_code,
            )
        return FileProcessingTaskResult(
            FileProcessingDisposition.DEAD,
            error_code=safe_code,
        )


def _safe_error_code(value: str) -> str:
    normalized = str(value or "document_processing_failed")[:128]
    if not normalized.replace("_", "").isalnum():
        return "document_processing_failed"
    return normalized
