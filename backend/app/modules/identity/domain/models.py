from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from app.shared.exceptions import NonRetryableExecutionError


class ExternalIdentityProvider(StrEnum):
    DINGTALK = "dingtalk"
    ONES = "ones"

    @classmethod
    def require_supported(cls, value: str) -> ExternalIdentityProvider:
        normalized = value.strip().lower()
        try:
            return cls(normalized)
        except ValueError as exc:
            raise NonRetryableExecutionError(
                f"Unsupported external identity provider: {value}",
                safe_message="不支持此外部身份提供方",
                error_code="identity_provider_unsupported",
            ) from exc


class ExternalCredentialUsageSource(StrEnum):
    ADMIN_TEST = "ADMIN_TEST"
    RUNTIME = "RUNTIME"


@dataclass(frozen=True)
class DingTalkApplicationObservationInput:
    external_identity_id: str
    connector_id: str
    source_ingress_event_id: str
    observed_at: str


@dataclass(frozen=True)
class DingTalkNicknameObservationInput:
    external_identity_id: str
    connector_id: str
    source_ingress_event_id: str
    nickname: str
    occurred_at: str
    received_at: str


@dataclass(frozen=True)
class ExternalIdentityDescriptor:
    provider: str
    tenant_code: str
    external_subject_id: str
    connector_id: str = ""
    union_id: str = ""
    open_id: str = ""
    display_name: str = ""
    dingtalk_enterprise_id: str = ""
    source_ingress_event_id: str = ""
    occurred_at: str = ""
    received_at: str = ""


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    user_id: str
    username: str
    display_name: str
    role_codes: tuple[str, ...] = ()
    external_identity_id: str = ""
    auth_source: str = ""
    session_id: str = ""


@dataclass(frozen=True)
class AuthorizationDecision:
    allowed: bool
    user_id: str
    resource_type: str
    resource_code: str
    action: str
    matched_policy_ids: tuple[str, ...] = ()
    matched_grant_ids: tuple[str, ...] = ()
    role_codes: tuple[str, ...] = ()
    reason: str = ""
    trace: dict[str, object] = field(default_factory=dict)
