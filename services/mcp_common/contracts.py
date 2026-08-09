from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


McpAudience = Literal["ones-mcp", "data-mcp"]
ExecutableJobStatus = Literal["QUEUED", "RUNNING", "RETRYING"]


class StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class McpTokenClaims(StrictContract):
    iss: str
    aud: McpAudience
    sub: str
    azp: Literal["agent-worker"]
    job_id: str
    application_publication_id: str
    scopes: tuple[str, ...] = Field(min_length=1, max_length=64)
    iat: int
    exp: int
    jti: str

    @field_validator(
        "iss",
        "sub",
        "job_id",
        "application_publication_id",
        "jti",
    )
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("claim must not be empty")
        return value

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, scopes: tuple[str, ...]) -> tuple[str, ...]:
        if any(not scope or len(scope) > 128 for scope in scopes):
            raise ValueError("scope must contain 1-128 characters")
        if tuple(dict.fromkeys(scopes)) != scopes:
            raise ValueError("scopes must be unique and ordered")
        return scopes


class PrincipalContext(StrictContract):
    app_user_id: str
    job_id: str
    application_publication_id: str
    audience: McpAudience
    scopes: tuple[str, ...]
    token_id: str
    correlation_id: str


class SubjectSnapshot(StrictContract):
    external_identity_id: str = ""
    external_subject: str = ""
    provider_instance_id: str = ""
    default_team_id: str = ""
    binding_revision: int = Field(default=0, ge=0)


class JobContext(StrictContract):
    job_id: str
    app_user_id: str
    application_publication_id: str
    status: ExecutableJobStatus
    subject: SubjectSnapshot = Field(default_factory=SubjectSnapshot)


class ToolBindingContext(StrictContract):
    binding_id: str
    subject_snapshot_id: str
    server_code: McpAudience
    tool_name: str
    required_scope: str
    tool_schema_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    resource_code: str = ""
    resource_deployment_id: str = ""
    resource_revision_id: str = ""


class AuthorizedToolContext(StrictContract):
    principal: PrincipalContext
    job: JobContext
    binding: ToolBindingContext


class McpToolError(StrictContract):
    code: str
    message: str
    retryable: bool = False
    correlation_id: str


class McpToolProvenance(StrictContract):
    mcp_server_code: McpAudience
    server_version: str
    tool_name: str
    tool_schema_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    job_id: str
    app_user_id: str
    application_publication_id: str
    subject_snapshot_id: str = ""
    resource_deployment_id: str = ""
    resource_revision_id: str = ""
    credential_revision: int = Field(default=0, ge=0)
    request_summary: dict[str, Any] = Field(default_factory=dict)
    result_hash: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    result_size: int = Field(default=0, ge=0)
    status: Literal["SUCCEEDED", "FAILED", "DENIED"]
    duration_ms: int = Field(ge=0)
    correlation_id: str
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class McpResourceDeployment(StrictContract):
    id: str
    server_code: Literal["data-mcp"]
    resource_code: str
    active_resource_revision_id: str
    status: Literal["ACTIVE", "DISABLED"]
    revision: int = Field(ge=1)
    updated_by: str
    updated_at: datetime


def schema_hash(schema: dict[str, Any]) -> str:
    encoded = json.dumps(
        schema,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
