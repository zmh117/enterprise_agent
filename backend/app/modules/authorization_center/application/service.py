from __future__ import annotations

from typing import Any

from app.modules.audit.application.audit_service import AuditService
from app.modules.authorization_center.infrastructure.repository import (
    AuthorizationCenterRepository,
)
from app.modules.identity.infrastructure import IdentityRepository
from app.shared.exceptions import PermissionDenied


class BusinessAuthorizationService:
    """Authorize application access; MCP binding owns all Tool eligibility."""

    def __init__(
        self,
        repository: AuthorizationCenterRepository,
        identity_repository: IdentityRepository,
        *,
        audit_service: AuditService | None = None,
    ) -> None:
        self.repository = repository
        self.identity_repository = identity_repository
        self.audit_service = audit_service

    def decide(
        self,
        *,
        user_id: str,
        application_id: str = "",
        application_code: str = "",
        capability_code: str = "",
        environment: str = "",
        base: str = "",
        workshop: str = "",
        stage: str = "invoke",
    ) -> dict[str, Any]:
        if capability_code:
            return self._decision(
                False,
                stage,
                "legacy_capability_boundary_retired",
                [],
                {},
                scope=self._scope_summary(environment, base, workshop),
            )
        user = self.identity_repository.get_user(user_id)
        application = self.repository.database.execute_one(
            "select * from business_application where id = ?"
            if application_id
            else "select * from business_application where code = ?",
            (application_id or application_code,),
        )
        if application is None:
            return self._decision(False, stage, "application_not_found", [], {})
        if str(user["status"]) != "enabled":
            return self._decision(False, stage, "user_disabled", [], application)
        if str(application["status"]) != "enabled":
            return self._decision(False, stage, "application_disabled", [], application)
        accesses = self.repository.business_access_for_user(
            user_id=user_id,
            application_id=str(application["id"]),
        )
        matching_roles = [
            str(access["role_code"])
            for access in accesses
            if not (environment or base or workshop)
            or any(
                self._scope_matches(
                    scope,
                    environment=environment,
                    base=base,
                    workshop=workshop,
                )
                for scope in access["scopes"]
            )
        ]
        return self._decision(
            bool(matching_roles),
            stage,
            "application_role_allow" if matching_roles else "no_application_role",
            matching_roles,
            application,
            scope=self._scope_summary(environment, base, workshop),
        )

    def require(self, **kwargs: Any) -> dict[str, Any]:
        decision = self.decide(**kwargs)
        if decision["allowed"]:
            return decision
        if self.audit_service:
            self.audit_service.record(
                "authorization.business.denied",
                status="DENIED",
                summary="Business authorization denied",
                actor_id=str(kwargs.get("user_id") or ""),
                payload=decision,
            )
        raise PermissionDenied(
            f"Business authorization denied: {decision['reason']}",
            safe_message="当前用户未获得该业务应用权限",
            error_code="business_application_denied",
            diagnostics={"decision": decision},
        )

    @staticmethod
    def _scope_matches(
        scope: dict[str, Any],
        *,
        environment: str,
        base: str,
        workshop: str,
    ) -> bool:
        if environment and str(scope.get("environment_code") or "") != environment:
            return False
        if base and str(scope.get("base_code") or "") not in {"", base}:
            return False
        if workshop and str(scope.get("workshop_code") or "") not in {"", workshop}:
            return False
        return True

    @staticmethod
    def _scope_summary(environment: str, base: str, workshop: str) -> dict[str, str]:
        return {"environment": environment, "base": base, "workshop": workshop}

    @staticmethod
    def _decision(
        allowed: bool,
        stage: str,
        reason: str,
        role_codes: list[str],
        application: dict[str, Any],
        *,
        scope: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return {
            "allowed": allowed,
            "stage": stage,
            "reason": reason,
            "source_role_codes": sorted(set(role_codes)),
            "application": {
                "id": str(application.get("id") or ""),
                "code": str(application.get("code") or ""),
            },
            "scope": scope or {},
        }


class AuthorizationExplanationService:
    def __init__(self, business_authorization: BusinessAuthorizationService) -> None:
        self.business_authorization = business_authorization

    def explain(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "decision": self.business_authorization.decide(**kwargs),
            "notice": "解释仅显示安全的授权来源摘要，不包含策略条件、消息正文或凭据。",
        }
