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
    _work_item_response,
)
from services.ones_mcp_server.provider.graphql.operations.normalization import timestamp_text
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
