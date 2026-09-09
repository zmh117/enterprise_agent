from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from services.ones_mcp_server.provider.graphql.client import OnesGraphqlClient
from services.ones_mcp_server.provider.graphql import documents
from services.ones_mcp_server.provider.graphql.documents import load_graphql_document
from services.ones_mcp_server.provider.graphql.operation import GraphqlOperationRegistry
from services.ones_mcp_server.provider.graphql.operations.business_queries import (
    PROJECT_SEARCH_OPERATION,
    SPRINT_WORK_ITEM_QUERY_OPERATION,
    WORK_ITEM_QUERY_OPERATION,
)
from services.ones_mcp_server.provider.graphql.operations.test_queries import (
    TEST_PLAN_LIST_OPERATION,
    TESTCASE_LIBRARY_LIST_OPERATION,
    TESTCASE_MODULE_CASES_OPERATION,
    TESTCASE_PLAN_CASES_OPERATION,
)
from services.ones_mcp_server.provider.graphql.operations.normalization import page_items
from services.ones_mcp_server.provider.graphql.operations.work_item_search import (
    WORK_ITEM_SEARCH_DOCUMENT,
    WORK_ITEM_SEARCH_OPERATION,
    WORK_ITEM_SEARCH_OPERATION_CODE,
    WORK_ITEM_SEARCH_PATH,
)


class _RecordingHttp:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def post_json(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        headers: dict[str, str],
        query: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {"path": path, "payload": payload, "headers": headers, "query": query}
        )
        return self.response


@dataclass(frozen=True)
class _SecondQuery:
    code: str = "project_summary"
    path_template: str = "/project/api/project/summary/graphql"
    query_type: str = ""
    document: str = "query ProjectSummary($team_id: String!) { projectSummary(teamId: $team_id) }"

    def build_variables(
        self,
        _arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        return {"team_id": context["team_id"]}

    def parse_response(
        self,
        payload: dict[str, Any],
        *,
        variables: dict[str, Any],
    ) -> dict[str, Any]:
        return {"payload": payload, "team_id": variables["team_id"]}


def test_graphql_registry_supports_multiple_code_owned_operations() -> None:
    registry = GraphqlOperationRegistry((WORK_ITEM_SEARCH_OPERATION, _SecondQuery()))

    assert registry.codes == ("project_summary", "work_item_search")
    assert registry.require("work_item_search") is WORK_ITEM_SEARCH_OPERATION
    assert registry.require("project_summary").document.startswith("query ProjectSummary(")


def test_graphql_client_uses_registered_document_path_and_variables_only() -> None:
    http = _RecordingHttp(
        {
            "data": {
                "buckets": [
                    {
                        "tasks": [
                            {
                                "number": 1,
                                "name": "Bounded result",
                                "issueType": {"uuid": "Rbk6XNBr"},
                            }
                        ],
                        "pageInfo": {
                            "count": 1,
                            "totalCount": 1,
                            "endCursor": "cursor-1",
                            "hasNextPage": False,
                            "preciseCount": True,
                        },
                    }
                ]
            }
        }
    )
    client = OnesGraphqlClient(
        http,  # type: ignore[arg-type]
        GraphqlOperationRegistry((WORK_ITEM_SEARCH_OPERATION,)),
    )

    result = client.execute(
        WORK_ITEM_SEARCH_OPERATION_CODE,
        arguments={
            "keyword": "fixed",
            "issue_type": "task",
            "limit": 5,
            "query": "mutation CallerControlled { forbidden }",
        },
        context={"user_id": "ones-user", "team_id": "ones-team"},
        headers={"Ones-Auth-Token": "not-persisted-test-token"},
    )

    assert http.calls[0]["path"] == WORK_ITEM_SEARCH_PATH.format(team_uuid="ones-team")
    assert http.calls[0]["query"] == {"t": "group-task-data"}
    assert http.calls[0]["payload"] == {
        "query": WORK_ITEM_SEARCH_DOCUMENT,
        "variables": {
            "groupBy": {"tasks": {}},
            "groupOrderBy": None,
            "groupFilter": None,
            "orderBy": {"position": "ASC", "createTime": "DESC"},
            "filterGroup": [
                {"name_match": "fixed", "issueType_in": ["Rbk6XNBr"]}
            ],
            "pagination": {"limit": 5, "after": "", "preciseCount": True},
        },
    }
    assert result.output["items"][0]["name"] == "Bounded result"
    assert result.output["items"][0]["type"] == "task"
    assert result.output["_provider_cursor"] == "cursor-1"


def test_work_item_search_injects_only_the_server_resolved_provider_cursor() -> None:
    http = _RecordingHttp(
        {
            "data": {
                "buckets": [
                    {
                        "tasks": [],
                        "pageInfo": {
                            "count": 0,
                            "totalCount": 50,
                            "endCursor": "",
                            "hasNextPage": False,
                            "preciseCount": True,
                        },
                    }
                ]
            }
        }
    )
    client = OnesGraphqlClient(
        http,  # type: ignore[arg-type]
        GraphqlOperationRegistry((WORK_ITEM_SEARCH_OPERATION,)),
    )

    client.execute(
        WORK_ITEM_SEARCH_OPERATION_CODE,
        arguments={
            "keyword": "fixed",
            "issue_type": "task",
            "limit": 20,
            "provider_cursor": "provider-page-2",
            "cumulative_returned": 50,
        },
        context={"user_id": "ones-user", "team_id": "ones-team"},
        headers={"Ones-Auth-Token": "not-persisted-test-token"},
    )

    assert http.calls[0]["payload"]["variables"]["pagination"] == {
        "limit": 20,
        "after": "provider-page-2",
        "preciseCount": True,
    }


def test_graphql_registry_rejects_arbitrary_or_mutating_operations() -> None:
    with pytest.raises(ValueError):
        GraphqlOperationRegistry(())

    with pytest.raises(ValueError):
        GraphqlOperationRegistry(
            (
                _SecondQuery(),
                _SecondQuery(document="mutation ProjectSummary { forbidden }"),
            )
        )

    with pytest.raises(KeyError):
        GraphqlOperationRegistry((WORK_ITEM_SEARCH_OPERATION,)).require("caller_supplied")


def test_work_item_document_is_loaded_from_the_code_owned_resource() -> None:
    expected = load_graphql_document("work_item_search.graphql")

    assert WORK_ITEM_SEARCH_DOCUMENT == expected
    assert "workItems(" not in expected
    assert "tasks(" in expected
    assert "$filterGroup" in expected
    assert "$pagination" in expected


def test_graphql_client_rejects_provider_variables_not_consumed_by_document() -> None:
    @dataclass(frozen=True)
    class _UnusedVariableQuery(_SecondQuery):
        def build_variables(
            self,
            _arguments: dict[str, Any],
            context: dict[str, Any],
        ) -> dict[str, Any]:
            return {"team_id": context["team_id"], "unused": "must-fail"}

    client = OnesGraphqlClient(
        _RecordingHttp({}),  # type: ignore[arg-type]
        GraphqlOperationRegistry((_UnusedVariableQuery(),)),
    )

    with pytest.raises(ValueError, match="variables do not match"):
        client.build_request(
            "project_summary",
            arguments={},
            context={"team_id": "ones-team"},
        )


def test_graphql_document_loader_fails_for_missing_empty_or_unsafe_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="missing"):
        load_graphql_document("missing.graphql")
    with pytest.raises(ValueError, match="name"):
        load_graphql_document("../work_item_search.graphql")

    class _EmptyResource:
        def joinpath(self, _filename: str) -> _EmptyResource:
            return self

        def read_text(self, *, encoding: str) -> str:
            assert encoding == "utf-8"
            return " \n"

    monkeypatch.setattr(documents.resources, "files", lambda _package: _EmptyResource())
    with pytest.raises(ValueError, match="empty"):
        load_graphql_document("empty.graphql")


