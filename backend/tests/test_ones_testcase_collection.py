from __future__ import annotations

import json
from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator

from app.python_runtime.job_sandbox import JobSandboxError, JobSandboxManager
from app.python_runtime.ones_result_bridge import materialize_result
from app.shared.ones_tool_contracts import (
    ONES_COLLECTED_LIST_FIELDS,
    ONES_COLLECTION_LIMITS,
    ONES_TOOL_CONTRACTS,
)
from services.ones_mcp_server.errors import OnesMcpError
from services.ones_mcp_server.provider.graphql import collection
from services.ones_mcp_server.provider.graphql.client import OnesGraphqlClient
from services.ones_mcp_server.provider.graphql.operation import GraphqlOperationRegistry
from services.ones_mcp_server.provider.graphql.operations.test_queries import (
    TEST_GRAPHQL_OPERATIONS,
)
from tests.test_ones_mcp_runtime import _fixture


_CASES = (
    ("testcase_library_service", "ones_list_testcase_libraries", {}, "testcaseLibraries"),
    (
        "testcase_module_service",
        "ones_list_testcase_modules",
        {"library_uuid": "LIBRARY"},
        "testcaseModules",
    ),
    ("test_plan_service", "ones_list_test_plans", {}, "testcasePlans"),
    (
        "test_case_service",
        "ones_query_test_cases",
        {"source": "module", "source_uuid": "MODULE", "library_uuid": "LIBRARY"},
        "testcaseCases",
    ),
    (
        "test_case_service",
        "ones_query_test_cases",
        {"source": "plan", "source_uuid": "PLAN"},
        "testcasePlanCases",
    ),
)


class _TestAssetHttp:
    """Synthetic fixed-response transport; never reads provider settings or connects."""

    def __init__(self, kind, count, page_size):
        self.kind, self.count, self.page_size = kind, count, page_size
        self.requests = []

    def post_json(self, path, payload, **kwargs):
        variables = deepcopy(payload["variables"])
        self.requests.append(variables)
        if self.kind == "testcaseModules":
            assert "pagination" not in variables
            start, end = 0, self.count
        else:
            pagination = variables["pagination"]
            start = int(pagination["after"] or 0)
            end = min(start + self.page_size, start + pagination["limit"], self.count)
        rows = []
        for index in range(start, end):
            row = {"uuid": f"SYNTHETIC-{index}"}
            if self.kind == "testcasePlanCases":
                row = {"testcaseCase": row}
            elif self.kind in {"testcaseLibraries", "testcasePlans", "testcaseModules"}:
                row["name"] = "合成测试"
                if self.kind == "testcaseModules":
                    row["path"] = f"/{index}"
            rows.append(row)
        if self.kind == "testcaseModules":
            return {"data": {self.kind: rows}}
        return {
            "data": {
                "buckets": [
                    {
                        self.kind: rows,
                        "pageInfo": {
                            "count": len(rows),
                            "totalCount": self.count,
                            "hasNextPage": end < self.count,
                            "endCursor": str(end),
                            "unstable": False,
                        },
                    }
                ]
            }
        }


@pytest.mark.parametrize("service_key,name,arguments,kind", _CASES)
@pytest.mark.parametrize("count", [9999, 10000, 10001])
@pytest.mark.parametrize("page_size", [50, 200])
def test_test_asset_collection_boundaries_and_sandbox(
    service_key, name, arguments, kind, count, page_size, tmp_path
):
    fixture = _fixture(capabilities=(name,))
    service = fixture[service_key]
    http = _TestAssetHttp(kind, count, page_size)
    service.graphql = OnesGraphqlClient(http, GraphqlOperationRegistry(TEST_GRAPHQL_OPERATIONS))
    result = service.invoke(
        claims=service.authenticate(fixture["token"]),
        arguments=arguments,
        correlation_id="test-assets-collection",
        invocation_id=f"{fixture['job'].id}.attempt-{fixture['job'].retry_count}",
    )
    field = ONES_COLLECTED_LIST_FIELDS[name]
    returned = min(count, 10000)
    assert result["returned"] == result["cumulative_returned"] == returned
    assert result["total"] == count
    assert len(result[field]) == returned
    assert result[field][-1]["uuid"] == f"SYNTHETIC-{returned - 1}"
    assert result["truncated"] is result["pagination_limit_reached"] is (count > 10000)
    assert "next_cursor" not in result and "_provider_cursor" not in result
    expected_pages = 1 if kind == "testcaseModules" else (returned + page_size - 1) // page_size
    assert len(http.requests) == expected_pages
    if kind != "testcaseModules":
        for index, variables in enumerate(http.requests):
            pagination = variables["pagination"]
            assert 1 <= pagination["limit"] <= 200
            assert pagination["after"] == (str(index * page_size) if index else "")
            assert {k: v for k, v in variables.items() if k != "pagination"} == {
                k: v for k, v in http.requests[0].items() if k != "pagination"
            }
    Draft202012Validator(service.output_schema).validate(result)

    if page_size == 50 and count >= 10000:
        sandbox = JobSandboxManager(tmp_path).create("job-test-assets")
        summary = materialize_result(sandbox, name, result)
        path = sandbox.path / summary["result_file"]
        assert summary["returned"] == 10000
        assert summary["complete"] is (count == 10000)
        assert field not in summary and len(json.dumps(summary)) < 1000
        assert "SYNTHETIC-9999" in path.read_text()
        sandbox.authorize_tool("Read", {"file_path": str(path)})
        with pytest.raises(JobSandboxError):
            sandbox.authorize_tool("Write", {"file_path": str(path), "content": "overwrite"})
        sandbox.cleanup()
        assert not path.exists()


