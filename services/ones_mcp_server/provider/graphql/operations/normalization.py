from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
from typing import Any, Literal

from app.shared.ones_tool_contracts import ONES_STATUS_CATEGORIES
from services.ones_mcp_server.errors import invalid_provider_field, invalid_provider_response


def require_mapping(value: object, *, path: str = "response") -> dict[str, Any]:
    if not isinstance(value, dict):
        raise invalid_provider_field(path, "对象", value)
    return value


def require_list(value: object, *, path: str = "response") -> list[Any]:
    if not isinstance(value, list):
        raise invalid_provider_field(path, "数组", value)
    return value


def bounded_string(
    value: object,
    *,
    maximum: int,
    allow_empty: bool = False,
    path: str = "response",
) -> str:
    if not isinstance(value, str) or len(value) > maximum or (not allow_empty and not value):
        expected = f"长度不超过{maximum}的{'字符串' if allow_empty else '非空字符串'}"
        raise invalid_provider_field(path, expected, value)
    return value


def bounded_int(value: object, *, minimum: int = 0, path: str = "response") -> int:
    if type(value) is not int or value < minimum:
        raise invalid_provider_field(path, f"不小于{minimum}的整数", value)
    return value


def optional_person(value: object, *, path: str = "person") -> dict[str, str] | None:
    if value is None:
        return None
    item = require_mapping(value, path=path)
    return {
        "uuid": bounded_string(item.get("uuid"), maximum=128, path=f"{path}.uuid"),
        "name": bounded_string(item.get("name"), maximum=200, path=f"{path}.name"),
    }


def require_status(value: object, *, path: str = "status") -> dict[str, str]:
    item = require_mapping(value, path=path)
    category = bounded_string(item.get("category"), maximum=40, path=f"{path}.category")
    if category not in ONES_STATUS_CATEGORIES:
        raise invalid_provider_field(f"{path}.category", "已支持的状态分类", category)
    return {
        "uuid": bounded_string(item.get("uuid"), maximum=128, path=f"{path}.uuid"),
        "name": bounded_string(item.get("name"), maximum=200, path=f"{path}.name"),
        "category": category,
    }


def timestamp_text(
    value: object,
    *,
    unit: Literal["seconds", "milliseconds", "microseconds"],
    path: str = "timestamp",
) -> str:
    if type(value) is not int or value < 0:
        raise invalid_provider_field(path, f"非负整数时间戳（{unit}）", value)
    multiplier = {"seconds": 1_000_000, "milliseconds": 1000, "microseconds": 1}[unit]
    try:
        return (
            datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=value * multiplier)
        ).isoformat()
    except (OverflowError, OSError, ValueError):
        raise invalid_provider_field(path, "有效日期范围内的时间戳", value) from None


def validate_graphql_response(payload: dict[str, Any]) -> None:
    errors = payload.get("errors")
    if errors is not None:
        require_list(errors, path="errors")
        if errors:
            raise invalid_provider_response("ones_provider_graphql_error")
    require_mapping(payload.get("data"), path="data")


