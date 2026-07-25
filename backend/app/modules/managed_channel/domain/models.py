from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ManagedChannelKind(StrEnum):
    WEBHOOK = "WEBHOOK"
    DINGTALK_APP_ROBOT = "DINGTALK_APP_ROBOT"


@dataclass(frozen=True)
class DingTalkApplicationInput:
    name: str
    client_id: str
    client_secret: str
    tenant_code: str
    allow_private_chat: bool = True
    allow_group_chat: bool = True
    require_group_at: bool = True


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
