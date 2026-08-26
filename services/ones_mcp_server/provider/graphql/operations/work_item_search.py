from __future__ import annotations

from typing import Any, Final

from services.ones_mcp_server.errors import invalid_provider_response
from services.ones_mcp_server.provider.graphql.documents import load_graphql_document


ISSUE_TYPES: Final = ("demand", "task", "defect")
WORK_ITEM_SEARCH_OPERATION_CODE: Final = "work_item_search"
WORK_ITEM_SEARCH_PATH: Final = "/project/api/project/items/graphql"
WORK_ITEM_SEARCH_DOCUMENT: Final = load_graphql_document("work_item_search.graphql")


class WorkItemSearchOperation:
    code = WORK_ITEM_SEARCH_OPERATION_CODE
    path_template = WORK_ITEM_SEARCH_PATH
    query_type = ""
    document = WORK_ITEM_SEARCH_DOCUMENT

    def build_variables(
        self,
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "keyword": arguments["keyword"],
            "issue_type": arguments["issue_type"],
            "limit": arguments["limit"],
            "user_id": context["user_id"],
            "team_id": context["team_id"],
        }

    def parse_response(
        self,
        payload: dict[str, Any],
        *,
        variables: dict[str, Any],
    ) -> dict[str, Any]:
        if set(payload) != {"data"} or not isinstance(payload.get("data"), dict):
            raise invalid_provider_response("ones_provider_schema_invalid")
        data = payload["data"]
        if set(data) != {"workItems"} or not isinstance(data.get("workItems"), dict):
            raise invalid_provider_response("ones_provider_schema_invalid")
        work_items = data["workItems"]
        if set(work_items) != {"items", "total", "truncated"}:
            raise invalid_provider_response("ones_provider_schema_invalid")
        items = work_items.get("items")
        total = work_items.get("total")
        truncated = work_items.get("truncated")
        limit = variables.get("limit")
        if (
            type(limit) is not int
            or not isinstance(items, list)
            or len(items) > limit
            or type(total) is not int
            or total < 0
            or type(truncated) is not bool
        ):
            raise invalid_provider_response("ones_provider_schema_invalid")
        normalized: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict) or set(item) != {"number", "name", "type"}:
                raise invalid_provider_response("ones_provider_schema_invalid")
            if (
                type(item.get("number")) is not int
                or not isinstance(item.get("name"), str)
                or len(item["name"]) > 500
                or item.get("type") not in ISSUE_TYPES
            ):
                raise invalid_provider_response("ones_provider_schema_invalid")
            normalized.append(dict(item))
        return {
            "items": normalized,
            "total": total,
            "truncated": truncated,
            "untrusted_data": True,
        }


WORK_ITEM_SEARCH_OPERATION = WorkItemSearchOperation()