def test_graphql_collection_output_limits_match_tool_scope():
    expected = {
        "ones_work_item_search": 1000,
        "ones_search_projects": 1000,
        "ones_list_issue_types": 1000,
        "ones_query_work_items": 10000,
        "ones_query_work_items_with_custom_options": 1000,
        "ones_list_testcase_libraries": 10000,
        "ones_list_testcase_modules": 10000,
        "ones_list_test_plans": 10000,
        "ones_query_test_cases": 10000,
    }
    assert ONES_COLLECTION_LIMITS == expected
    for name, maximum in expected.items():
        contract = ONES_TOOL_CONTRACTS[name]
        properties = contract.output_schema["properties"]
        assert properties[ONES_COLLECTED_LIST_FIELDS[name]]["maxItems"] == maximum
        assert properties["returned"]["maximum"] == maximum
        assert properties["cumulative_returned"]["maximum"] == maximum
        assert "limit" not in contract.input_schema["properties"]
        assert "cursor" not in contract.input_schema["properties"]


@pytest.mark.parametrize(
    "service_key,name,arguments,kind", [case for case in _CASES if case[3] != "testcaseModules"]
)
def test_test_asset_page_budget_is_still_bounded(service_key, name, arguments, kind):
    fixture = _fixture(capabilities=(name,))
    service = fixture[service_key]
    http = _TestAssetHttp(kind, 10001, 1)
    service.graphql = OnesGraphqlClient(http, GraphqlOperationRegistry(TEST_GRAPHQL_OPERATIONS))
    with pytest.raises(OnesMcpError) as error:
        service.invoke(
            claims=service.authenticate(fixture["token"]),
            arguments=arguments,
            correlation_id="test-assets-page-budget",
            invocation_id=f"{fixture['job'].id}.attempt-{fixture['job'].retry_count}",
        )
    assert error.value.error_code == "ones_collection_page_limit"
    assert len(http.requests) == 200


def test_default_collection_retains_50_page_budget():
    calls = []

    def fetch(arguments):
        calls.append(arguments)
        return {
            "items": [{"uuid": str(len(calls))}],
            "total": 1001,
            "truncated": True,
            "_provider_cursor": str(len(calls)),
        }

    with pytest.raises(OnesMcpError) as error:
        collection.collect_pages(fetch, {}, field="items")
    assert error.value.error_code == "ones_collection_page_limit"
    assert len(calls) == 50


@pytest.mark.parametrize("failure", ["size", "time"])
def test_expanded_collection_keeps_time_and_size_budgets(monkeypatch, failure):
    assert collection.MAX_SECONDS == 90
    assert collection.MAX_RESULT_BYTES == 8 * 1024 * 1024
    if failure == "time":
        times = iter([0, 91])
        monkeypatch.setattr(collection.time, "monotonic", lambda: next(times))
    else:
        monkeypatch.setattr(collection, "MAX_RESULT_BYTES", 1)
    with pytest.raises(OnesMcpError) as error:
        collection.collect_pages(
            lambda arguments: {"test_cases": [{"uuid": "ONE"}], "total": 1, "truncated": False},
            {},
            field="test_cases",
            max_results=10000,
            max_pages=200,
        )
    assert error.value.error_code == (
        "ones_collection_timeout" if failure == "time" else "ones_collection_size_exceeded"
    )
