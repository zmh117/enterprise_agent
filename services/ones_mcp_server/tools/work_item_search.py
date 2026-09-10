from __future__ import annotations

from typing import Any

from services.ones_mcp_server.contracts import ISSUE_TYPES, TOOL_IDENTIFIER
from services.ones_mcp_server.provider.graphql.operations.work_item_search import (
    WORK_ITEM_SEARCH_OPERATION_CODE,
)
from services.ones_mcp_server.tools.base import OnesToolResult
from services.ones_mcp_server.tools.query_services import AutomaticGraphqlQueryService
from services.ones_mcp_server.tools.validation import invalid_input, require_fields, text

OnesSearchResult = OnesToolResult


class OnesWorkItemSearchService(AutomaticGraphqlQueryService):
    tool_identifier = TOOL_IDENTIFIER
    operation_code = WORK_ITEM_SEARCH_OPERATION_CODE
    output_field = "items"

    def __init__(
        self, resolver: Any, graphql: Any, credentials: Any, audit: Any, credential_refresh: Any
    ) -> None:
        super().__init__(resolver, credentials, audit, credential_refresh, graphql=graphql)

    @staticmethod
    def _validate_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
        value = require_fields(
            arguments,
            allowed={"keyword", "issue_type"},
            required={"keyword", "issue_type"},
        )
        if value["issue_type"] not in ISSUE_TYPES:
            raise invalid_input()
        return {
            "keyword": text(value["keyword"], maximum=200),
            "issue_type": value["issue_type"],
        }

    def validate_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._validate_arguments(arguments)

    def search(
        self,
        *,
        claims: dict[str, Any],
        arguments: dict[str, Any],
        correlation_id: str,
        invocation_id: str = "",
    ) -> OnesSearchResult:
        return self.invoke(
            claims=claims,
            arguments=arguments,
            correlation_id=correlation_id,
            invocation_id=invocation_id,
        )
