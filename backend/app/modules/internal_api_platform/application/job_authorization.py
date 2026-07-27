from __future__ import annotations

from typing import Protocol

from ..domain.addressing import TargetRef


class JobAccessAuthorizer(Protocol):
    """Authorize a tool target against a persisted business-application Job."""

    def authorize(
        self,
        *,
        job_id: str,
        user_id: str,
        capability_code: str,
        target: TargetRef,
    ) -> bool: ...

    def close(self) -> None: ...
