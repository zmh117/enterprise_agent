from __future__ import annotations

import io
import hashlib
import json
import logging
import secrets
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from app.modules.document_processing.file_service_client import (
    ClaimedDocumentRun,
    ClaimedPictureItem,
    DocumentProcessingFileServiceClient,
)
from app.modules.document_processing.image_normalization import (
    NormalizedPicture,
    normalize_picture_asset,
)
from app.modules.document_processing.layout_ocr import (
    adapt_docling_picture_result,
    append_layout_ocr_markdown,
    assemble_layout_representation,
)
from app.modules.document_processing.profile import (
    DOCLING_LAYOUT_OCR_V1,
    DOCLING_TEXT_V1,
    DocumentProcessingProfile,
    require_document_processing_profile,
)
from app.modules.document_processing.provider import (
    DocumentProcessor,
    DocumentProcessorFailure,
    ProcessorTask,
    ProcessorTaskState,
)
from app.modules.message_bus.application.message_publisher import (
    AssemblyTaskMessage,
    DocumentProcessingStageMessage,
    FileProcessingDisposition,
    FileProcessingTaskMessage,
    FileProcessingTaskResult,
    PictureProcessingTaskMessage,
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
        now: Callable[[], datetime] | None = None,
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
        self.now = now or (lambda: datetime.now(UTC))

    def __call__(self, message: DocumentProcessingStageMessage) -> FileProcessingTaskResult:
        if isinstance(message, PictureProcessingTaskMessage):
            return self._handle_picture(message)
        if isinstance(message, AssemblyTaskMessage):
            return self._handle_assembly(message)
        return self._handle_parent(message)

    def _handle_parent(self, message: FileProcessingTaskMessage) -> FileProcessingTaskResult:
        run: ClaimedDocumentRun | None = None
        started = self.monotonic()
        try:
            run = self.file_service.claim(message)
            if run.terminal:
                return FileProcessingTaskResult(FileProcessingDisposition.ACK)
            profile = require_document_processing_profile(
                run.profile_code, profile_hash=run.profile_hash
            )
            self._require_run_not_expired(run.run_deadline_at, profile=profile)
            task = self._submit_or_resume(run, profile=profile)
            parent_timeout = self.total_timeout_seconds
            if profile.layout_ocr_options is not None:
                parent_timeout = int(
                    profile.layout_ocr_options["limits"]["parent_deadline_seconds"]
                )
            task = self._poll_until_terminal(
                task,
                started=started,
                timeout_seconds=parent_timeout,
            )
            self._require_run_not_expired(run.run_deadline_at, profile=profile)
            if task.state is ProcessorTaskState.FAILURE:
                raise DocumentProcessorFailure("docling_conversion_failed", retryable=False)
            if profile.profile_hash == DOCLING_LAYOUT_OCR_V1.profile_hash:
                self._complete_layout_parent(
                    run=run,
                    profile=profile,
                    task=task,
                    correlation_id=message.correlation_id,
                )
                return FileProcessingTaskResult(FileProcessingDisposition.ACK)
            result = self.processor.fetch(task.task_id, profile=profile)
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

    def _submit_or_resume(
        self,
        run: ClaimedDocumentRun,
        *,
        profile: DocumentProcessingProfile,
    ) -> ProcessorTask:
        if run.external_task_id:
            return self.processor.poll(run.external_task_id)
        source = self.file_service.download_source(run)
        task = self.processor.submit(
            stream=io.BytesIO(source),
            filename=run.display_name,
            media_type=run.media_type,
            format_code=run.format_code,
            profile=profile,
        )
        self.file_service.mark_submitted(run.run_id, task.task_id)
        return task

    def _complete_layout_parent(
        self,
        *,
        run: ClaimedDocumentRun,
        profile: DocumentProcessingProfile,
        task: ProcessorTask,
        correlation_id: str,
    ) -> None:
        if run.format_code in {"DOCX", "PPTX"}:
            parent = self.processor.fetch_bundle(
                task.task_id,
                profile=profile,
                source_format=run.format_code,
            )
            pictures = parent.pictures
        else:
            parent = self.processor.fetch_picture(task.task_id, profile=profile)
            pictures = ()
        parent_markdown = parent.markdown
        if not parent_markdown.strip():
            parent_markdown = "# 文档正文\n\n（未提取到父文档文字。）\n".encode()
        layout_options = profile.layout_ocr_options
        if layout_options is None:
            raise DocumentProcessorFailure("document_profile_mismatch", retryable=False)
        limits = layout_options["limits"]
        if len(pictures) > int(limits["hard_picture_occurrences"]):
            raise DocumentProcessorFailure(
                "docling_picture_occurrence_limit_exceeded", retryable=False
            )
        self.file_service.upload_parent_artifact(
            run_id=run.run_id,
            content=parent_markdown,
        )
        self.file_service.upload_representation(
            run_id=run.run_id,
            kind="DOCLING_JSON",
            content=parent.docling_json,
            media_type="application/json",
        )
        used_pixels = 0
        used_derived_bytes = len(parent_markdown) + len(parent.docling_json)
        assets: dict[str, dict[str, object]] = {}
        for artifact in pictures:
            selected = artifact.occurrence_index <= int(
                limits["soft_picture_occurrences"]
            )
            normalized = normalize_picture_asset(
                artifact.content,
                declared_media_type=artifact.media_type,
                profile=profile,
                used_total_pixels=used_pixels,
                used_derived_bytes=used_derived_bytes,
            )
            used_pixels += normalized.original_width_pixels * normalized.original_height_pixels
            used_derived_bytes += len(normalized.content)
            asset_id = self.file_service.upload_picture_asset(
                run_id=run.run_id,
                content=normalized.content,
                media_type=normalized.media_type,
                original_width_pixels=normalized.original_width_pixels,
                original_height_pixels=normalized.original_height_pixels,
                width_pixels=normalized.width_pixels,
                height_pixels=normalized.height_pixels,
                normalization_transform=dict(normalized.transform),
                content_sha256=normalized.content_sha256,
            )
            self.file_service.register_picture_occurrence(
                run_id=run.run_id,
                picture_asset_id=asset_id,
                occurrence_index=artifact.occurrence_index,
                source_format=run.format_code,
                picture_ref=artifact.picture_ref,
                parent_ref=artifact.parent_ref,
                parent_label=artifact.parent_label,
                parent_ordinal=artifact.parent_ordinal,
                slide_no=artifact.slide_no,
                parent_bbox=artifact.parent_bbox,
                selection_status=("SELECTED" if selected else "SKIPPED_LIMIT"),
            )
            entry = assets.setdefault(
                normalized.content_sha256,
                {
                    "asset_id": asset_id,
                    "count": 0,
                    "selected": False,
                },
            )
            entry["count"] = int(entry["count"]) + 1
            if selected:
                entry["selected"] = True
        model = layout_options["model_artifact"]
        for entry in assets.values():
            item_id = self.file_service.register_picture_item(
                run_id=run.run_id,
                picture_asset_id=str(entry["asset_id"]),
                occurrence_count=int(entry["count"]),
                ocr_engine_code="docling-rapidocr",
                model_revision=str(model["revision"]),
                model_digest=str(model["digest"]),
                correlation_id=correlation_id,
            )
            if not bool(entry["selected"]):
                self.file_service.complete_picture_item(
                    picture_item_id=item_id,
                    status="SKIPPED_LIMIT",
                    result_size_bytes=None,
                    result_sha256="",
                    error_code="picture_soft_limit",
                    correlation_id=correlation_id,
                )
        self.file_service.complete_parent_parse(
            run_id=run.run_id,
            correlation_id=correlation_id,
        )

    def _handle_picture(
        self, message: PictureProcessingTaskMessage
    ) -> FileProcessingTaskResult:
        item: ClaimedPictureItem | None = None
        started = self.monotonic()
        try:
            item = self.file_service.claim_picture_item(
                picture_item_id=message.picture_item_id,
                claim_token=secrets.token_urlsafe(24),
                claim_expires_at=(self.now() + timedelta(seconds=120)).isoformat(),
                expected_run_id=message.run_id,
                expected_profile_hash=message.profile_hash,
            )
            if item.terminal:
                return FileProcessingTaskResult(FileProcessingDisposition.ACK)
            if item.profile_hash != DOCLING_LAYOUT_OCR_V1.profile_hash:
                raise DocumentProcessorFailure("document_profile_mismatch", retryable=False)
            self._require_run_not_expired(
                item.run_deadline_at,
                profile=DOCLING_LAYOUT_OCR_V1,
            )
            if item.external_task_id:
                task = self.processor.poll(item.external_task_id)
            else:
                content = self.file_service.download_picture_asset(item)
                task = self.processor.submit_picture(
                    stream=io.BytesIO(content),
                    media_type=item.media_type,
                    profile=DOCLING_LAYOUT_OCR_V1,
                )
                self.file_service.mark_picture_submitted(
                    picture_item_id=item.picture_item_id,
                    external_task_id=task.task_id,
                )
            task = self._poll_until_terminal(
                task,
                started=started,
                timeout_seconds=int(
                    DOCLING_LAYOUT_OCR_V1.layout_ocr_options["limits"][
                        "picture_attempt_deadline_seconds"
                    ]
                ),
            )
            self._require_run_not_expired(
                item.run_deadline_at,
                profile=DOCLING_LAYOUT_OCR_V1,
            )
            if task.state is ProcessorTaskState.FAILURE:
                raise DocumentProcessorFailure("docling_conversion_failed", retryable=False)
            result = self.processor.fetch_picture(
                task.task_id,
                profile=DOCLING_LAYOUT_OCR_V1,
            )
            transform = dict(item.normalization_transform)
            normalized = NormalizedPicture(
                content=b"",
                media_type=item.media_type,
                content_sha256=item.content_sha256,
                original_width_pixels=item.original_width_pixels,
                original_height_pixels=item.original_height_pixels,
                width_pixels=item.width_pixels,
                height_pixels=item.height_pixels,
                exif_orientation=int(transform["exif_orientation"]),
                transform=transform,
            )
            picture_result = adapt_docling_picture_result(
                result.docling_json,
                picture=normalized,
                profile=DOCLING_LAYOUT_OCR_V1,
            )
            parsed = json.loads(picture_result)
            status = str(parsed["status"])
            if status in {"AVAILABLE", "NO_TEXT"}:
                self.file_service.upload_picture_result(
                    picture_item_id=item.picture_item_id,
                    content=picture_result,
                )
            self.file_service.complete_picture_item(
                picture_item_id=item.picture_item_id,
                status=status,
                result_size_bytes=len(picture_result),
                result_sha256=hashlib.sha256(picture_result).hexdigest(),
                error_code="",
                correlation_id=message.correlation_id,
            )
            return FileProcessingTaskResult(FileProcessingDisposition.ACK)
        except DocumentProcessorFailure as exc:
            return self._picture_failure(item, message, exc.error_code, retryable=exc.retryable)
        except RetryableExecutionError as exc:
            return self._picture_failure(
                item,
                message,
                exc.error_code or "document_picture_dependency_unavailable",
                retryable=True,
            )
        except NonRetryableExecutionError as exc:
            return self._picture_failure(
                item,
                message,
                exc.error_code or "document_picture_denied",
                retryable=False,
            )
        except Exception as exc:
            logger.error(
                "Unexpected picture processing failure item_id=%s error_class=%s",
                message.picture_item_id,
                type(exc).__name__[:128],
            )
            return self._picture_failure(
                item,
                message,
                "document_picture_unexpected",
                retryable=True,
            )

    def _handle_assembly(self, message: AssemblyTaskMessage) -> FileProcessingTaskResult:
        claimed = False
        started = self.monotonic()
        try:
            claim = self.file_service.claim_assembly(
                run_id=message.run_id,
                profile_hash=message.profile_hash,
                claim_token=secrets.token_urlsafe(24),
            )
            claimed = bool(claim["claimed"])
            if not claimed:
                if str(claim["assembly_status"]) == "COMPLETED":
                    return FileProcessingTaskResult(FileProcessingDisposition.ACK)
                return FileProcessingTaskResult(
                    FileProcessingDisposition.RETRY,
                    error_code="document_assembly_not_claimed",
                    delay_seconds=self.retry_base_seconds,
                )
            context = self.file_service.assembly_context(
                run_id=message.run_id,
                profile_hash=message.profile_hash,
            )
            self._require_run_not_expired(
                str(context["run_deadline_at"]),
                profile=DOCLING_LAYOUT_OCR_V1,
            )
            assembly_timeout = int(
                DOCLING_LAYOUT_OCR_V1.layout_ocr_options["limits"][
                    "assembly_deadline_seconds"
                ]
            )
            occurrence_values: list[dict[str, object]] = []
            result_cache: dict[str, bytes] = {}
            maximum_result = int(
                DOCLING_LAYOUT_OCR_V1.layout_ocr_options["limits"][
                    "max_ocr_layout_json_bytes"
                ]
            )
            for occurrence in context["occurrences"]:
                if not isinstance(occurrence, dict):
                    raise DocumentProcessorFailure(
                        "document_assembly_context_invalid", retryable=False
                    )
                item_id = str(occurrence["picture_item_id"])
                status = str(occurrence["status"])
                result: bytes | None = None
                if status in {"AVAILABLE", "NO_TEXT"}:
                    if item_id not in result_cache:
                        result_cache[item_id] = self.file_service.download_picture_result(
                            picture_item_id=item_id,
                            maximum_bytes=maximum_result,
                        )
                    result = result_cache[item_id]
                occurrence_values.append({**occurrence, "result": result})
            layout = assemble_layout_representation(
                source_file_id=str(context["source_file_id"]),
                source_version_id=str(context["source_version_id"]),
                run_id=message.run_id,
                profile=DOCLING_LAYOUT_OCR_V1,
                occurrences=occurrence_values,
            )
            self._require_stage_not_expired(
                started,
                timeout_seconds=assembly_timeout,
                error_code="document_assembly_timeout",
            )
            parent = self.file_service.download_parent_artifact(
                run_id=message.run_id,
                maximum_bytes=DOCLING_LAYOUT_OCR_V1.max_markdown_bytes,
            )
            markdown = append_layout_ocr_markdown(parent, layout)
            self._require_stage_not_expired(
                started,
                timeout_seconds=assembly_timeout,
                error_code="document_assembly_timeout",
            )
            self.file_service.upload_representation(
                run_id=message.run_id,
                kind="MARKDOWN",
                content=markdown,
                media_type="text/markdown",
            )
            self.file_service.upload_representation(
                run_id=message.run_id,
                kind="OCR_LAYOUT_JSON",
                content=layout,
                media_type="application/json",
            )
            partial = any(
                str(item["status"]) in {"SKIPPED_LIMIT", "FAILED"}
                for item in context["occurrences"]
                if isinstance(item, dict)
            )
            self.file_service.finalize(
                run_id=message.run_id,
                partial=partial,
                page_count=None,
                processing_time_ms=None,
            )
            self.file_service.finish_assembly(run_id=message.run_id, succeeded=True)
            return FileProcessingTaskResult(FileProcessingDisposition.ACK)
        except (DocumentProcessorFailure, NonRetryableExecutionError) as exc:
            code = getattr(exc, "error_code", None) or "document_assembly_invalid"
            if claimed:
                self.file_service.finish_assembly(run_id=message.run_id, succeeded=False)
                self.file_service.fail(run_id=message.run_id, error_code=code)
            return FileProcessingTaskResult(FileProcessingDisposition.DEAD, error_code=code)
        except Exception as exc:
            logger.error(
                "Unexpected document assembly failure run_id=%s error_class=%s",
                message.run_id,
                type(exc).__name__[:128],
            )
            if claimed:
                try:
                    self.file_service.retry_assembly(run_id=message.run_id)
                except Exception:
                    logger.warning("Assembly retry state update deferred run_id=%s", message.run_id)
            return FileProcessingTaskResult(
                FileProcessingDisposition.RETRY,
                error_code="document_assembly_dependency_unavailable",
                delay_seconds=self.retry_base_seconds,
            )

    def _picture_failure(
        self,
        item: ClaimedPictureItem | None,
        message: PictureProcessingTaskMessage,
        error_code: str,
        *,
        retryable: bool,
    ) -> FileProcessingTaskResult:
        safe_code = _safe_error_code(error_code)
        attempt = item.attempt if item is not None else message.attempt + 1
        if retryable and attempt < int(
            DOCLING_LAYOUT_OCR_V1.layout_ocr_options["limits"]["max_picture_attempts"]
        ):
            delay = min(self.retry_base_seconds * (2 ** max(attempt - 1, 0)), 120)
            try:
                self.file_service.retry_picture_item(
                    picture_item_id=message.picture_item_id,
                    error_code=safe_code,
                    delay_seconds=delay,
                )
            except RetryableExecutionError:
                logger.warning(
                    "Picture retry state update deferred item_id=%s error_code=%s",
                    message.picture_item_id,
                    safe_code,
                )
            return FileProcessingTaskResult(
                FileProcessingDisposition.RETRY,
                error_code=safe_code,
                delay_seconds=delay,
            )
        try:
            self.file_service.complete_picture_item(
                picture_item_id=message.picture_item_id,
                status="FAILED",
                result_size_bytes=None,
                result_sha256="",
                error_code=safe_code,
                correlation_id=message.correlation_id,
            )
        except RetryableExecutionError:
            logger.warning(
                "Picture terminal state update deferred item_id=%s error_code=%s",
                message.picture_item_id,
                safe_code,
            )
            return FileProcessingTaskResult(
                FileProcessingDisposition.RETRY,
                error_code=safe_code,
                delay_seconds=self.retry_base_seconds,
            )
        return FileProcessingTaskResult(FileProcessingDisposition.ACK)

    def _poll_until_terminal(
        self,
        task: ProcessorTask,
        *,
        started: float,
        timeout_seconds: int,
    ) -> ProcessorTask:
        current = task
        while current.state not in {
            ProcessorTaskState.SUCCESS,
            ProcessorTaskState.FAILURE,
        }:
            if self.monotonic() - started >= timeout_seconds:
                raise DocumentProcessorFailure("docling_processing_timeout", retryable=True)
            self.sleep(self.poll_interval_seconds)
            current = self.processor.poll(current.task_id)
        return current

    def _require_run_not_expired(
        self,
        value: str,
        *,
        profile: DocumentProcessingProfile,
    ) -> None:
        if profile.layout_ocr_options is None:
            return
        try:
            deadline = datetime.fromisoformat(value)
        except ValueError as exc:
            raise DocumentProcessorFailure(
                "document_run_deadline_invalid", retryable=False
            ) from exc
        if deadline.tzinfo is None:
            raise DocumentProcessorFailure("document_run_deadline_invalid", retryable=False)
        if self.now() >= deadline:
            raise DocumentProcessorFailure(
                "document_processing_run_deadline_exceeded", retryable=False
            )

    def _require_stage_not_expired(
        self,
        started: float,
        *,
        timeout_seconds: int,
        error_code: str,
    ) -> None:
        if self.monotonic() - started >= timeout_seconds:
            raise DocumentProcessorFailure(error_code, retryable=False)

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
