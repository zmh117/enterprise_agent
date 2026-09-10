"""Synthetic values preserving field shapes/units observed in ones_mock/ones.

Never import the captured documents: they contain private headers and business
data. These cases deliberately test the parser boundary without a live service.
"""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

from jsonschema import Draft202012Validator
import pytest

from app.shared.exceptions import AppError
from app.shared.ones_tool_contracts import SPRINT_SCHEMA
from services.ones_mcp_server.provider.graphql.client import OnesGraphqlClient
from services.ones_mcp_server.provider.graphql.operation import GraphqlOperationRegistry
from services.ones_mcp_server.provider.graphql.operations.business_queries import (
    BUSINESS_GRAPHQL_OPERATIONS,
    WORK_ITEM_QUERY,
    _detail_response as _work_item_detail_response,
    _work_item_response,
)
from services.ones_mcp_server.provider.graphql.operations.normalization import (
    normalize_work_item,
    timestamp_text,
)
from services.ones_mcp_server.provider.graphql.operations.test_queries import (
    _case_list_response,
    _detail_response,
)
from services.ones_mcp_server.provider.rest.operations.basic_queries import (
    PROJECT_SPRINTS_OPERATION,
    WORK_ITEM_MESSAGES_OPERATION,
)


def _page(collection: str, rows: list[dict]) -> dict:
    return {
        "data": {
            "buckets": [
                {
                    collection: rows,
                    "pageInfo": {
                        "count": len(rows),
                        "totalCount": len(rows),
                        "hasNextPage": False,
                        "endCursor": "",
                        "unstable": False,
                    },
                }
            ]
        }
    }


def _task(index: int = 1) -> dict:
    return {
        "uuid": f"SYNTHETIC-TASK-{index}",
        "number": index,
        "name": "Synthetic task",
        "project": {"uuid": "P"},
        "issueType": {"uuid": "I"},
        "status": {"uuid": "S", "name": "New", "category": "to_do"},
    }


@pytest.mark.parametrize(
    "field,target", [("sprint", "sprint"), ("owner", "owner"), ("assign", "assignee")]
)
@pytest.mark.parametrize(
    "empty", [None, {}, {"uuid": "", "name": ""}, {"uuid": None, "name": None}]
)
def test_empty_optional_relations_do_not_drop_the_51st_work_item(
    field: str, target: str, empty: object
) -> None:
    rows = [_task(index) for index in range(51)]
    rows[-1][field] = empty
    result = _work_item_response(_page("tasks", rows), {"_limit": 200})
    assert result["returned"] == result["total"] == 51
    assert result["truncated"] is False
    assert result["items"][-1]["uuid"] == rows[-1]["uuid"]
    assert target not in result["items"][-1]


def test_detail_and_related_work_items_share_optional_relation_normalization() -> None:
    task = _task()
    task.update(sprint={"uuid": "", "name": ""}, owner={}, assign=None)
    task["relatedTasks"] = [dict(_task(2), sprint={}, owner=None, assign={"uuid": "", "name": ""})]
    result = _work_item_detail_response({"data": {"task": task}}, {})
    for item in [result["work_item"], *result["related_items"]]:
        assert not {"sprint", "owner", "assignee"}.intersection(item)


@pytest.mark.parametrize("field", ["sprint", "owner", "assign"])
@pytest.mark.parametrize(
    "invalid",
    [
        "",
        [],
        {"uuid": "", "name": "present"},
        {"uuid": "U", "name": ""},
        {"uuid": 0, "name": ""},
        {"uuid": "U" * 129, "name": "N"},
    ],
)
def test_malformed_optional_relations_remain_strict(field: str, invalid: object) -> None:
    task = dict(_task(), **{field: invalid})
    with pytest.raises(AppError) as caught:
        normalize_work_item(task, path="data.task")
    assert caught.value.error_code == "ones_provider_schema_invalid"
    assert f"data.task.{field}" in caught.value.safe_message


@pytest.mark.parametrize("field", ["project", "issueType", "status"])
def test_empty_required_relations_remain_invalid(field: str) -> None:
    with pytest.raises(AppError) as caught:
        normalize_work_item(dict(_task(), **{field: {"uuid": "", "name": ""}}))
    assert caught.value.error_code == "ones_provider_schema_invalid"


def test_populated_optional_relations_are_preserved() -> None:
    reference = {"uuid": "U", "name": "Synthetic reference"}
    result = normalize_work_item(dict(_task(), sprint=reference, owner=reference, assign=reference))
    assert result["sprint"] == result["owner"] == result["assignee"] == reference


@pytest.mark.parametrize(
    "raw,percentage", [(0, 0), (2_500_000, 25), (3_333_333, 33.33333), (10_000_000, 100)]
)
def test_sprint_fixed_point_progress_and_seconds(raw: int, percentage: float) -> None:
    payload = {
        "sprint": {
            "sprints": [
                {
                    "uuid": "SYNTHETIC-SPRINT",
                    "project_uuid": "SYNTHETIC-PROJECT",
                    "title": "Synthetic sprint",
                    "progress": raw,
                    "start_time": 1_767_225_600,
                    "end_time": 1_767_312_000,
                    "statuses": [{"category": "done", "is_current_status": True}],
                }
            ]
        }
    }
    output = PROJECT_SPRINTS_OPERATION.parse_response(
        payload, project_uuid="SYNTHETIC-PROJECT", limit=100
    )
    sprint = output["sprints"][0]
    assert sprint["progress"] == percentage
    assert sprint["start_at"] == "2026-01-01T00:00:00+00:00"
    assert sprint["end_at"] == "2026-01-02T00:00:00+00:00"
    Draft202012Validator(SPRINT_SCHEMA).validate(sprint)


