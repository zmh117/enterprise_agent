from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.modules.admin.application.scope import AdminScope, strict_business_scope_summary
from app.modules.identity.api.dependencies import container, require_action
from app.modules.job.infrastructure.repositories import now_iso


def build_governance_dashboard_router() -> APIRouter:
    router = APIRouter(prefix="/api/admin/dashboard", tags=["governance-dashboard"])

    @router.get("")
    def dashboard(request: Request) -> dict[str, Any]:
        principal = require_action(
            request, resource_type="dashboard", resource_code="*", action="read"
        )
        c = container(request)
        authorization = c.authorization_evaluator

        def allowed(resource_type: str, action: str = "read") -> bool:
            return authorization.decide(
                user_id=principal.user_id,
                resource_type=resource_type,
                resource_code="*",
                action=action,
            ).allowed

        modules: list[dict[str, Any]] = []

        def count_module(
            code: str,
            resource_type: str,
            sql: str,
            *,
            params: tuple[object, ...] = (),
        ) -> None:
            if not allowed(resource_type):
                return
            row = c.database.execute_one(sql, params)
            modules.append({"code": code, "count": int((row or {}).get("count") or 0)})

        count_module(
            "agents",
            "agent",
            "select count(*) as count from agent_definition where status != 'archived'",
        )
        count_module(
            "applications",
            "business_application",
            "select count(*) as count from business_application where status != 'archived'",
        )
        if allowed("channel_connector"):
            modules.append(
                {"code": "channels", "count": len(c.managed_channel_service.list_channels())}
            )
        count_module("users", "user", "select count(*) as count from app_user")
        if allowed("identity"):
            modules.append(
                {
                    "code": "identity_candidates",
                    "count": c.identity_discovery_service.count_candidates(),
                }
            )
        if allowed("agent_job"):
            roles = c.identity_repository.role_codes_for_user(principal.user_id)
            scope = AdminScope(
                strict_business_scope_summary(
                    c.database,
                    user_id=principal.user_id,
                    global_access="platform-admin" in roles,
                ),
                principal.user_id,
            )
            if scope.global_access:
                row = c.database.execute_one("select count(*) as count from agent_job")
            else:
                row = c.database.execute_one(
                    """
                    select count(*) as count from agent_job
                     where internal_user_id = ? or requester_id = ? or user_id = ?
                    """,
                    (principal.user_id, principal.user_id, principal.user_id),
                )
            modules.append({"code": "jobs", "count": int((row or {}).get("count") or 0)})
        if allowed("mcp_server"):
            modules.append({"code": "mcp_servers", "count": 2})
        count_module(
            "mcp_tools",
            "mcp_tool",
            "select count(*) as count from mcp_tool where lifecycle_status != 'ARCHIVED'",
        )
        count_module(
            "mcp_resources",
            "mcp_resource",
            "select count(*) as count from mcp_resource where lifecycle_status != 'ARCHIVED'",
        )
        count_module(
            "credentials",
            "secret",
            "select count(*) as count from platform_secret",
        )
        return {
            "captured_at": now_iso(),
            "modules": modules,
            "data_chain": [
                "Channel / Debug",
                "Application Publication",
                "Agent Runtime (TypeScript)",
                "MCP Server",
                "Resource Generation",
                "Provider",
            ],
        }

    return router
