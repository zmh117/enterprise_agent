from __future__ import annotations

import json

from app.modules.permission.application.permission_service import (
    DATA_SCOPED_TOOLS,
    PermissionService,
)
from app.shared.exceptions import NotFound, PermissionDenied, ToolPolicyError


class SeedPolicyTestPermissionService(PermissionService):
    """Preserve low-level legacy test fixtures without a production fallback."""

    def __init__(
        self,
        *args: object,
        unified_enabled: bool,
        **kwargs: object,
    ) -> None:
        super().__init__(*args, **kwargs)
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
                strict_decision = self.authorization_evaluator.decide(
                    user_id=user_id,
                    resource_type=resource_type,
                    resource_code=resource_code,
                    action=action,
                )
            except NotFound:
                return False
            if strict_decision.allowed:
                return True
            roles = self.authorization_evaluator.repository.role_codes_for_user(
                user_id
            )
            return self._legacy_policy_allows(
                user_id=user_id,
                role_codes=roles,
                resource_type=resource_type,
                resource_code=resource_code,
                action=action,
            )
        row = self.config_repository.database.execute_one(
            """
            select id
              from permission_policy
             where subject_code = ?
               and resource_type = ?
               and (resource_code = ? or resource_code = '*')
               and effect = 'allow'
               and status = 'enabled'
             limit 1
            """,
            (user_id, resource_type, resource_code),
        )
        return row is not None

    def assert_tool_allowed(
        self,
        *,
        user_id: str,
        tool_name: str,
        project_code: str,
        scope: dict[str, str] | None = None,
    ) -> None:
        self.assert_registered_readonly_tool(tool_name)
        if not self._is_allowed(
            user_id=user_id,
            resource_type="tool",
            resource_code=tool_name,
            action="use",
        ):
            raise ToolPolicyError(
                f"Test user {user_id} cannot call {tool_name}",
                safe_message="当前用户无权调用此工具",
            )
        if not self._is_allowed(
            user_id=user_id,
            resource_type="project",
            resource_code=project_code,
            action="use",
        ):
            raise PermissionDenied(
                f"Test user {user_id} cannot use {project_code}",
                safe_message="当前用户无权在此范围内使用 Agent",
            )
        if not self.unified_enabled or tool_name not in DATA_SCOPED_TOOLS:
            return
        scope = scope or {}
        roles = self.authorization_evaluator.repository.role_codes_for_user(
            user_id
        )
        allowed = self._legacy_scope_allows(
            user_id=user_id,
            role_codes=roles,
            environment=scope.get("environment", ""),
            base=scope.get("base", ""),
            workshop=scope.get("workshop", ""),
            tool_name=tool_name,
        )
        if not allowed:
            raise ToolPolicyError(
                "Test user has no matching legacy data scope",
                safe_message="当前用户无权访问此数据范围",
            )

    def _legacy_policy_allows(
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
             where status = 'enabled'
               and resource_type = ?
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
            if (
                str(row["subject_type"]),
                str(row["subject_code"]),
            )
            in principals
        ]
        if any(str(row["effect"]) == "deny" for row in matched):
            return False
        return any(str(row["effect"]) == "allow" for row in matched)

    def _legacy_scope_allows(
        self,
        *,
        user_id: str,
        role_codes: tuple[str, ...],
        environment: str,
        base: str,
        workshop: str,
        tool_name: str,
    ) -> bool:
        rows = self.config_repository.database.execute(
            """
            select g.*, e.code as environment_code,
                   b.code as base_code, w.code as workshop_code
              from platform_access_grant g
              left join platform_environment e
                     on e.id = g.environment_id
              left join platform_base b on b.id = g.base_id
              left join platform_workshop w
                     on w.id = g.workshop_id
             where g.status = 'enabled'
             order by g.priority, g.id
            """
        )
        principals = {("user", user_id)}
        principals.update(("role", code) for code in role_codes)
        matched: list[dict[str, object]] = []
        for row in rows:
            if (
                str(row["subject_type"]),
                str(row["subject_code"]),
            ) not in principals:
                continue
            if row.get("environment_id") and (
                str(row.get("environment_code") or "") != environment
            ):
                continue
            if row.get("base_id") and (
                str(row.get("base_code") or "") != base
            ):
                continue
            if row.get("workshop_id") and (
                str(row.get("workshop_code") or "") != workshop
            ):
                continue
            tool_scope = json.loads(
                str(row.get("tool_scope_json") or "[]")
            )
            if (
                tool_name
                and tool_scope
                and "*" not in tool_scope
                and tool_name not in tool_scope
            ):
                continue
            matched.append(row)
        if any(str(row["effect"]) == "deny" for row in matched):
            return False
        return any(str(row["effect"]) == "allow" for row in matched)