@pytest.mark.parametrize(
    ("operation", "arguments", "limit"),
    (
        (
            PROJECT_SEARCH_OPERATION,
            {"keyword": "", "limit": 100},
            100,
        ),
        (WORK_ITEM_QUERY_OPERATION, {"limit": 100}, 100),
        (
            SPRINT_WORK_ITEM_QUERY_OPERATION,
            {"project_uuid": "project", "sprint_uuid": "sprint", "limit": 100},
            100,
        ),
        (TESTCASE_LIBRARY_LIST_OPERATION, {"limit": 100}, 100),
        (TEST_PLAN_LIST_OPERATION, {"limit": 100}, 100),
        (
            TESTCASE_MODULE_CASES_OPERATION,
            {
                "source": "module",
                "source_uuid": "module",
                "library_uuid": "library",
                "limit": 200,
            },
            200,
        ),
        (
            TESTCASE_PLAN_CASES_OPERATION,
            {"source": "plan", "source_uuid": "plan", "limit": 200},
            200,
        ),
    ),
)
def test_graphql_bucket_operations_inject_exact_server_pagination(
    operation: Any,
    arguments: dict[str, Any],
    limit: int,
) -> None:
    client = OnesGraphqlClient(
        _RecordingHttp({}),  # type: ignore[arg-type]
        GraphqlOperationRegistry((operation,)),
    )

    request = client.build_request(
        operation.code,
        arguments={
            **arguments,
            "provider_cursor": "provider-page-2",
            "cumulative_returned": limit,
        },
        context={"team_id": "ones-team"},
    )

    assert request["variables"]["pagination"] == {
        "limit": limit,
        "after": "provider-page-2",
        "preciseCount": True,
    }
    assert "pagination: $pagination" in operation.document
    assert 'after: ""' not in operation.document


def test_graphql_collection_limits_preserve_the_provider_page_probe_boundary() -> None:
    assert "projects(limit: 101" in PROJECT_SEARCH_OPERATION.document
    assert "tasks(" in WORK_ITEM_QUERY_OPERATION.document
    assert "limit: 101" in WORK_ITEM_QUERY_OPERATION.document
    assert "limit: 101" in SPRINT_WORK_ITEM_QUERY_OPERATION.document
    assert "testcasePlans(" in TEST_PLAN_LIST_OPERATION.document
    assert "limit: 101" in TEST_PLAN_LIST_OPERATION.document
    assert "testcaseCases(" in TESTCASE_MODULE_CASES_OPERATION.document
    assert "limit: 201" in TESTCASE_MODULE_CASES_OPERATION.document
    assert "testcasePlanCases(" in TESTCASE_PLAN_CASES_OPERATION.document
    assert "limit: 201" in TESTCASE_PLAN_CASES_OPERATION.document


def test_provider_total_count_cannot_create_a_false_continuation() -> None:
    items, total, truncated, cursor = page_items(
        {
            "data": {
                "buckets": [
                    {
                        "tasks": [{"uuid": "task-1"}],
                        "pageInfo": {
                            "count": 1,
                            "totalCount": 101,
                            "endCursor": "provider-terminal",
                            "hasNextPage": False,
                        },
                    }
                ]
            }
        },
        collection="tasks",
        limit=100,
        prior_count=0,
    )

    assert items == [{"uuid": "task-1"}]
    assert total == 101
    assert truncated is False
    assert cursor == "provider-terminal"
