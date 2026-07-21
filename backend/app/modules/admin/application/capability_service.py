from __future__ import annotations

from typing import Any

from app.modules.admin.domain import ADMIN_CAPABILITIES
from app.modules.identity.application.authorization import AuthorizationEvaluator
from app.modules.identity.infrastructure import IdentityRepository


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
        for item in ADMIN_CAPABILITIES:
            if not self.authorization.decide(
                user_id=user_id,
                resource_type=item.resource_type,
                resource_code=item.resource_code,
                action=item.action,
            ).allowed:
                continue
            capabilities.append(item.code)
            modules.setdefault(item.module, []).append(item.action)
        roles = self.repository.role_codes_for_user(user_id)
        return {
            "capabilities": capabilities,
            "modules": {key: sorted(set(value)) for key, value in sorted(modules.items())},
            "data_scope": self.repository.safe_platform_scope_summary(
                user_id=user_id,
                role_codes=roles,
                global_access="platform-admin" in roles,
            ),
        }
