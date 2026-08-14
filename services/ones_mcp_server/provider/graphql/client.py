from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.ones_mcp_server.provider.graphql.operation import GraphqlOperationRegistry
from services.ones_mcp_server.provider.http_client import OnesProviderHttpClient


@dataclass(frozen=True, slots=True)
class GraphqlExecution:
    request: dict[str, Any]
    response: dict[str, Any]
    output: dict[str, Any]


class OnesGraphqlClient:
    """Executes only GraphQL operations present in the code-owned registry."""

    def __init__(
        self,
        http: OnesProviderHttpClient,
        registry: GraphqlOperationRegistry,
    ) -> None:
        self.http = http
        self.registry = registry

    def build_request(
        self,
        operation_code: str,
        *,
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        operation = self.registry.require(operation_code)
        variables = operation.build_variables(arguments, context)
        return {"query": operation.document, "variables": variables}

    def execute(
        self,
        operation_code: str,
        *,
        arguments: dict[str, Any],
        context: dict[str, Any],
        headers: dict[str, str],
    ) -> GraphqlExecution:
        operation = self.registry.require(operation_code)
        request = self.build_request(
            operation_code,
            arguments=arguments,
            context=context,
        )
        response = self.http.post_json(operation.path, request, headers=headers)
        output = operation.parse_response(
            response,
            variables=dict(request["variables"]),
        )
        return GraphqlExecution(request=request, response=response, output=output)
