from __future__ import annotations

from app.modules.authorization_center.application import BusinessAuthorizationService
from app.shared.database import Database
from app.shared.exceptions import NotFound, PermissionDenied

from ..domain.addressing import TargetRef
from ..domain.errors import AuthorizationError


class BusinessApplicationJobAccessAuthorizer:
    """Re-check current role access for a pinned business-application Job."""

    def __init__(
        self,
        database: Database,
        business_authorization: BusinessAuthorizationService,
    ) -> None:
        self.database = database
        self.business_authorization = business_authorization

    def authorize(
        self,
        *,
        job_id: str,
        user_id: str,
        capability_code: str,
        target: TargetRef,
    ) -> bool:
        if not job_id:
            return False
        job = self.database.execute_one(
            """
            select id, user_id, internal_user_id, business_application_id, status
              from agent_job
             where id = ?
            """,
            (job_id,),
        )
        if job is None:
            raise AuthorizationError("Agent Job authorization context is invalid")
        expected_user_id = str(job.get("internal_user_id") or job.get("user_id") or "")
        if not user_id or expected_user_id != user_id:
            raise AuthorizationError("Agent Job caller identity does not match")
        if str(job.get("status") or "") != "RUNNING":
            raise AuthorizationError("Agent Job is not running")
        application_id = str(job.get("business_application_id") or "")
        if not application_id:
            return False
        try:
            self.business_authorization.require(
                user_id=user_id,
                application_id=application_id,
                capability_code=capability_code,
                environment=target.environment,
                base=target.base,
                workshop=target.workshop or "",
                stage="internal_api_platform",
            )
        except (NotFound, PermissionDenied) as exc:
            raise AuthorizationError(
                "Caller is not authorized for the business application target"
            ) from exc
        return True

    def close(self) -> None:
        self.database.close()
