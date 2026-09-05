from __future__ import annotations

from dataclasses import dataclass
import re
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
        provider_variables = self._provider_variables(operation.document, variables)
        return {"query": operation.document, "variables": provider_variables}

    def execute(
        self,
        operation_code: str,
        *,
        arguments: dict[str, Any],
        context: dict[str, Any],
        headers: dict[str, str],
    ) -> GraphqlExecution:
        operation = self.registry.require(operation_code)
        variables = operation.build_variables(arguments, context)
        provider_variables = self._provider_variables(operation.document, variables)
        request = {"query": operation.document, "variables": provider_variables}
        team_uuid = context.get("team_id")
        if not isinstance(team_uuid, str) or not team_uuid:
            raise ValueError("ONES GraphQL Team context is invalid")
        path = operation.path_template.format(team_uuid=team_uuid)
        query = {"t": operation.query_type} if operation.query_type else None
        if query is None:
            response = self.http.post_json(path, request, headers=headers)
        else:
            response = self.http.post_json(
                path,
                request,
                headers=headers,
                query=query,
            )
        output = operation.parse_response(
            response,
            variables=variables,
        )
        return GraphqlExecution(
            request={
                "operation": operation.code,
                "path": path,
                **({"query_type": operation.query_type} if operation.query_type else {}),
                "variables": provider_variables,
            },
            response=response,
            output=output,
        )

    @staticmethod
    def _provider_variables(
        document: str,
        variables: dict[str, Any],
    ) -> dict[str, Any]:
        provider_variables = {
            key: value for key, value in variables.items() if not key.startswith("_")
        }
        referenced = set(re.findall(r"\$([A-Za-z_][A-Za-z0-9_]*)", document))
        if set(provider_variables) != referenced:
            raise ValueError("ONES GraphQL variables do not match the fixed document")
        return provider_variables
