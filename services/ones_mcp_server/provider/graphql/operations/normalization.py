from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.shared.ones_tool_contracts import ONES_STATUS_CATEGORIES
from services.ones_mcp_server.errors import invalid_provider_response


def require_mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise invalid_provider_response("ones_provider_schema_invalid")
    return value


def require_list(value: object) -> list[Any]:
    if not isinstance(value, list):
        raise invalid_provider_response("ones_provider_schema_invalid")
    return value


def bounded_string(
    value: object,
    *,
    maximum: int,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str) or len(value) > maximum or (not allow_empty and not value):
        raise invalid_provider_response("ones_provider_schema_invalid")
    return value


def bounded_int(value: object, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise invalid_provider_response("ones_provider_schema_invalid")
    return value


def optional_person(value: object) -> dict[str, str] | None:
    if value is None:
        return None
    item = require_mapping(value)
    return {
        "uuid": bounded_string(item.get("uuid"), maximum=128),
        "name": bounded_string(item.get("name"), maximum=200),
    }


def require_status(value: object) -> dict[str, str]:
    item = require_mapping(value)
    category = bounded_string(item.get("category"), maximum=40)
    if category not in ONES_STATUS_CATEGORIES:
        raise invalid_provider_response("ones_provider_schema_invalid")
    return {
        "uuid": bounded_string(item.get("uuid"), maximum=128),
        "name": bounded_string(item.get("name"), maximum=200),
        "category": category,
    }


def timestamp_text(value: object) -> str:
    if isinstance(value, str):
        return bounded_string(value, maximum=64)
    if type(value) is not int or value < 0:
        raise invalid_provider_response("ones_provider_schema_invalid")
    divisor = 1_000_000 if value >= 100_000_000_000_000 else 1000
    try:
        return datetime.fromtimestamp(value / divisor, tz=UTC).isoformat()
    except (OverflowError, OSError, ValueError):
        raise invalid_provider_response("ones_provider_schema_invalid") from None


def page_items(
    payload: dict[str, Any],
    *,
    collection: str,
    limit: int,
) -> tuple[list[dict[str, Any]], int, bool, str]:
    data = require_mapping(payload.get("data"))
    buckets = require_list(data.get("buckets"))
    items: list[dict[str, Any]] = []
    total = 0
    truncated = False
    next_cursor = ""
    for raw_bucket in buckets:
        bucket = require_mapping(raw_bucket)
        raw_items = require_list(bucket.get(collection))
        items.extend(require_mapping(item) for item in raw_items)
        page = require_mapping(bucket.get("pageInfo"))
        count = bounded_int(page.get("count", len(raw_items)))
        bucket_total = bounded_int(page.get("totalCount", count))
        total += bucket_total
        has_next = page.get("hasNextPage", False)
        if type(has_next) is not bool:
            raise invalid_provider_response("ones_provider_schema_invalid")
        truncated = truncated or has_next or bucket_total > count
        cursor = page.get("endCursor")
        if cursor is not None:
            next_cursor = bounded_string(cursor, maximum=512, allow_empty=True)
    if len(items) > limit:
        items = items[:limit]
        truncated = True
    return items, total, truncated, next_cursor


def normalized_list(
    field: str,
    items: list[dict[str, Any]],
    *,
    total: int,
    truncated: bool,
    next_cursor: str = "",
) -> dict[str, Any]:
    result: dict[str, Any] = {
        field: items,
        "total": total,
        "returned": len(items),
        "truncated": truncated,
        "untrusted_data": True,
    }
    if truncated and next_cursor:
        result["next_cursor"] = next_cursor
    return result


def normalize_work_item(value: object) -> dict[str, Any]:
    item = require_mapping(value)
    project = require_mapping(item.get("project"))
    project_output: dict[str, Any] = {
        "uuid": bounded_string(project.get("uuid"), maximum=128)
    }
    if project.get("name") is not None:
        project_output["name"] = bounded_string(project.get("name"), maximum=300)
    issue_type = require_mapping(item.get("issueType"))
    issue_type_output: dict[str, Any] = {
        "uuid": bounded_string(issue_type.get("uuid"), maximum=128)
    }
    if issue_type.get("name") is not None:
        issue_type_output["name"] = bounded_string(issue_type.get("name"), maximum=200)
    output: dict[str, Any] = {
        "uuid": bounded_string(item.get("uuid"), maximum=128),
        "number": bounded_int(item.get("number")),
        "name": bounded_string(item.get("name"), maximum=500),
        "project": project_output,
        "issue_type": issue_type_output,
        "status": require_status(item.get("status")),
    }
    for source, target in (("owner", "owner"), ("assign", "assignee")):
        person = optional_person(item.get(source))
        if person is not None:
            output[target] = person
    sprint = item.get("sprint")
    if sprint is not None:
        sprint_item = require_mapping(sprint)
        output["sprint"] = {
            "uuid": bounded_string(sprint_item.get("uuid"), maximum=128),
            "name": bounded_string(sprint_item.get("name"), maximum=300),
        }
    if item.get("createTime") is not None:
        output["created_at"] = timestamp_text(item.get("createTime"))
    if item.get("serverUpdateStamp") is not None:
        output["updated_at"] = timestamp_text(item.get("serverUpdateStamp"))
    if item.get("subTaskCount") is not None:
        output["subtask_count"] = bounded_int(item.get("subTaskCount"))
    if item.get("subTaskDoneCount") is not None:
        output["subtask_done_count"] = bounded_int(item.get("subTaskDoneCount"))
    return output

