from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CandidateIdentityState(StrEnum):
    WAITING_BIND = "waiting_bind"
    RESTORE_REQUIRED = "restore_required"
    HIDDEN = "hidden"


class ConversationScope(StrEnum):
    DIRECT = "direct"
    GROUP = "group"
    BOTH = "both"


@dataclass(frozen=True)
class PendingDingTalkIdentityObservation:
    tenant_code: str
    external_subject_id: str
    display_name: str
    connector_id: str
    robot_code: str
    conversation_type: str
    conversation_id: str
    message_kind: str
    safe_text: str
    text_truncated: bool
    attachment_type: str
    attachment_name: str
    attachment_size: int | None
    occurred_at: str | None

    def with_source(
        self,
        *,
        source_ingress_event_id: str,
        received_at: str,
    ) -> DingTalkIdentityObservation:
        return DingTalkIdentityObservation(
            source_ingress_event_id=source_ingress_event_id,
            received_at=received_at,
            occurred_at=self.occurred_at or received_at,
            tenant_code=self.tenant_code,
            external_subject_id=self.external_subject_id,
            display_name=self.display_name,
            connector_id=self.connector_id,
            robot_code=self.robot_code,
            conversation_type=self.conversation_type,
            conversation_id=self.conversation_id,
            message_kind=self.message_kind,
            safe_text=self.safe_text,
            text_truncated=self.text_truncated,
            attachment_type=self.attachment_type,
            attachment_name=self.attachment_name,
            attachment_size=self.attachment_size,
        )


@dataclass(frozen=True)
class DingTalkIdentityObservation:
    source_ingress_event_id: str
    received_at: str
    occurred_at: str
    tenant_code: str
    external_subject_id: str
    display_name: str
    connector_id: str
    robot_code: str
    conversation_type: str
    conversation_id: str
    message_kind: str
    safe_text: str
    text_truncated: bool
    attachment_type: str
    attachment_name: str
    attachment_size: int | None