@pytest.mark.parametrize("raw", [-1, 10_000_001, True, 2.5, "private-progress-value"])
def test_invalid_progress_reports_field_not_value(raw: object) -> None:
    payload = {"sprint": {"sprints": [{"uuid": "S", "title": "Synthetic", "progress": raw}]}}
    with pytest.raises(AppError) as caught:
        PROJECT_SPRINTS_OPERATION.parse_response(payload, project_uuid="P", limit=100)
    assert caught.value.error_code == "ones_provider_schema_invalid"
    assert "sprint.sprints[0].progress" in caught.value.safe_message
    assert "private-progress-value" not in caught.value.safe_message


def test_testcase_seconds_and_message_microseconds_use_distinct_units() -> None:
    payload = {
        "data": {
            "testcaseCases": [{"uuid": "C", "name": "Synthetic", "createTime": 1_767_225_600}],
            "testcaseCaseSteps": [],
        }
    }
    assert _detail_response(payload, {})["test_case"]["created_at"] == "2026-01-01T00:00:00+00:00"
    output = WORK_ITEM_MESSAGES_OPERATION.parse_response(
        {
            "messages": [{"uuid": "M", "type": "system", "send_time": 1_767_225_600_123_456}],
            "count": 1,
        },
        limit=100,
    )
    assert output["messages"][0]["sent_at"] == "2026-01-01T00:00:00.123456+00:00"
    assert (
        timestamp_text(1_767_225_600_123, unit="milliseconds") == "2026-01-01T00:00:00.123000+00:00"
    )


@pytest.mark.parametrize("collection", ["testcaseCases", "testcasePlanCases"])
@pytest.mark.parametrize(
    "change,code",
    [
        ({"unstable": True}, "ones_pagination_unstable"),
        ({"count": 21}, "ones_provider_page_size_invalid"),
        ({"hasNextPage": "false"}, "ones_provider_schema_invalid"),
        ({"endCursor": "x" * 513}, "ones_provider_schema_invalid"),
    ],
)
def test_case_pages_enforce_shared_integrity(collection: str, change: dict, code: str) -> None:
    item = {"uuid": "C"} if collection == "testcaseCases" else {"testcaseCase": {"uuid": "C"}}
    payload = _page(collection, [item])
    payload["data"]["buckets"][0]["pageInfo"].update(change)
    with pytest.raises(AppError) as caught:
        _case_list_response(payload, {"_limit": 200, "_case_collection": collection})
    assert caught.value.error_code == code


def test_case_page_never_slices_before_advancing_cursor() -> None:
    payload = _page("testcaseCases", [{"uuid": "C1"}, {"uuid": "C2"}])
    with pytest.raises(AppError) as caught:
        _case_list_response(payload, {"_limit": 1, "_case_collection": "testcaseCases"})
    assert caught.value.error_code == "ones_provider_page_size_invalid"
    payload["data"]["buckets"].append(deepcopy(payload["data"]["buckets"][0]))
    with pytest.raises(AppError) as caught:
        _case_list_response(payload, {"_limit": 200, "_case_collection": "testcaseCases"})
    assert caught.value.error_code == "ones_provider_schema_invalid"


def test_work_item_field_failure_preserves_safe_indexed_location() -> None:
    payload = _page(
        "tasks",
        [
            {
                "uuid": "T",
                "number": 1,
                "name": "Private business name",
                "project": {"uuid": "P"},
                "issueType": {"uuid": "I"},
                "status": None,
            }
        ],
    )
    with pytest.raises(AppError) as caught:
        _work_item_response(payload, {"_limit": 200})
    assert "data.buckets[0].tasks[0].status" in caught.value.safe_message
    assert "null" in caught.value.safe_message
    assert "Private business name" not in caught.value.safe_message


@pytest.mark.parametrize("with_data", [False, True])
def test_graphql_errors_fail_before_any_partial_result(with_data: bool) -> None:
    payload = _page("tasks", []) if with_data else {}
    payload["errors"] = [
        {"message": "private-upstream-message", "extensions": {"token": "private-canary"}}
    ]
    client = OnesGraphqlClient(
        SimpleNamespace(post_json=lambda *args, **kwargs: payload),
        GraphqlOperationRegistry(BUSINESS_GRAPHQL_OPERATIONS),
    )
    with pytest.raises(AppError) as caught:
        client.execute(
            WORK_ITEM_QUERY, arguments={"limit": 200}, context={"team_id": "T"}, headers={}
        )
    assert caught.value.error_code == "ones_provider_graphql_error"
    assert "private" not in caught.value.safe_message
