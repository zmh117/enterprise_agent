from __future__ import annotations

from app.modules.audit.application.audit_service import AuditService
from app.modules.identity.domain import AuthorizationDecision
from app.modules.identity.infrastructure import IdentityRepository
from app.shared.exceptions import PermissionDenied


class AuthorizationEvaluator:
    def __init__(
        self,
        repository: IdentityRepository,
        audit_service: AuditService | None = None,
    ) -> None:
        self.repository = repository
        self.audit_service = audit_service

    def decide(
        self,
        *,
        user_id: str,
        resource_type: str,
        resource_code: str,
        action: str = "use",
    ) -> AuthorizationDecision:
        user = self.repository.get_user(user_id)
        roles = self.repository.role_codes_for_user(user_id)
        if str(user["status"]) != "enabled":
            return self._decision(
                False,
                user_id,
                roles,
                resource_type,
                resource_code,
                action,
                (),
                "user_disabled",
            )
        policies = self.repository.policies_for_principals(
            user_id=user_id,
            role_codes=roles,
            resource_type=resource_type,
            resource_code=resource_code,
            action=action,
        )
        denies = [row for row in policies if str(row["effect"]) == "deny"]
        allows = [row for row in policies if str(row["effect"]) == "allow"]
        matched = tuple(str(row["id"]) for row in policies)
        if denies:
            return self._decision(
                False,
                user_id,
                roles,
                resource_type,
                resource_code,
                action,
                matched,
                "explicit_deny",
            )
        return self._decision(
            bool(allows),
            user_id,
            roles,
            resource_type,
            resource_code,
            action,
            matched,
            "allow" if allows else "no_matching_allow",
        )

    def decide_platform_scope(
        self,
        *,
        user_id: str,
        environment: str,
        base: str,
        workshop: str = "",
        tool_name: str = "",
    ) -> AuthorizationDecision:
        user = self.repository.get_user(user_id)
        roles = self.repository.role_codes_for_user(user_id)
        resource_code = "/".join(
            value for value in (environment, base, workshop) if value
        )
        if str(user["status"]) != "enabled":
            return self._decision(
                False,
                user_id,
                roles,
                "platform_scope",
                resource_code,
                "use",
                (),
                "user_disabled",
            )
        if not environment or not base:
            return self._decision(
                False,
                user_id,
                roles,
                "platform_scope",
                resource_code,
                "use",
                (),
                "scope_required",
            )
        grants = self.repository.platform_grants_for_principals(
            user_id=user_id,
            role_codes=roles,
            environment=environment,
            base=base,
            workshop=workshop,
            tool_name=tool_name,
        )
        denies = [row for row in grants if str(row["effect"]) == "deny"]
        allows = [row for row in grants if str(row["effect"]) == "allow"]
        reason = "explicit_scope_deny" if denies else (
            "scope_allow" if allows else "no_matching_scope_allow"
        )
        return self._decision(
            bool(allows) and not denies,
            user_id,
            roles,
            "platform_scope",
            resource_code,
            "use",
            (),
            reason,
            matched_grants=tuple(str(row["id"]) for row in grants),
            extra_trace={
                "environment": environment,
                "base": base,
                "workshop": workshop,
                "tool_name": tool_name,
            },
        )

    def require_platform_scope(
        self,
        *,
        user_id: str,
        environment: str,
        base: str,
        workshop: str = "",
        tool_name: str = "",
    ) -> AuthorizationDecision:
        decision = self.decide_platform_scope(
            user_id=user_id,
            environment=environment,
            base=base,
            workshop=workshop,
            tool_name=tool_name,
        )
        if not decision.allowed:
            self._audit_denial(decision)
            raise PermissionDenied(
                f"Platform scope denied: {decision.reason}",
                safe_message="You are not allowed to access this data scope",
                error_code="platform_scope_denied",
            )
        return decision

    def record_shadow_comparison(
        self,
        *,
        user_id: str,
        legacy_allowed: bool,
        decision: AuthorizationDecision,
    ) -> None:
        if not self.audit_service or legacy_allowed == decision.allowed:
            return
        self.audit_service.record(
            "permission.rbac.shadow_mismatch",
            status="DIFFERENT",
            summary="Legacy and unified authorization decisions differ",
            actor_id=user_id,
            payload={
                "legacy_allowed": legacy_allowed,
                "unified_allowed": decision.allowed,
                "decision": decision.trace,
            },
        )

    def require(
        self,
        *,
        user_id: str,
        resource_type: str,
        resource_code: str,
        action: str = "use",
    ) -> AuthorizationDecision:
        decision = self.decide(
            user_id=user_id,
            resource_type=resource_type,
            resource_code=resource_code,
            action=action,
        )
        if not decision.allowed:
            self._audit_denial(decision)
            raise PermissionDenied(
                f"Permission denied: {decision.reason}",
                safe_message="You are not allowed to perform this action",
                error_code="permission_denied",
            )
        return decision

    def _decision(
        self,
        allowed: bool,
        user_id: str,
        roles: tuple[str, ...],
        resource_type: str,
        resource_code: str,
        action: str,
        matched: tuple[str, ...],
        reason: str,
        *,
        matched_grants: tuple[str, ...] = (),
        extra_trace: dict[str, object] | None = None,
    ) -> AuthorizationDecision:
        trace: dict[str, object] = {
            "user_id": user_id,
            "role_codes": list(roles),
            "resource_type": resource_type,
            "resource_code": resource_code,
            "action": action,
            "matched_policy_ids": list(matched),
            "matched_grant_ids": list(matched_grants),
            "allowed": allowed,
            "reason": reason,
        }
        trace.update(extra_trace or {})
        return AuthorizationDecision(
            allowed=allowed,
            user_id=user_id,
            resource_type=resource_type,
            resource_code=resource_code,
            action=action,
            matched_policy_ids=matched,
            matched_grant_ids=matched_grants,
            role_codes=roles,
            reason=reason,
            trace=trace,
        )

    def _audit_denial(self, decision: AuthorizationDecision) -> None:
        if not self.audit_service:
            return
        self.audit_service.record(
            "permission.rbac.denied",
            status="DENIED",
            summary="RBAC authorization denied",
            actor_id=decision.user_id,
            payload=decision.trace,
        )
