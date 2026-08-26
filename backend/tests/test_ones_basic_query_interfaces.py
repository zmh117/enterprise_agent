from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
import pytest

from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST
from app.shared.exceptions import AppError
from app.shared.ones_tool_contracts import ONES_TOOL_CONTRACTS
from ones_mock.mock_ones_api import MockOnesSettings, create_app
from services.ones_mcp_server.provider.graphql.client import OnesGraphqlClient
from services.ones_mcp_server.provider.graphql.operation import GraphqlOperationRegistry
from services.ones_mcp_server.provider.graphql.operations.business_queries import (
    BUSINESS_GRAPHQL_OPERATIONS,
    ISSUE_TYPE_LIST,
    PROJECT_SEARCH,
    SPRINT_WORK_ITEM_QUERY,
    WORK_ITEM_DETAIL,
)
from services.ones_mcp_server.provider.graphql.operations.test_queries import (
    TEST_GRAPHQL_OPERATIONS,
    TEST_PLAN_LIST,
    TESTCASE_DETAIL,
    TESTCASE_LIBRARY_LIST,
    TESTCASE_MODULE_CASES,
    TESTCASE_MODULE_LIST,
    TESTCASE_PLAN_CASES,
)
from services.ones_mcp_server.provider.rest.operations.basic_queries import (
    PROJECT_SPRINTS_OPERATION,
    TEAM_USER_SEARCH_OPERATION,
    WORK_ITEM_MESSAGES_OPERATION,
)
from services.ones_mcp_server.tools.query_services import (
    OnesTestCaseQueryService,
    OnesWorkItemQueryService,
)


NEW_TOOL_IDENTIFIERS = {
    "ones_get_test_case_detail",
    "ones_get_work_item_detail",
    "ones_list_issue_types",
    "ones_list_project_sprints",
    "ones_list_test_plans",
    "ones_list_testcase_libraries",
    "ones_list_testcase_modules",
    "ones_list_work_item_messages",
    "ones_query_test_cases",
    "ones_query_work_items",
    "ones_search_projects",
    "ones_search_team_users",
}