def page_items(
    payload: dict[str, Any],
    *,
    collection: str,
    limit: int,
    prior_count: int = 0,
) -> tuple[list[dict[str, Any]], int, bool, str]:
    bounded_int(prior_count, minimum=0)
    validate_graphql_response(payload)
    data = require_mapping(payload.get("data"), path="data")
    buckets = require_list(data.get("buckets"), path="data.buckets")
    # All registered collection operations request an ungrouped bucket. A
    # cursor from one bucket must never be used to skip another bucket.
    if len(buckets) > 1:
        raise invalid_provider_field("data.buckets", "最多一个未分组bucket", buckets)
    items: list[dict[str, Any]] = []
    total = 0
    truncated = False
    next_cursor = ""
    for index, raw_bucket in enumerate(buckets):
        path = f"data.buckets[{index}]"
        bucket = require_mapping(raw_bucket, path=path)
        raw_items = require_list(bucket.get(collection), path=f"{path}.{collection}")
        items.extend(
            require_mapping(item, path=f"{path}.{collection}[{i}]")
            for i, item in enumerate(raw_items)
        )
        page = require_mapping(bucket.get("pageInfo"), path=f"{path}.pageInfo")
        count = bounded_int(page.get("count"), path=f"{path}.pageInfo.count")
        unstable = page.get("unstable", False)
        if type(unstable) is not bool or unstable:
            raise invalid_provider_response("ones_pagination_unstable")
        if count != len(raw_items):
            raise invalid_provider_response("ones_provider_page_size_invalid")
        bucket_total = bounded_int(page.get("totalCount"), path=f"{path}.pageInfo.totalCount")
        total += bucket_total
        has_next = page.get("hasNextPage")
        if type(has_next) is not bool:
            raise invalid_provider_field(f"{path}.pageInfo.hasNextPage", "布尔值", has_next)
        truncated = truncated or has_next
        cursor = page.get("endCursor")
        if cursor is not None:
            next_cursor = bounded_string(
                cursor, maximum=512, allow_empty=True, path=f"{path}.pageInfo.endCursor"
            )
    if len(items) > limit:
        # Slicing here would discard rows while advancing past them with the
        # provider endCursor, permanently skipping data on the next request.
        raise invalid_provider_response("ones_provider_page_size_invalid")
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


def ordered_uuid_fingerprint(uuids: list[str]) -> str:
    if len(set(uuids)) != len(uuids):
        raise invalid_provider_response("ones_provider_schema_invalid")
    canonical = json.dumps(uuids, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def normalize_work_item(value: object, *, path: str = "task") -> dict[str, Any]:
    item = require_mapping(value, path=path)
    project = require_mapping(item.get("project"), path=f"{path}.project")
    project_output: dict[str, Any] = {
        "uuid": bounded_string(project.get("uuid"), maximum=128, path=f"{path}.project.uuid")
    }
    if project.get("name") is not None:
        project_output["name"] = bounded_string(
            project.get("name"), maximum=300, path=f"{path}.project.name"
        )
    issue_type = require_mapping(item.get("issueType"), path=f"{path}.issueType")
    issue_type_output: dict[str, Any] = {
        "uuid": bounded_string(issue_type.get("uuid"), maximum=128, path=f"{path}.issueType.uuid")
    }
    if issue_type.get("name") is not None:
        issue_type_output["name"] = bounded_string(
            issue_type.get("name"), maximum=200, path=f"{path}.issueType.name"
        )
    output: dict[str, Any] = {
        "uuid": bounded_string(item.get("uuid"), maximum=128, path=f"{path}.uuid"),
        "number": bounded_int(item.get("number"), path=f"{path}.number"),
        "name": bounded_string(item.get("name"), maximum=500, path=f"{path}.name"),
        "project": project_output,
        "issue_type": issue_type_output,
        "status": require_status(item.get("status"), path=f"{path}.status"),
    }
    for source, target in (("owner", "owner"), ("assign", "assignee")):
        person = optional_person(item.get(source), path=f"{path}.{source}")
        if person is not None:
            output[target] = person
    sprint = item.get("sprint")
    if sprint is not None:
        sprint_item = require_mapping(sprint, path=f"{path}.sprint")
        output["sprint"] = {
            "uuid": bounded_string(
                sprint_item.get("uuid"), maximum=128, path=f"{path}.sprint.uuid"
            ),
            "name": bounded_string(
                sprint_item.get("name"), maximum=300, path=f"{path}.sprint.name"
            ),
        }
    if item.get("createTime") is not None:
        output["created_at"] = timestamp_text(
            item.get("createTime"), unit="microseconds", path=f"{path}.createTime"
        )
    if item.get("serverUpdateStamp") is not None:
        output["updated_at"] = timestamp_text(
            item.get("serverUpdateStamp"), unit="microseconds", path=f"{path}.serverUpdateStamp"
        )
    if item.get("subTaskCount") is not None:
        output["subtask_count"] = bounded_int(item.get("subTaskCount"), path=f"{path}.subTaskCount")
    if item.get("subTaskDoneCount") is not None:
        output["subtask_done_count"] = bounded_int(
            item.get("subTaskDoneCount"), path=f"{path}.subTaskDoneCount"
        )
    return output
