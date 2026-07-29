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
    ) -> AuthorizedJobContext: ...

    def close(self) -> None: ...
