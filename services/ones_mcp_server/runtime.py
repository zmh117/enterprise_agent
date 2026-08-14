"""Compatibility import surface for the modular ONES MCP implementation.

New code should import from ``auth``, ``credentials``, ``provider`` or ``tools``
directly. Keeping this module avoids breaking existing internal imports while the
service grows additional code-registered tools and GraphQL operations.
"""

from services.ones_mcp_server.auth.principal import (
    OnesPrincipalResolver,
    PrincipalBusinessAuthorizationPort,
    ResolvedOnesPrincipal,
)
from services.ones_mcp_server.credentials.refresh import OnesCredentialRefreshService
from services.ones_mcp_server.errors import OnesMcpError, OnesProviderUnauthorized
from services.ones_mcp_server.provider.graphql.client import (
    GraphqlExecution,
    OnesGraphqlClient,
)
from services.ones_mcp_server.provider.graphql.operation import (
    GraphqlOperation,
    GraphqlOperationRegistry,
)
from services.ones_mcp_server.provider.http_client import OnesProviderHttpClient
from services.ones_mcp_server.tools.work_item_search import (
    OnesSearchResult,
    OnesWorkItemSearchService,
)

__all__ = [
    "GraphqlExecution",
    "GraphqlOperation",
    "GraphqlOperationRegistry",
    "OnesCredentialRefreshService",
    "OnesGraphqlClient",
    "OnesMcpError",
    "OnesPrincipalResolver",
    "OnesProviderHttpClient",
    "OnesProviderUnauthorized",
    "OnesSearchResult",
    "OnesWorkItemSearchService",
    "PrincipalBusinessAuthorizationPort",
    "ResolvedOnesPrincipal",
]
