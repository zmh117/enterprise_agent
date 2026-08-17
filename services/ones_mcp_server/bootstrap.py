from __future__ import annotations

from dataclasses import replace

from app.bootstrap import Container
from app.modules.identity.application.principal_jwt import PrincipalJwks, PrincipalTokenVerifier
from app.modules.identity.infrastructure.ones_identity_verifier import UrllibOnesIdentityVerifier
from app.modules.mcp_audit import McpAuditCoordinator
from app.shared.config import OnesIdentitySettings
from services.ones_mcp_server.auth.principal import OnesPrincipalResolver
from services.ones_mcp_server.contracts import SERVER_CODE
from services.ones_mcp_server.credentials.refresh import OnesCredentialRefreshService
from services.ones_mcp_server.provider.graphql.client import OnesGraphqlClient
from services.ones_mcp_server.provider.graphql.operation import GraphqlOperationRegistry
from services.ones_mcp_server.provider.graphql.operations.work_item_search import (
    WORK_ITEM_SEARCH_OPERATION,
)
from services.ones_mcp_server.provider.http_client import OnesProviderHttpClient
from services.ones_mcp_server.provider.target import validate_provider_target
from services.ones_mcp_server.tools.registry import OnesToolRegistry
from services.ones_mcp_server.tools.work_item_search import OnesWorkItemSearchService


def build_work_item_search_service(runtime: Container) -> OnesWorkItemSearchService:
    settings = runtime.settings
    credentials = runtime.external_identity_credential_repository
    if credentials is None:
        raise ValueError("ONES MCP requires the platform credential master key")
    target = validate_provider_target(
        settings.ones_mcp.provider_base_url,
        allowed_hosts=settings.ones_mcp.provider_allowed_hosts,
        app_env=settings.environment,
        allow_insecure_local=settings.ones_mcp.allow_insecure_local,
    )
    verifier = PrincipalTokenVerifier(
        PrincipalJwks.from_file(settings.principal_jwt.public_jwks_file),
        expected_audience=SERVER_CODE,
        audit_service=runtime.audit_service,
    )
    resolver = OnesPrincipalResolver(
        runtime.database,
        verifier,
        runtime.mcp_tool_snapshot_service,
        runtime.business_authorization_service,
        credentials,
    )
    audit = McpAuditCoordinator(
        runtime.database,
        max_payload_bytes=settings.ones_mcp.max_response_bytes,
        audit_service=runtime.audit_service,
    )
    http = OnesProviderHttpClient(
        target,
        timeout_seconds=settings.ones_mcp.timeout_seconds,
        max_response_bytes=settings.ones_mcp.max_response_bytes,
    )
    graphql = OnesGraphqlClient(
        http,
        GraphqlOperationRegistry((WORK_ITEM_SEARCH_OPERATION,)),
    )
    login_settings = replace(
        settings.ones_identity,
        base_url=target.base_url,
        allowed_hosts=(target.host,),
        timeout_seconds=settings.ones_mcp.timeout_seconds,
        max_response_bytes=settings.ones_mcp.max_response_bytes,
        allow_insecure_local=target.allow_insecure_local,
    )
    if not isinstance(login_settings, OnesIdentitySettings):
        raise TypeError("ONES identity settings are invalid")
    refresh = OnesCredentialRefreshService(
        resolver,
        UrllibOnesIdentityVerifier(login_settings, environment=settings.environment),
        credentials,
        audit,
    )
    return OnesWorkItemSearchService(
        resolver,
        graphql,
        credentials,
        audit,
        refresh,
    )


def build_tool_registry(runtime: Container) -> OnesToolRegistry:
    work_item_search = build_work_item_search_service(runtime)
    return OnesToolRegistry(
        authenticate=work_item_search.authenticate,
        tools=(work_item_search,),
        audit=work_item_search.audit,
    )
