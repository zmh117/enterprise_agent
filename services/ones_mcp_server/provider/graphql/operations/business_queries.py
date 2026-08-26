from __future__ import annotations

from datetime import datetime
from typing import Any, Final

from services.ones_mcp_server.errors import invalid_provider_response
from services.ones_mcp_server.provider.graphql.documents import load_graphql_document
from services.ones_mcp_server.provider.graphql.operations.fixed import FixedGraphqlOperation
from services.ones_mcp_server.provider.graphql.operations.normalization import (
    bounded_int,
    bounded_string,
    normalize_work_item,
    normalized_list,
    optional_person,
    page_items,
    require_list,
    require_mapping,
    require_status,
)


PROJECT_SEARCH = "project_search"
ISSUE_TYPE_LIST = "issue_type_list"
WORK_ITEM_QUERY = "work_item_query"
SPRINT_WORK_ITEM_QUERY = "sprint_work_item_query"
WORK_ITEM_DETAIL = "work_item_detail"


def _project_variables(arguments: dict[str, Any], _context: dict[str, Any]) -> dict[str, Any]:
    filters: dict[str, Any] = {
        "visibleInProject_equal": True,
        "isArchive_equal": False,
    }
    keyword = str(arguments.get("keyword") or "").strip()
    if keyword:
        filters["name_match"] = keyword
    return {
        "projectOrderBy": {"isPin": "DESC", "namePinyin": "ASC", "createTime": "DESC"},
        "projectFilterGroup": [filters],
        "groupBy": {"projects": {}},
        "orderBy": None,
        "_limit": arguments["limit"],
    }


def _project_response(payload: dict[str, Any], variables: dict[str, Any]) -> dict[str, Any]:
    limit = bounded_int(variables.get("_limit"), minimum=1)
    raw, total, truncated, cursor = page_items(payload, collection="projects", limit=limit)
    projects: list[dict[str, Any]] = []
    for value in raw:
        project: dict[str, Any] = {
            "uuid": bounded_string(value.get("uuid"), maximum=128),
            "name": bounded_string(value.get("name"), maximum=300),
            "archived": value.get("isArchive") is True,
            "sample": value.get("isSample") is True,
        }
        owner = optional_person(value.get("owner"))
        if owner is not None:
            project["owner"] = owner
        if value.get("status") is not None:
            project["status"] = require_status(value.get("status"))
        projects.append(project)
    return normalized_list(
        "projects", projects, total=total, truncated=truncated, next_cursor=cursor
    )


def _issue_type_variables(
    arguments: dict[str, Any], _context: dict[str, Any]
) -> dict[str, Any]:
    return {
        "filter": {
            "scope_equal": arguments["project_uuid"],
            "scopeType_equal": 1,
        }
    }


def _issue_type_response(
    payload: dict[str, Any], variables: dict[str, Any]
) -> dict[str, Any]:
    data = require_mapping(payload.get("data"))
    raw_items = require_list(data.get("issueTypeScopes"))
    limit = bounded_int(variables.get("_limit", 100), minimum=1)
    output: list[dict[str, Any]] = []
    for raw in raw_items[:limit]:
        item = require_mapping(raw)
        issue_type = require_mapping(item.get("issueType"))
        sub = issue_type.get("subIssueType", False)
        if type(sub) is not bool:
            raise invalid_provider_response("ones_provider_schema_invalid")
        output.append(
            {
                "uuid": bounded_string(issue_type.get("uuid"), maximum=128),
                "scope_uuid": bounded_string(item.get("uuid"), maximum=128),
                "name": bounded_string(issue_type.get("name"), maximum=200),
                "sub_issue_type": sub,
            }
        )
    return normalized_list(
        "issue_types",
        output,
        total=len(raw_items),
        truncated=len(raw_items) > limit,
    )


