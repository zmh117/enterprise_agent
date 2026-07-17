from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ExternalIdentityDescriptor:
    provider: str
    tenant_code: str
    external_subject_id: str
    connector_id: str = ""
    union_id: str = ""
    open_id: str = ""
    display_name: str = ""


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