class _MockProviderHttp:
    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.target = SimpleNamespace(base_url="http://ones-mock:8001")

    def post_json(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        headers: dict[str, str],
        query: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        response = self.client.post(path, params=query, headers=headers, json=payload)
        assert response.status_code == 200, response.text
        value = response.json()
        assert isinstance(value, dict)
        return value

    def get_json(
        self,
        path: str,
        payload: dict[str, Any] | None,
        *,
        headers: dict[str, str],
        query: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        request_headers = dict(headers)
        if payload is None:
            response = self.client.get(path, params=query, headers=request_headers)
        else:
            response = self.client.request(
                "GET",
                path,
                params=query,
                headers={**request_headers, "Content-Type": "application/json"},
                json=payload,
            )
        assert response.status_code == 200, response.text
        value = response.json()
        assert isinstance(value, dict)
        return value


def _provider() -> tuple[MockOnesSettings, _MockProviderHttp, dict[str, str]]:
    settings = MockOnesSettings()
    http = _MockProviderHttp(TestClient(create_app(settings)))
    headers = {
        "Ones-Auth-Token": settings.token,
        "Ones-User-Id": settings.user_uuid,
    }
    return settings, http, headers


def _assert_contract(identifier: str, output: dict[str, Any]) -> None:
    Draft202012Validator(ONES_TOOL_CONTRACTS[identifier].output_schema).validate(output)


def test_all_ones_tool_contracts_are_valid_shared_manifest_facts() -> None:
    assert NEW_TOOL_IDENTIFIERS < set(ONES_TOOL_CONTRACTS)
    for identifier, contract in ONES_TOOL_CONTRACTS.items():
        Draft202012Validator.check_schema(contract.input_schema)
        Draft202012Validator.check_schema(contract.output_schema)
        definition = MCP_TOOL_MANIFEST[identifier]
        assert definition.server_code == "ones-mcp"
        assert definition.description == contract.description
        assert definition.input_schema == contract.input_schema
        assert definition.read_only is True


def test_fixed_business_graphql_operations_execute_against_the_mock_contract() -> None:
    settings, http, headers = _provider()
    client = OnesGraphqlClient(
        http,  # type: ignore[arg-type]
        GraphqlOperationRegistry((*BUSINESS_GRAPHQL_OPERATIONS, *TEST_GRAPHQL_OPERATIONS)),
    )
    context = {"team_id": settings.team_uuid}

    projects = client.execute(
        PROJECT_SEARCH,
        arguments={"keyword": "Manufacturing", "limit": 10},
        context=context,
        headers=headers,
    )
    assert projects.output["projects"][0]["uuid"] == settings.config.project_uuid
    assert "query" not in projects.request
    assert not any(key.startswith("_") for key in projects.request["variables"])
    _assert_contract("ones_search_projects", projects.output)

    issue_types = client.execute(
        ISSUE_TYPE_LIST,
        arguments={"project_uuid": settings.config.project_uuid, "limit": 10},
        context=context,
        headers=headers,
    )
    assert issue_types.output["returned"] == 3
    _assert_contract("ones_list_issue_types", issue_types.output)

    work_items = client.execute(
        SPRINT_WORK_ITEM_QUERY,
        arguments={
            "project_uuid": settings.config.project_uuid,
            "sprint_uuid": "MOCK-ONES-SPRINT-ACTIVE",
            "status_categories": ["done"],
            "limit": 10,
        },
        context=context,
        headers=headers,
    )
    assert [item["number"] for item in work_items.output["items"]] == [900102]
    _assert_contract("ones_query_work_items", work_items.output)

    detail = client.execute(
        WORK_ITEM_DETAIL,
        arguments={"work_item_uuid": "MOCK-ONES-TASK-900102"},
        context=context,
        headers=headers,
    )
    assert detail.output["work_item"]["status"]["category"] == "done"
    _assert_contract("ones_get_work_item_detail", detail.output)


def test_fixed_testcase_graphql_operations_execute_against_the_mock_contract() -> None:
    settings, http, headers = _provider()
    client = OnesGraphqlClient(
        http,  # type: ignore[arg-type]
        GraphqlOperationRegistry(TEST_GRAPHQL_OPERATIONS),
    )
    context = {"team_id": settings.team_uuid}
    cases = (
        (
            TESTCASE_LIBRARY_LIST,
            {"limit": 10},
            "ones_list_testcase_libraries",
            "libraries",
        ),
        (
            TESTCASE_MODULE_LIST,
            {"library_uuid": "MOCK-ONES-LIBRARY-001", "limit": 10},
            "ones_list_testcase_modules",
            "modules",
        ),
        (TEST_PLAN_LIST, {"limit": 10}, "ones_list_test_plans", "plans"),
        (
            TESTCASE_MODULE_CASES,
            {
                "source": "module",
                "source_uuid": "MOCK-ONES-MODULE-001",
                "library_uuid": "MOCK-ONES-LIBRARY-001",
                "limit": 10,
            },
            "ones_query_test_cases",
            "test_cases",
        ),
        (
            TESTCASE_PLAN_CASES,
            {
                "source": "plan",
                "source_uuid": "MOCK-ONES-PLAN-001",
                "limit": 10,
            },
            "ones_query_test_cases",
            "test_cases",
        ),
    )
    for operation, arguments, tool, field in cases:
        execution = client.execute(
            operation,
            arguments=arguments,
            context=context,
            headers=headers,
        )
        assert execution.output[field]
        _assert_contract(tool, execution.output)

    detail = client.execute(
        TESTCASE_DETAIL,
        arguments={"test_case_uuid": "MOCK-ONES-TESTCASE-001"},
        context=context,
        headers=headers,
    )
    assert detail.output["steps"][0]["index"] == 1
    _assert_contract("ones_get_test_case_detail", detail.output)


def test_fixed_rest_operations_execute_against_the_mock_contract() -> None:
    settings, http, _headers = _provider()
    common = {
        "team_uuid": settings.team_uuid,
        "token": settings.token,
        "user_id": settings.user_uuid,
    }

    sprints = PROJECT_SPRINTS_OPERATION.execute(
        http,  # type: ignore[arg-type]
        project_uuid=settings.config.project_uuid,
        limit=10,
        **common,
    )
    assert {item["status"] for item in sprints.output["sprints"]} == {
        "done",
        "in_progress",
    }
    _assert_contract("ones_list_project_sprints", sprints.output)

    messages = WORK_ITEM_MESSAGES_OPERATION.execute(
        http,  # type: ignore[arg-type]
        work_item_uuid="MOCK-ONES-TASK-900102",
        limit=10,
        **common,
    )
    assert messages.output["messages"][0]["text"] == "Synthetic timeline message."
    _assert_contract("ones_list_work_item_messages", messages.output)

    users = TEAM_USER_SEARCH_OPERATION.execute(
        http,  # type: ignore[arg-type]
        keyword="Owner",
        project_uuid=settings.config.project_uuid,
        limit=10,
        **common,
    )
    assert users.output["users"][0]["name"] == "Mock ONES Owner"
    _assert_contract("ones_search_team_users", users.output)


def test_new_tool_validation_and_timeline_projection_fail_closed() -> None:
    work_items = object.__new__(OnesWorkItemQueryService)
    test_cases = object.__new__(OnesTestCaseQueryService)

    for arguments in (
        {"sprint_uuid": "SPRINT-1", "limit": 10},
        {
            "created_from": "2026-08-02T00:00:00Z",
            "created_to": "2026-08-01T00:00:00Z",
            "limit": 10,
        },
        {"query": "mutation Forbidden { update }", "limit": 10},
    ):
        with pytest.raises(AppError) as raised:
            work_items.validate_arguments(arguments)
        assert raised.value.error_code == "ones_tool_input_invalid"

    with pytest.raises(AppError) as missing_library:
        test_cases.validate_arguments(
            {"source": "module", "source_uuid": "MODULE-1", "limit": 10}
        )
    assert missing_library.value.error_code == "ones_tool_input_invalid"

    timeline = WORK_ITEM_MESSAGES_OPERATION.parse_response(
        {
            "messages": [
                {
                    "uuid": "MESSAGE-1",
                    "type": "comment",
                    "send_time": 1784736000000,
                    "text": "See https://example.test/private?signature=discarded now",
                    "email": "discarded@example.test",
                    "avatar": "https://example.test/avatar",
                }
            ],
            "count": 1,
            "has_next": False,
        },
        limit=10,
    )
    assert timeline["messages"] == [
        {
            "uuid": "MESSAGE-1",
            "type": "comment",
            "sent_at": "2026-07-22T16:00:00+00:00",
            "text": "See [link omitted] now",
        }
    ]
    _assert_contract("ones_list_work_item_messages", timeline)
