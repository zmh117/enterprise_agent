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
    ordered_uuid_fingerprint,
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
    limit = int(arguments["limit"])
    return {
        "projectOrderBy": {"isPin": "DESC", "namePinyin": "ASC", "createTime": "DESC"},
        "projectFilterGroup": [filters],
        "groupBy": {"projects": {}},
        "orderBy": None,
        "pagination": {
            "limit": limit,
            "after": str(arguments.get("provider_cursor") or ""),
            "preciseCount": True,
        },
        "_limit": limit,
        "_cumulative_returned": int(arguments.get("cumulative_returned") or 0),
    }


def _project_response(payload: dict[str, Any], variables: dict[str, Any]) -> dict[str, Any]:
    limit = bounded_int(variables.get("_limit"), minimum=1)
    cumulative_returned = bounded_int(variables.get("_cumulative_returned", 0), minimum=0)
    raw, total, truncated, cursor = page_items(
        payload,
        collection="projects",
        limit=limit,
        prior_count=cumulative_returned,
    )
    projects: list[dict[str, Any]] = []
    for index, value in enumerate(raw):
        path = f"data.buckets[0].projects[{index}]"
        project: dict[str, Any] = {
            "uuid": bounded_string(value.get("uuid"), maximum=128, path=f"{path}.uuid"),
            "name": bounded_string(value.get("name"), maximum=300, path=f"{path}.name"),
            "archived": value.get("isArchive") is True,
            "sample": value.get("isSample") is True,
        }
        owner = optional_person(value.get("owner"), path=f"{path}.owner")
        if owner is not None:
            project["owner"] = owner
        if value.get("status") is not None:
            project["status"] = require_status(value.get("status"), path=f"{path}.status")
        projects.append(project)
    output = normalized_list("projects", projects, total=total, truncated=truncated)
    output["_provider_cursor"] = cursor
    return output


def _issue_type_variables(arguments: dict[str, Any], _context: dict[str, Any]) -> dict[str, Any]:
    return {
        "filter": {
            "scope_equal": arguments["project_uuid"],
            "scopeType_equal": 1,
        }
    }


def _issue_type_response(payload: dict[str, Any], variables: dict[str, Any]) -> dict[str, Any]:
    data = require_mapping(payload.get("data"), path="data")
    raw_items = require_list(data.get("issueTypeScopes"), path="data.issueTypeScopes")
    limit = bounded_int(variables.get("_limit", 100), minimum=1)
    offset = bounded_int(variables.get("_offset", 0), minimum=0)
    output: list[dict[str, Any]] = []
    uuids: list[str] = []
    for index, raw in enumerate(raw_items):
        path = f"data.issueTypeScopes[{index}]"
        item = require_mapping(raw, path=path)
        issue_type = require_mapping(item.get("issueType"), path=f"{path}.issueType")
        sub = issue_type.get("subIssueType", False)
        if type(sub) is not bool:
            raise invalid_provider_response("ones_provider_schema_invalid")
        uuid = bounded_string(issue_type.get("uuid"), maximum=128, path=f"{path}.issueType.uuid")
        uuids.append(uuid)
        output.append(
            {
                "uuid": uuid,
                "scope_uuid": bounded_string(item.get("uuid"), maximum=128, path=f"{path}.uuid"),
                "name": bounded_string(
                    issue_type.get("name"), maximum=200, path=f"{path}.issueType.name"
                ),
                "sub_issue_type": sub,
            }
        )
    page = output[offset : offset + limit]
    next_offset = offset + len(page)
    result = normalized_list(
        "issue_types",
        page,
        total=len(raw_items),
        truncated=next_offset < len(raw_items),
    )
    result["_next_offset"] = next_offset
    result["_collection_fingerprint"] = ordered_uuid_fingerprint(uuids)
    return result


def _calendar_date(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("ONES work item time filter is invalid") from None
    if parsed.tzinfo is None:
        raise ValueError("ONES work item time filter is invalid")
    return parsed.date().isoformat()


def _work_item_variables(arguments: dict[str, Any], _context: dict[str, Any]) -> dict[str, Any]:
    filters: dict[str, Any] = {}
    for argument, provider in (
        ("issue_type_uuids", "issueType_in"),
        ("status_uuids", "status_in"),
        ("status_categories", "statusCategory_in"),
        ("assignee_uuids", "assign_in"),
    ):
        if arguments.get(argument):
            filters[provider] = list(arguments[argument])
    for custom_filter in arguments.get("custom_option_filters") or []:
        filters[str(custom_filter["filter_key"])] = list(custom_filter["option_uuids"])
    if arguments.get("project_uuid"):
        filters["project_in"] = [arguments["project_uuid"]]
    if arguments.get("sprint_uuid"):
        filters["sprint_in"] = [arguments["sprint_uuid"]]
    keyword = str(arguments.get("keyword") or "").strip()
    if keyword:
        filters["name_match"] = keyword
    created_from = arguments.get("created_from")
    created_to = arguments.get("created_to")
    if created_from or created_to:
        time_filter: dict[str, str] = {}
        if created_from:
            time_filter["gte"] = _calendar_date(str(created_from))
        if created_to:
            time_filter["lte"] = _calendar_date(str(created_to))
        filters["createTime_range"] = time_filter
    limit = int(arguments["limit"])
    return {
        "groupBy": {"tasks": {}},
        "groupOrderBy": None,
        "groupFilter": None,
        "orderBy": {"position": "ASC", "createTime": "DESC"},
        "filterGroup": [filters] if filters else [],
        "pagination": {
            "limit": limit,
            "after": str(arguments.get("provider_cursor") or ""),
            "preciseCount": True,
        },
        "_limit": limit,
        "_cumulative_returned": int(arguments.get("cumulative_returned") or 0),
    }


def _work_item_response(payload: dict[str, Any], variables: dict[str, Any]) -> dict[str, Any]:
    limit = bounded_int(variables.get("_limit"), minimum=1)
    cumulative_returned = bounded_int(variables.get("_cumulative_returned", 0), minimum=0)
    raw, total, truncated, cursor = page_items(
        payload,
        collection="tasks",
        limit=limit,
        prior_count=cumulative_returned,
    )
    output = normalized_list(
        "items",
        [
            normalize_work_item(item, path=f"data.buckets[0].tasks[{index}]")
            for index, item in enumerate(raw)
        ],
        total=total,
        truncated=truncated,
    )
    output["_provider_cursor"] = cursor
    return output


def _detail_variables(arguments: dict[str, Any], _context: dict[str, Any]) -> dict[str, Any]:
    return {"key": f"task-{arguments['work_item_uuid']}"}


def _detail_response(payload: dict[str, Any], _variables: dict[str, Any]) -> dict[str, Any]:
    data = require_mapping(payload.get("data"), path="data")
    task = require_mapping(data.get("task"), path="data.task")
    related_raw = task.get("relatedTasks", [])
    related = require_list(related_raw, path="data.task.relatedTasks")
    output: dict[str, Any] = {
        "work_item": normalize_work_item(task, path="data.task"),
        "related_items": [
            normalize_work_item(item, path=f"data.task.relatedTasks[{index}]")
            for index, item in enumerate(related[:100])
        ],
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
        "_offset": int(arguments.get("page_offset") or 0),
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
