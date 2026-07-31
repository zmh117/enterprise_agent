from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


CAPABILITY_IDENTIFIER_MAX_LENGTH = 128
HTTP_JSON_EXECUTOR_ID = "http-json-v1"
_CAPABILITY_SEGMENT = r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*"
_CAPABILITY_IDENTIFIER_PATTERN = re.compile(
    rf"^cap__{_CAPABILITY_SEGMENT}__{_CAPABILITY_SEGMENT}__{_CAPABILITY_SEGMENT}$"
)


class OperationSemantics(StrEnum):
    QUERY = "QUERY"


class DataClassification(StrEnum):
    INTERNAL = "INTERNAL"


class ConnectionDraftStatus(StrEnum):
    DRAFT = "DRAFT"
    VERIFIED = "VERIFIED"


class PublishedRevisionStatus(StrEnum):
    PUBLISHED = "PUBLISHED"
    DISABLED = "DISABLED"
    ARCHIVED = "ARCHIVED"


class CapabilityReleaseStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"
    DISABLED = "DISABLED"
    ARCHIVED = "ARCHIVED"


class CredentialStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INVALID = "INVALID"
    DISABLED = "DISABLED"


class ChallengeStatus(StrEnum):
    PENDING = "PENDING"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"


class MappingValueSource(StrEnum):
    AGENT_INPUT = "AGENT_INPUT"
    SYSTEM_CONTEXT = "SYSTEM_CONTEXT"
    CONSTANT = "CONSTANT"
    RESPONSE = "RESPONSE"


class MappingScalarType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"


@dataclass(frozen=True, slots=True)
class CapabilityIdentifier:
    value: str

    def __post_init__(self) -> None:
        if len(self.value) > CAPABILITY_IDENTIFIER_MAX_LENGTH:
            raise ValueError("Capability Identifier exceeds 128 characters")
        if not _CAPABILITY_IDENTIFIER_PATTERN.fullmatch(self.value):
            raise ValueError(
                "Capability Identifier must match cap__<provider>__<domain>__<operation>"
            )

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class RevisionRef:
    identity_id: str
    revision_id: str
    revision: int
    content_hash: str

    def __post_init__(self) -> None:
        if not self.identity_id or not self.revision_id:
            raise ValueError("Revision identity is required")
        if self.revision < 1:
            raise ValueError("Revision must be positive")
        if len(self.content_hash) != 64:
            raise ValueError("Revision content hash must be SHA-256")


@dataclass(frozen=True, slots=True)
class ApiConnectionRevision:
    ref: RevisionRef
    origin: str
    status: PublishedRevisionStatus = PublishedRevisionStatus.PUBLISHED


@dataclass(frozen=True, slots=True)
class AuthenticationProfileRevision:
    ref: RevisionRef
    login_path: str
    token_path: str
    user_path: str
    teams_path: str
    authorization_header: str
    status: PublishedRevisionStatus = PublishedRevisionStatus.PUBLISHED


@dataclass(frozen=True, slots=True)
class CapabilityRevision:
    ref: RevisionRef
    identifier: CapabilityIdentifier
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    operation_semantics: OperationSemantics = OperationSemantics.QUERY
    data_classification: DataClassification = DataClassification.INTERNAL


@dataclass(frozen=True, slots=True)
class HandlerRevision:
    ref: RevisionRef
    connection_revision_id: str
    authentication_profile_revision_id: str
    method: str
    relative_path: str
    mapping_plan_id: str
    executor_id: str = HTTP_JSON_EXECUTOR_ID
    graphql_document: str = ""


@dataclass(frozen=True, slots=True)
class CompiledMappingPlan:
    id: str
    schema_version: int
    content_hash: str
    plan: dict[str, Any]

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("Unsupported compiled Mapping Plan version")
        if len(self.content_hash) != 64:
            raise ValueError("Mapping Plan content hash must be SHA-256")


@dataclass(frozen=True, slots=True)
class CapabilityRelease:
    id: str
    identifier: CapabilityIdentifier
    release_revision: int
    capability_revision: RevisionRef
    handler_revision: RevisionRef
    connection_revision: RevisionRef
    authentication_profile_revision: RevisionRef
    mapping_plan_id: str
    status: CapabilityReleaseStatus = CapabilityReleaseStatus.ACTIVE
    release_note: str = ""
    replacement_release_id: str = ""
    deprecation_reason: str = ""

    def __post_init__(self) -> None:
        if self.release_revision < 1:
            raise ValueError("Release revision must be positive")


@dataclass(frozen=True, slots=True)
class ExternalApiCredential:
    id: str
    user_id: str
    provider: str
    connection_revision_id: str
    encrypted_token: str = field(repr=False)
    status: CredentialStatus = CredentialStatus.ACTIVE
    revision: int = 1

    def public(self) -> dict[str, object]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "provider": self.provider,
            "connection_revision_id": self.connection_revision_id,
            "status": self.status.value,
            "revision": self.revision,
            "configured": bool(self.encrypted_token),
        }


@dataclass(frozen=True, slots=True)
class VerificationChallenge:
    id: str
    user_id: str
    connection_revision_id: str
    external_user_id: str
    display_name: str
    team_ids: tuple[str, ...]
    encrypted_token: str = field(repr=False)
    expires_at: str = ""
    status: ChallengeStatus = ChallengeStatus.PENDING

    def public(self) -> dict[str, object]:
        return {
            "challenge_id": self.id,
            "external_user_id": self.external_user_id,
            "display_name": self.display_name,
            "team_ids": list(self.team_ids),
            "expires_at": self.expires_at,
        }


@dataclass(frozen=True, slots=True)
class ExternalExecutionSubjectSnapshot:
    provider: str
    external_user_id: str
    default_team_id: str
    binding_revision: int

    def __post_init__(self) -> None:
        if not self.provider or not self.external_user_id or not self.default_team_id:
            raise ValueError("External execution subject is incomplete")
        if self.binding_revision < 1:
            raise ValueError("Binding revision must be positive")

    def to_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "external_user_id": self.external_user_id,
            "default_team_id": self.default_team_id,
            "binding_revision": self.binding_revision,
        }
