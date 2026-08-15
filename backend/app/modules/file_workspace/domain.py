from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.shared.exceptions import NonRetryableExecutionError


class RetentionPeriod(StrEnum):
    DAY = "DAY"
    WEEK = "WEEK"
    MONTH = "MONTH"


class WorkspaceOwnerType(StrEnum):
    PRIVATE_USER = "PRIVATE_USER"
    GROUP_CONVERSATION = "GROUP_CONVERSATION"


class WorkspaceStatus(StrEnum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    EXPIRED = "EXPIRED"
    CLEANING = "CLEANING"
    CLEANED = "CLEANED"


class ManagedFileStatus(StrEnum):
    ACTIVE = "ACTIVE"
    CONTENT_UNAVAILABLE = "CONTENT_UNAVAILABLE"
    DELETED = "DELETED"


class FileVersionKind(StrEnum):
    ATTACHMENT = "ATTACHMENT"
    WORKING = "WORKING"
    OUTPUT = "OUTPUT"
    CONFLICT = "CONFLICT"


class FileVersionStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    CONFLICT = "CONFLICT"
    CONTENT_UNAVAILABLE = "CONTENT_UNAVAILABLE"
    DELETED = "DELETED"


class FileSourceKind(StrEnum):
    MESSAGE_ATTACHMENT = "MESSAGE_ATTACHMENT"
    AGENT_GENERATED = "AGENT_GENERATED"
    AGENT_EDITED = "AGENT_EDITED"
    CONFLICT = "CONFLICT"


class WorkspaceFileRole(StrEnum):
    INPUT = "INPUT"
    WORKING = "WORKING"
    OUTPUT = "OUTPUT"
    CONFLICT = "CONFLICT"


class WorkspaceFileStatus(StrEnum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class SnapshotSourceKind(StrEnum):
    CURRENT_MESSAGE = "CURRENT_MESSAGE"
    EXPLICIT_REFERENCE = "EXPLICIT_REFERENCE"
    WORKSPACE = "WORKSPACE"
    CONFLICT = "CONFLICT"


class FileAction(StrEnum):
    READ_METADATA = "READ_METADATA"
    MATERIALIZE = "MATERIALIZE"
    EDIT = "EDIT"
    COMMIT = "COMMIT"
    RETAIN = "RETAIN"
    DELIVER = "DELIVER"


class CommitUserIntent(StrEnum):
    MODIFY = "MODIFY"
    GENERATE = "GENERATE"
    SAVE = "SAVE"


class CommitDeliveryMode(StrEnum):
    DEFAULT = "DEFAULT"
    WORKSPACE_ONLY = "WORKSPACE_ONLY"


class CommitIntentStatus(StrEnum):
    INTENT = "INTENT"
    UPLOADING = "UPLOADING"
    COMMITTED = "COMMITTED"
    CONFLICT = "CONFLICT"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class StagingStatus(StrEnum):
    UPLOADING = "UPLOADING"
    COMPLETE = "COMPLETE"
    PUBLISHED = "PUBLISHED"
    CLEANUP_PENDING = "CLEANUP_PENDING"
    DELETED = "DELETED"


class ConflictStatus(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    EXPIRED = "EXPIRED"


class RetentionReason(StrEnum):
    MESSAGE_ATTACHMENT = "MESSAGE_ATTACHMENT"
    USER_SAVED = "USER_SAVED"
    DELIVERED = "DELIVERED"


class CleanupResourceType(StrEnum):
    WORKSPACE = "WORKSPACE"
    FILE_VERSION = "FILE_VERSION"
    STAGING_OBJECT = "STAGING_OBJECT"
    ATTACHMENT_CONTENT = "ATTACHMENT_CONTENT"


class CleanupStatus(StrEnum):
    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    RETRY = "RETRY"
    COMPLETED = "COMPLETED"
    DEAD = "DEAD"


WORKSPACE_TRANSITIONS: dict[WorkspaceStatus, frozenset[WorkspaceStatus]] = {
    WorkspaceStatus.ACTIVE: frozenset({WorkspaceStatus.CLOSED, WorkspaceStatus.EXPIRED}),
    WorkspaceStatus.CLOSED: frozenset({WorkspaceStatus.CLEANING}),
    WorkspaceStatus.EXPIRED: frozenset({WorkspaceStatus.CLEANING}),
    WorkspaceStatus.CLEANING: frozenset({WorkspaceStatus.CLEANED}),
    WorkspaceStatus.CLEANED: frozenset(),
}

COMMIT_TRANSITIONS: dict[CommitIntentStatus, frozenset[CommitIntentStatus]] = {
    CommitIntentStatus.INTENT: frozenset(
        {CommitIntentStatus.UPLOADING, CommitIntentStatus.REJECTED, CommitIntentStatus.EXPIRED}
    ),
    CommitIntentStatus.UPLOADING: frozenset(
        {
            CommitIntentStatus.COMMITTED,
            CommitIntentStatus.CONFLICT,
            CommitIntentStatus.REJECTED,
            CommitIntentStatus.EXPIRED,
        }
    ),
    CommitIntentStatus.COMMITTED: frozenset(),
    CommitIntentStatus.CONFLICT: frozenset(),
    CommitIntentStatus.REJECTED: frozenset(),
    CommitIntentStatus.EXPIRED: frozenset(),
}

CLEANUP_TRANSITIONS: dict[CleanupStatus, frozenset[CleanupStatus]] = {
    CleanupStatus.PENDING: frozenset({CleanupStatus.CLAIMED}),
    CleanupStatus.RETRY: frozenset({CleanupStatus.CLAIMED}),
    CleanupStatus.CLAIMED: frozenset(
        {CleanupStatus.RETRY, CleanupStatus.COMPLETED, CleanupStatus.DEAD}
    ),
    CleanupStatus.COMPLETED: frozenset(),
    CleanupStatus.DEAD: frozenset(),
}


@dataclass(frozen=True)
class FileOwner:
    owner_type: WorkspaceOwnerType
    user_id: str = ""
    enterprise_id: str = ""
    connector_id: str = ""
    conversation_id: str = ""

    def __post_init__(self) -> None:
        private_valid = self.owner_type is WorkspaceOwnerType.PRIVATE_USER and bool(
            self.user_id
        ) and not any((self.enterprise_id, self.connector_id, self.conversation_id))
        group_valid = self.owner_type is WorkspaceOwnerType.GROUP_CONVERSATION and not self.user_id and all(
            (self.enterprise_id, self.connector_id, self.conversation_id)
        )
        if not (private_valid or group_valid):
            raise NonRetryableExecutionError(
                "Invalid task file owner boundary",
                safe_message="文件归属边界无效",
                error_code="file_owner_invalid",
            )

    def database_values(self) -> tuple[str, str, str, str, str]:
        return (
            self.owner_type.value,
            self.user_id,
            self.enterprise_id,
            self.connector_id,
            self.conversation_id,
        )


def ensure_transition[State: StrEnum](
    *,
    current: State,
    target: State,
    transitions: dict[State, frozenset[State]],
) -> None:
    if target not in transitions[current]:
        raise NonRetryableExecutionError(
            f"Invalid state transition: {current.value} -> {target.value}",
            safe_message="资源状态已变化，请刷新后重试",
            error_code="file_state_conflict",
        )
