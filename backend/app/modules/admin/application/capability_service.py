from __future__ import annotations

from typing import Any

from app.modules.admin.domain import ADMIN_CAPABILITIES
from app.modules.admin.application.scope import (
    strict_business_scope_summary,
)
from app.modules.identity.application.authorization import AuthorizationEvaluator
from app.modules.identity.infrastructure import IdentityRepository
from app.modules.job.infrastructure.repositories import now_iso


class AdminCapabilityService:
    def __init__(
        self,
        repository: IdentityRepository,
        authorization: AuthorizationEvaluator,
    ) -> None:
        self.repository = repository
        self.authorization = authorization

    def summary(self, user_id: str) -> dict[str, Any]:
        capabilities = []
        modules: dict[str, list[str]] = {}
        roles = self.repository.role_codes_for_user(user_id)
        platform_admin = "platform-admin" in roles
        role_binding_codes = {
            str(row["capability_code"])
            for row in self.repository.database.execute(
                """
                select ac.capability_code
                  from rbac_role_admin_capability ac
                  join rbac_role r on r.id = ac.role_id
                  join rbac_user_role ur on ur.role_id = r.id
                 where ur.user_id = ? and ac.status = 'enabled'
                   and r.status = 'enabled' and ur.status = 'enabled'
                   and (ur.expires_at is null or ur.expires_at > ?)
                """,
                (user_id, now_iso()),
            )
        }
        for item in ADMIN_CAPABILITIES:
            if (
                not platform_admin
                and item.code not in role_binding_codes
                and not self.authorization.decide(
                    user_id=user_id,
                    resource_type=item.resource_type,
                    resource_code=item.resource_code,
                    action=item.action,
                ).allowed
            ):
                continue
            capabilities.append(item.code)
            modules.setdefault(item.module, []).append(item.action)
        return {
            "capabilities": capabilities,
            "modules": {key: sorted(set(value)) for key, value in sorted(modules.items())},
            "data_scope": strict_business_scope_summary(
                self.repository.database,
                user_id=user_id,
                global_access=platform_admin,
            ),
        }
