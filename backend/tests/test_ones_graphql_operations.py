from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from services.ones_mcp_server.provider.graphql.client import OnesGraphqlClient
from services.ones_mcp_server.provider.graphql.operation import GraphqlOperationRegistry
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
    ) -> dict[str, Any]:
        self.calls.append({"path": path, "payload": payload, "headers": headers})
        return self.response


@dataclass(frozen=True)
class _SecondQuery:
    code: str = "project_summary"
    path: str = "/project/api/project/items/graphql"
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
                "workItems": {
                    "items": [{"number": 1, "name": "Bounded result", "type": "task"}],
                    "total": 1,
                    "truncated": False,
                }
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

    assert http.calls[0]["path"] == WORK_ITEM_SEARCH_PATH
    assert http.calls[0]["payload"] == {
        "query": WORK_ITEM_SEARCH_DOCUMENT,
        "variables": {
            "keyword": "fixed",
            "issue_type": "task",
            "limit": 5,
            "user_id": "ones-user",
            "team_id": "ones-team",
        },
    }
    assert result.output["items"][0]["name"] == "Bounded result"


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
