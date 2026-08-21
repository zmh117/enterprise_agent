from __future__ import annotations

from enum import StrEnum
import json

from app.shared.exceptions import NonRetryableExecutionError


class ProcessingRunStatus(StrEnum):
    QUEUED = "QUEUED"
    SUBMITTED = "SUBMITTED"
    RUNNING = "RUNNING"
    RETRY_WAIT = "RETRY_WAIT"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    NO_TEXT = "NO_TEXT"
    FAILED = "FAILED"


class RepresentationKind(StrEnum):
    MARKDOWN = "MARKDOWN"
    DOCLING_JSON = "DOCLING_JSON"
    OCR_LAYOUT_JSON = "OCR_LAYOUT_JSON"


class ProcessingStageCode(StrEnum):
    PARENT_PARSE = "PARENT_PARSE"
    PICTURE_OCR = "PICTURE_OCR"
    ASSEMBLING = "ASSEMBLING"


class PictureItemStatus(StrEnum):
    QUEUED = "QUEUED"
    CLAIMED = "CLAIMED"
    SUBMITTED = "SUBMITTED"
    RETRY_WAIT = "RETRY_WAIT"
    AVAILABLE = "AVAILABLE"
    NO_TEXT = "NO_TEXT"
    SKIPPED_LIMIT = "SKIPPED_LIMIT"
    FAILED = "FAILED"


PICTURE_ITEM_TERMINAL_STATUSES = frozenset(
    {
        PictureItemStatus.AVAILABLE,
        PictureItemStatus.NO_TEXT,
        PictureItemStatus.SKIPPED_LIMIT,
        PictureItemStatus.FAILED,
    }
)


class RepresentationStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    CONTENT_UNAVAILABLE = "CONTENT_UNAVAILABLE"
    DELETED = "DELETED"


class RepresentationTransferStatus(StrEnum):
    OPEN = "OPEN"
    UPLOADING = "UPLOADING"
    STAGED = "STAGED"
    FINALIZED = "FINALIZED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"


PROCESSING_RUN_TRANSITIONS = {
    ProcessingRunStatus.QUEUED: frozenset(
        {
            ProcessingRunStatus.SUBMITTED,
            ProcessingRunStatus.RUNNING,
            ProcessingRunStatus.FAILED,
        }
    ),
    # The worker keeps a run SUBMITTED while it polls the processor and streams the
    # resulting representations, so every terminal state is reachable from here.
    ProcessingRunStatus.SUBMITTED: frozenset(
        {
            ProcessingRunStatus.RUNNING,
            ProcessingRunStatus.RETRY_WAIT,
            ProcessingRunStatus.SUCCEEDED,
            ProcessingRunStatus.PARTIAL,
            ProcessingRunStatus.NO_TEXT,
            ProcessingRunStatus.FAILED,
        }
    ),
    ProcessingRunStatus.RUNNING: frozenset(
        {
            ProcessingRunStatus.SUBMITTED,
            ProcessingRunStatus.RETRY_WAIT,
            ProcessingRunStatus.SUCCEEDED,
            ProcessingRunStatus.PARTIAL,
            ProcessingRunStatus.NO_TEXT,
            ProcessingRunStatus.FAILED,
        }
    ),
    ProcessingRunStatus.RETRY_WAIT: frozenset(
        {
            ProcessingRunStatus.SUBMITTED,
            ProcessingRunStatus.RUNNING,
            ProcessingRunStatus.FAILED,
        }
    ),
    ProcessingRunStatus.SUCCEEDED: frozenset(),
    ProcessingRunStatus.PARTIAL: frozenset(),
    ProcessingRunStatus.NO_TEXT: frozenset(),
    ProcessingRunStatus.FAILED: frozenset(),
}

PROCESSING_TERMINAL_STATUSES = frozenset(
    {
        ProcessingRunStatus.SUCCEEDED,
        ProcessingRunStatus.PARTIAL,
        ProcessingRunStatus.NO_TEXT,
        ProcessingRunStatus.FAILED,
    }
)

REPRESENTATION_MEDIA_TYPES = {
    RepresentationKind.MARKDOWN: "text/markdown",
    RepresentationKind.DOCLING_JSON: "application/json",
    RepresentationKind.OCR_LAYOUT_JSON: "application/json",
}


def require_processing_transition(
    current: str | ProcessingRunStatus,
    target: str | ProcessingRunStatus,
) -> None:
    current_status = ProcessingRunStatus(str(current))
    target_status = ProcessingRunStatus(str(target))
    if target_status not in PROCESSING_RUN_TRANSITIONS[current_status]:
        raise NonRetryableExecutionError(
            f"Invalid document processing transition: {current_status} -> {target_status}",
            safe_message="文档处理状态已变化，请刷新后重试",
            error_code="document_processing_state_conflict",
        )


def normalize_representation_kind(value: object) -> RepresentationKind:
    try:
        return RepresentationKind(str(value))
    except ValueError as exc:
        raise NonRetryableExecutionError(
            "Unsupported document representation kind",
            safe_message="文档派生表示类型无效",
            error_code="document_representation_kind_invalid",
        ) from exc


def decode_required_representation_kinds(value: object) -> tuple[RepresentationKind, ...]:
    try:
        decoded = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise NonRetryableExecutionError(
            "Invalid frozen document representation set",
            safe_message="文档派生表示集合无效",
            error_code="document_representation_set_invalid",
        ) from exc
    if not isinstance(decoded, list) or not decoded or any(
        not isinstance(item, str) for item in decoded
    ):
        raise NonRetryableExecutionError(
            "Invalid frozen document representation set",
            safe_message="文档派生表示集合无效",
            error_code="document_representation_set_invalid",
        )
    try:
        kinds = tuple(RepresentationKind(item) for item in decoded)
    except ValueError as exc:
        raise NonRetryableExecutionError(
            "Unknown frozen document representation kind",
            safe_message="文档派生表示集合无效",
            error_code="document_representation_set_invalid",
        ) from exc
    if len(set(kinds)) != len(kinds):
        raise NonRetryableExecutionError(
            "Duplicate frozen document representation kind",
            safe_message="文档派生表示集合无效",
            error_code="document_representation_set_invalid",
        )
    return kinds
