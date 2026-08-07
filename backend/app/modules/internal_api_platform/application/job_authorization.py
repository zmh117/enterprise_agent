from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..domain.addressing import TargetRef


@dataclass(frozen=True)
class AuthorizedJobContext:
    job_id: str
    user_id: str
    project_code: str
    application_id: str
    application_publication_id: str
    handler_id: str
    handler_version: str
    resource_revision_id: str
    execution_scope_key: str
    schema_version: int = 1
    snapshot_id: str = ""
    tool_execution_binding_id: str = ""
    tool_release_id: str = ""
    implementation_digest: str = ""
    public_schema_hash: str = ""
    actual_placement: str = ""
    workshop_partition_policy_revision_id: str = ""
    workshop_partition_policy_content_hash: str = ""
    database_table_prefix: str = ""
    redis_prefixes: tuple[str, ...] = ()
    loki_scope_policy_revision_id: str = ""
    loki_scope_policy_content_hash: str = ""
    loki_scope_conditions: tuple[tuple[str, str], ...] = ()


class JobAccessAuthorizer(Protocol):
    """Authorize a tool target against a persisted business-application Job."""

    def authorize(
        self,
        *,
        job_id: str,
        user_id: str,
        project_code: str,
        application_id: str,
        capability_code: str,
        target: TargetRef,
        placement: str = "",
        tool_call_id: str = "",
        correlation_id: str = "",
    ) -> AuthorizedJobContext: ...

    def close(self) -> None: ...
