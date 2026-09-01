from __future__ import annotations

from typing import cast

from app.bootstrap import Container
from app.modules.external_action.repository import ExternalActionRepository
from app.modules.external_action.service import (
    ExternalActionService,
    ExternalActionTokenSigner,
    external_action_signing_key,
)
from app.modules.identity.application.principal_jwt import PrincipalJwks, PrincipalTokenVerifier
from app.modules.mcp_audit import McpAuditCoordinator
from services.dingtalk_mcp_server.auth.principal import DingTalkPrincipalResolver
from services.dingtalk_mcp_server.auth.identity_completion import (
    DingTalkUnionIdCompletionService,
)
from services.dingtalk_mcp_server.contracts import SERVER_CODE
from services.dingtalk_mcp_server.tools.mutation_catalog import build_mutation_tools
from services.dingtalk_mcp_server.tools.read_catalog import build_read_tools
from services.dingtalk_mcp_server.tools.registry import (
    DingTalkToolHandler,
    DingTalkToolRegistry,
)


def build_tool_registry(runtime: Container) -> DingTalkToolRegistry:
    if not runtime.settings.app_config_master_key:
        raise ValueError("DingTalk MCP requires the platform master key")
    resolver = DingTalkPrincipalResolver(
        runtime.database,
        PrincipalTokenVerifier(
            PrincipalJwks.from_file(runtime.settings.principal_jwt.public_jwks_file),
            expected_audience=SERVER_CODE,
            audit_service=runtime.audit_service,
        ),
        runtime.mcp_tool_snapshot_service,
        runtime.business_authorization_service,
        DingTalkUnionIdCompletionService(runtime),
    )
    audit = McpAuditCoordinator(
        runtime.database,
        max_payload_bytes=256 * 1024,
        audit_service=runtime.audit_service,
    )
    actions = ExternalActionService(
        ExternalActionRepository(runtime.database),
        ExternalActionTokenSigner(
            external_action_signing_key(runtime.settings.app_config_master_key)
        ),
        runtime.audit_service,
    )
    read_tools = build_read_tools(runtime, resolver, audit)
    mutation_tools = build_mutation_tools(runtime, resolver, actions, audit)
    tools = cast(tuple[DingTalkToolHandler, ...], (*read_tools, *mutation_tools))
    return DingTalkToolRegistry(
        authenticate=mutation_tools[0].authenticate,
        tools=tools,
        audit=audit,
    )