def _microseconds(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("ONES work item time filter is invalid") from None
    if parsed.tzinfo is None:
        raise ValueError("ONES work item time filter is invalid")
    return str(int(parsed.timestamp() * 1_000_000))


def _work_item_variables(
    arguments: dict[str, Any], _context: dict[str, Any]
) -> dict[str, Any]:
    filters: dict[str, Any] = {}
    for argument, provider in (
        ("issue_type_uuids", "issueType_in"),
        ("status_uuids", "status_in"),
        ("status_categories", "statusCategory_in"),
        ("assignee_uuids", "assign_in"),
    ):
        if arguments.get(argument):
            filters[provider] = list(arguments[argument])
    if arguments.get("project_uuid"):
        filters["project_in"] = [arguments["project_uuid"]]
    if arguments.get("sprint_uuid"):
        filters["sprint_in"] = [arguments["sprint_uuid"]]
    created_from = arguments.get("created_from")
    created_to = arguments.get("created_to")
    if created_from or created_to:
        time_filter: dict[str, str] = {}
        if created_from:
            time_filter["gte"] = _microseconds(str(created_from))
        if created_to:
            time_filter["lte"] = _microseconds(str(created_to))
        filters["createTime_range"] = time_filter
    keyword = str(arguments.get("keyword") or "").strip()
    limit = int(arguments["limit"])
    return {
        "groupBy": {"tasks": {}},
        "groupOrderBy": None,
        "groupFilter": None,
        "orderBy": {"position": "ASC", "createTime": "DESC"},
        "filterGroup": [filters] if filters else [],
        "search": {"keyword": keyword, "aliases": []} if keyword else None,
        "pagination": {"limit": limit, "preciseCount": True},
        "_limit": limit,
    }


def _work_item_response(
    payload: dict[str, Any], variables: dict[str, Any]
) -> dict[str, Any]:
    limit = bounded_int(variables.get("_limit"), minimum=1)
    raw, total, truncated, cursor = page_items(payload, collection="tasks", limit=limit)
    return normalized_list(
        "items",
        [normalize_work_item(item) for item in raw],
        total=total,
        truncated=truncated,
        next_cursor=cursor,
    )


def _detail_variables(arguments: dict[str, Any], _context: dict[str, Any]) -> dict[str, Any]:
    return {"key": f"task-{arguments['work_item_uuid']}"}


def _detail_response(payload: dict[str, Any], _variables: dict[str, Any]) -> dict[str, Any]:
    data = require_mapping(payload.get("data"))
    task = require_mapping(data.get("task"))
    related_raw = task.get("relatedTasks", [])
    related = require_list(related_raw)
    output: dict[str, Any] = {
        "work_item": normalize_work_item(task),
        "related_items": [normalize_work_item(item) for item in related[:100]],
        "untrusted_data": True,
    }
    description = task.get("descriptionText")
    if isinstance(description, str):
        output["description"] = description[:4000]
    return output


PROJECT_SEARCH_OPERATION: Final = FixedGraphqlOperation(
    PROJECT_SEARCH,
    "projects-group-list-for-project-view",
    load_graphql_document("project_search.graphql"),
    _project_variables,
    _project_response,
)
ISSUE_TYPE_LIST_OPERATION: Final = FixedGraphqlOperation(
    ISSUE_TYPE_LIST,
    "issueTypeScopes",
    load_graphql_document("issue_type_list.graphql"),
    lambda arguments, context: {
        **_issue_type_variables(arguments, context),
        "_limit": arguments["limit"],
    },
    _issue_type_response,
)
WORK_ITEM_QUERY_OPERATION: Final = FixedGraphqlOperation(
    WORK_ITEM_QUERY,
    "group-task-data",
    load_graphql_document("work_item_query.graphql"),
    _work_item_variables,
    _work_item_response,
)
SPRINT_WORK_ITEM_QUERY_OPERATION: Final = FixedGraphqlOperation(
    SPRINT_WORK_ITEM_QUERY,
    "group-task-data",
    load_graphql_document("sprint_work_item_query.graphql"),
    _work_item_variables,
    _work_item_response,
)
WORK_ITEM_DETAIL_OPERATION: Final = FixedGraphqlOperation(
    WORK_ITEM_DETAIL,
    "Task",
    load_graphql_document("work_item_detail.graphql"),
    _detail_variables,
    _detail_response,
)

BUSINESS_GRAPHQL_OPERATIONS: Final = (
    PROJECT_SEARCH_OPERATION,
    ISSUE_TYPE_LIST_OPERATION,
    WORK_ITEM_QUERY_OPERATION,
    SPRINT_WORK_ITEM_QUERY_OPERATION,
    WORK_ITEM_DETAIL_OPERATION,
)
