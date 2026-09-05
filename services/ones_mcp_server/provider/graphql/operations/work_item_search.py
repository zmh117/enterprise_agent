from __future__ import annotations

from typing import Any, Final

from services.ones_mcp_server.errors import invalid_provider_response
from services.ones_mcp_server.provider.graphql.documents import load_graphql_document
from services.ones_mcp_server.provider.graphql.operations.normalization import (
    bounded_int,
    bounded_string,
    page_items,
    require_mapping,
)


ISSUE_TYPES: Final = ("demand", "task", "defect")
ISSUE_TYPE_UUIDS: Final = {
    "demand": "WE3uoYoq",
    "task": "Rbk6XNBr",
    "defect": "B4TV9bu5",
}
ISSUE_TYPES_BY_UUID: Final = {value: key for key, value in ISSUE_TYPE_UUIDS.items()}
WORK_ITEM_SEARCH_OPERATION_CODE: Final = "work_item_search"
WORK_ITEM_SEARCH_PATH: Final = "/project/api/project/team/{team_uuid}/items/graphql"
WORK_ITEM_SEARCH_DOCUMENT: Final = load_graphql_document("work_item_search.graphql")


class WorkItemSearchOperation:
    code = WORK_ITEM_SEARCH_OPERATION_CODE
    path_template = WORK_ITEM_SEARCH_PATH
    query_type = "group-task-data"
    document = WORK_ITEM_SEARCH_DOCUMENT

    def build_variables(
        self,
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        del context
        issue_type = str(arguments["issue_type"])
        issue_type_uuid = ISSUE_TYPE_UUIDS[issue_type]
        limit = int(arguments["limit"])
        return {
            "groupBy": {"tasks": {}},
            "groupOrderBy": None,
            "groupFilter": None,
            "orderBy": {"position": "ASC", "createTime": "DESC"},
            "filterGroup": [
                {
                    "name_match": arguments["keyword"],
                    "issueType_in": [issue_type_uuid],
                }
            ],
            "pagination": {"limit": limit, "preciseCount": True},
            "_limit": limit,
            "_issue_type": issue_type,
            "_issue_type_uuid": issue_type_uuid,
        }

    def parse_response(
        self,
        payload: dict[str, Any],
        *,
        variables: dict[str, Any],
    ) -> dict[str, Any]:
        limit = bounded_int(variables.get("_limit"), minimum=1)
        expected_uuid = bounded_string(
            variables.get("_issue_type_uuid"), maximum=128
        )
        expected_type = variables.get("_issue_type")
        if expected_type not in ISSUE_TYPES:
            raise invalid_provider_response("ones_provider_schema_invalid")
        items, total, truncated, _cursor = page_items(
            payload,
            collection="tasks",
            limit=limit,
        )
        normalized: list[dict[str, Any]] = []
        for item in items:
            issue_type = require_mapping(item.get("issueType"))
            issue_type_uuid = bounded_string(issue_type.get("uuid"), maximum=128)
            if (
                issue_type_uuid != expected_uuid
                or ISSUE_TYPES_BY_UUID.get(issue_type_uuid) != expected_type
            ):
                raise invalid_provider_response("ones_provider_schema_invalid")
            normalized.append(
                {
                    "number": bounded_int(item.get("number")),
                    "name": bounded_string(item.get("name"), maximum=500),
                    "type": expected_type,
                }
            )
        return {
            "items": normalized,
            "total": total,
            "truncated": truncated,
            "untrusted_data": True,
        }


WORK_ITEM_SEARCH_OPERATION = WorkItemSearchOperation()
