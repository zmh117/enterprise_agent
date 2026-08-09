from __future__ import annotations

from app.modules.identity.application.authorization import AuthorizationEvaluator
from app.modules.job.infrastructure.repositories import ConfigurationRepository
from app.modules.permission.application.permission_service import PermissionService
from app.shared.exceptions import NotFound


class SeedPolicyTestPermissionService(PermissionService):
    """Honor seed RBAC grants in disposable tests without production fallback."""

    def __init__(
        self,
        config_repository: ConfigurationRepository,
        *,
        authorization_evaluator: AuthorizationEvaluator,
        unified_enabled: bool,
    ) -> None:
        super().__init__(
            config_repository,
            authorization_evaluator=authorization_evaluator,
        )
        self.unified_enabled = unified_enabled

    def _is_allowed(
        self,
        *,
        user_id: str,
        resource_type: str,
        resource_code: str,
        action: str,
    ) -> bool:
        if self.unified_enabled:
            try:
                decision = self.authorization_evaluator.decide(
                    user_id=user_id,
                    resource_type=resource_type,
                    resource_code=resource_code,
                    action=action,
                )
            except NotFound:
                return False
            if decision.allowed:
                return True
            role_codes = self.authorization_evaluator.repository.role_codes_for_user(user_id)
            return self._seed_policy_allows(
                user_id=user_id,
                role_codes=role_codes,
                resource_type=resource_type,
                resource_code=resource_code,
                action=action,
            )
        row = self.config_repository.database.execute_one(
            """
            select id from permission_policy
             where subject_code = ? and resource_type = ?
               and (resource_code = ? or resource_code = '*')
               and effect = 'allow' and status = 'enabled'
               and (action = ? or action = '*')
             limit 1
            """,
            (user_id, resource_type, resource_code, action),
        )
        return row is not None

    def _seed_policy_allows(
        self,
        *,
        user_id: str,
        role_codes: tuple[str, ...],
        resource_type: str,
        resource_code: str,
        action: str,
    ) -> bool:
        rows = self.config_repository.database.execute(
            """
            select subject_type, subject_code, effect
              from permission_policy
             where status = 'enabled' and resource_type = ?
               and (resource_code = ? or resource_code = '*')
               and (action = ? or action = '*')
             order by priority, id
            """,
            (resource_type, resource_code, action),
        )
        principals = {("user", user_id)}
        principals.update(("role", code) for code in role_codes)
        matched = [
            row
            for row in rows
            if (str(row["subject_type"]), str(row["subject_code"])) in principals
        ]
        if any(str(row["effect"]) == "deny" for row in matched):
            return False
        return any(str(row["effect"]) == "allow" for row in matched)
