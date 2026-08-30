from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.shared.exceptions import NonRetryableExecutionError


class ManagedChannelKind(StrEnum):
    WEBHOOK = "WEBHOOK"
    DINGTALK_APP_ROBOT = "DINGTALK_APP_ROBOT"


class DingTalkEnterpriseStatus(StrEnum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    ARCHIVED = "ARCHIVED"


_DINGTALK_ENTERPRISE_TRANSITIONS = {
    DingTalkEnterpriseStatus.PENDING_VERIFICATION: frozenset(
        {DingTalkEnterpriseStatus.ACTIVE, DingTalkEnterpriseStatus.DISABLED}
    ),
    DingTalkEnterpriseStatus.ACTIVE: frozenset({DingTalkEnterpriseStatus.DISABLED}),
    DingTalkEnterpriseStatus.DISABLED: frozenset(
        {
            DingTalkEnterpriseStatus.PENDING_VERIFICATION,
            DingTalkEnterpriseStatus.ARCHIVED,
        }
    ),
    DingTalkEnterpriseStatus.ARCHIVED: frozenset({DingTalkEnterpriseStatus.PENDING_VERIFICATION}),
}


def require_dingtalk_enterprise_transition(
    current: str | DingTalkEnterpriseStatus,
    target: str | DingTalkEnterpriseStatus,
) -> DingTalkEnterpriseStatus:
    try:
        current_status = DingTalkEnterpriseStatus(str(current))
        target_status = DingTalkEnterpriseStatus(str(target))
    except ValueError as exc:
        raise NonRetryableExecutionError(
            "Unsupported DingTalk enterprise status",
            safe_message="钉钉企业状态无效",
            error_code="dingtalk_enterprise_status_invalid",
        ) from exc
    if current_status == target_status:
        return target_status
    if target_status not in _DINGTALK_ENTERPRISE_TRANSITIONS[current_status]:
        raise NonRetryableExecutionError(
            f"Illegal DingTalk enterprise transition: {current_status} -> {target_status}",
            safe_message="当前钉钉企业状态不允许执行此操作",
            error_code="dingtalk_enterprise_transition_invalid",
        )
    return target_status


def normalize_dingtalk_corp_id(value: object) -> str:
    """Normalize an SDK-observed Corp ID without changing its opaque value."""

    normalized = str(value or "").strip()
    if (
        not normalized
        or len(normalized) > 128
        or any(character.isspace() or ord(character) < 32 for character in normalized)
    ):
        raise NonRetryableExecutionError(
            "DingTalk Corp ID is invalid",
            safe_message="钉钉企业验证消息缺少有效 Corp ID",
            error_code="dingtalk_corp_id_invalid",
        )
    return normalized


def require_immutable_dingtalk_corp_id(current: object, observed: object) -> str:
    normalized = normalize_dingtalk_corp_id(observed)
    existing = str(current or "").strip()
    if existing and existing != normalized:
        raise NonRetryableExecutionError(
            "Verified DingTalk Corp ID cannot be changed",
            safe_message="消息所属钉钉企业与已验证企业不一致",
            error_code="dingtalk_corp_id_mismatch",
        )
    return normalized


@dataclass(frozen=True)
class DingTalkApplicationInput:
    name: str
    client_id: str
    client_secret: str
    dingtalk_enterprise_id: str
    allow_private_chat: bool = True
    allow_group_chat: bool = True
    require_group_at: bool = True
    work_notification_agent_id: int | None = None


@dataclass(frozen=True)
class RuntimeConnectorState:
    connector_id: str
    revision: int
    status: str
    connected: bool
    registered: bool
    error_code: str = ""
    error_summary: str = ""


@dataclass(frozen=True)
class ChannelIngressSubmission:
    connector_id: str
    external_event_id: str
    correlation_id: str
    normalized_event: dict[str, Any]
    safe_summary: dict[str, Any]
    payload_hash: str
    request_bytes: int
    reply_credential: str = ""
