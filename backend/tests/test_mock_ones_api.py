from __future__ import annotations

import unittest
from dataclasses import replace
from typing import Any

from fastapi.testclient import TestClient

from ones_mock.mock_ones_api import MOCK_ISSUE_TYPES, MockOnesSettings, create_app
from services.ones_mcp_server.provider.task_update import OnesTaskUpdateProvider
from services.ones_mcp_server.task_update_catalog import TaskUpdateFieldCatalog


class _TestClientTaskUpdateHttp:
    def __init__(self, client: TestClient) -> None:
        self.client = client

    def post_json(
        self,
        path: str,
        payload: dict[str, object],
        *,
        headers: dict[str, str],
        query: dict[str, str] | None = None,
    ) -> dict[str, object]:
        response = self.client.post(path, params=query, headers=headers, json=payload)
        response.raise_for_status()
        body = response.json()
        assert isinstance(body, dict)
        return body


class MockOnesApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = MockOnesSettings()
        self.client = TestClient(create_app(self.settings))
        self.auth_headers = {
            "Ones-Auth-Token": self.settings.token,
            "Ones-User-Id": self.settings.user_uuid,
        }

    def graphql(self, query_type: str, variables: dict[str, Any]) -> Any:
        return self.client.post(
            f"/project/api/project/team/{self.settings.team_uuid}/items/graphql",
            params={"t": query_type},
            headers=self.auth_headers,
            json={"query": "query MockQuery { mock }", "variables": variables},
        )

    def test_health(self) -> None:
        response = self.client.get("/health")

        self.assertEqual(200, response.status_code)
        body = response.json()
        self.assertEqual("ok", body["status"])
        self.assertEqual("ones-mock", body["service"])
        self.assertEqual(2, body["users"])

    def test_login_returns_user_token_and_team_for_business_requests(self) -> None:
        response = self.client.post(
            "/project/api/project/auth/login",
            json={"email": self.settings.email, "password": self.settings.password},
        )

        self.assertEqual(200, response.status_code)
        body = response.json()
        self.assertEqual(self.settings.user_uuid, body["user"]["uuid"])
        self.assertEqual(self.settings.token, body["user"]["token"])
        self.assertEqual(self.settings.team_uuid, body["teams"][0]["uuid"])
        self.assertGreaterEqual(len(body["teams"]), 2)

    def test_login_rejects_wrong_password_without_echoing_it(self) -> None:
        response = self.client.post(
            "/project/api/project/auth/login",
            json={"email": self.settings.email, "password": "wrong-password"},
        )

        self.assertEqual(401, response.status_code)
        self.assertNotIn("wrong-password", response.text)
        self.assertEqual("invalid_credentials", response.json()["detail"]["code"])

    def test_login_can_return_an_invalid_contract_for_adapter_tests(self) -> None:
        response = self.client.post(
            "/project/api/project/auth/login",
            json={
                "email": self.settings.invalid_response_email,
                "password": "ignored-by-invalid-contract-scenario",
            },
        )

        self.assertEqual(200, response.status_code)
        self.assertNotIn("uuid", response.json()["user"])
        self.assertNotIsInstance(response.json()["teams"], list)

    def test_graphql_requires_login_derived_auth_headers(self) -> None:
        response = self.client.post(
            f"/project/api/project/team/{self.settings.team_uuid}/items/graphql",
            params={"t": "group-task-data"},
            json={"query": "query MockQuery { mock }", "variables": {}},
        )

        self.assertEqual(401, response.status_code)
        self.assertEqual("unauthorized", response.json()["detail"]["code"])

    def test_group_task_data_filters_by_defect_type_and_number(self) -> None:
        response = self.graphql(
            "group-task-data",
            {
                "filterGroup": [{"issueType_in": [MOCK_ISSUE_TYPES["defect"]["uuid"]]}],
                "search": {"keyword": "#900103", "aliases": []},
                "pagination": {"limit": 500, "preciseCount": False},
            },
        )

        self.assertEqual(200, response.status_code)
        bucket = response.json()["data"]["buckets"][0]
        self.assertEqual(1, bucket["pageInfo"]["totalCount"])
        self.assertEqual(900103, bucket["tasks"][0]["number"])
        self.assertEqual(
            MOCK_ISSUE_TYPES["defect"]["uuid"],
            bucket["tasks"][0]["issueType"]["uuid"],
        )

    def test_group_task_data_supports_demands_tasks_and_defects(self) -> None:
        response = self.graphql("group-task-data", {})

        self.assertEqual(200, response.status_code)
        tasks = response.json()["data"]["buckets"][0]["tasks"]
        self.assertEqual([900101, 900102, 900103], [task["number"] for task in tasks])
        self.assertEqual(
            {
                MOCK_ISSUE_TYPES["demand"]["uuid"],
                MOCK_ISSUE_TYPES["task"]["uuid"],
                MOCK_ISSUE_TYPES["defect"]["uuid"],
            },
            {task["issueType"]["uuid"] for task in tasks},
        )

    def test_issue_type_scopes_are_project_scoped(self) -> None:
        response = self.graphql(
            "issueTypeScopes",
            {
                "filter": {
                    "scope_equal": self.settings.project_scope_uuid,
                    "scopeType_equal": 1,
                }
            },
        )

        self.assertEqual(200, response.status_code)
        scopes = response.json()["data"]["issueTypeScopes"]
        self.assertEqual(3, len(scopes))
        self.assertEqual(
            {item["scope_uuid"] for item in MOCK_ISSUE_TYPES.values()},
            {item["uuid"] for item in scopes},
        )

        no_match = self.graphql(
            "issueTypeScopes",
            {"filter": {"scope_equal": "MOCK-UNKNOWN-SCOPE", "scopeType_equal": 1}},
        )
        self.assertEqual([], no_match.json()["data"]["issueTypeScopes"])

    def test_graphql_rejects_wrong_team_and_unsupported_query(self) -> None:
        wrong_team = self.client.post(
            "/project/api/project/team/MOCK-UNKNOWN-TEAM/items/graphql",
            params={"t": "group-task-data"},
            headers=self.auth_headers,
            json={"query": "query MockQuery { mock }", "variables": {}},
        )
        unsupported = self.graphql("unknown-query", {})

        self.assertEqual(404, wrong_team.status_code)
        self.assertEqual("team_not_found", wrong_team.json()["detail"]["code"])
        self.assertEqual(400, unsupported.status_code)
        self.assertEqual("unsupported_query_type", unsupported.json()["detail"]["code"])

    def test_task_update_provider_uses_mock_update3_and_observes_readback(self) -> None:
        catalog = replace(
            TaskUpdateFieldCatalog.load(),
            source_team_uuid=self.settings.team_uuid,
        )
        provider = OnesTaskUpdateProvider(
            _TestClientTaskUpdateHttp(self.client),  # type: ignore[arg-type]
            catalog=catalog,
        )
        task_uuid = "MOCK-ONES-TASK-900103"

        before = provider.read_task(
            team_uuid=self.settings.team_uuid,
            task_uuid=task_uuid,
            provider_user_id=self.settings.user_uuid,
            token=self.settings.token,
        )
        result = provider.update_task(
            team_uuid=self.settings.team_uuid,
            provider_user_id=self.settings.user_uuid,
            token=self.settings.token,
            payload={
                "tasks": [
                    {
                        "uuid": task_uuid,
                        "name": "Mock defect: status refresh fixed",
                        "summary": "Mock defect: status refresh fixed",
                    }
                ]
            },
        )
        after = provider.read_task(
            team_uuid=self.settings.team_uuid,
            task_uuid=task_uuid,
            provider_user_id=self.settings.user_uuid,
            token=self.settings.token,
        )

        self.assertEqual({"updated": True, "bad_tasks": []}, result)
        self.assertEqual("缺陷", before.issue_type_name)
        self.assertTrue(before.can_edit)
        self.assertEqual("Mock defect: status refresh fixed", after.title)
        self.assertNotEqual(before.server_update_stamp, after.server_update_stamp)

    def test_governed_search_returns_bounded_normalized_contract(self) -> None:
        response = self.client.post(
            "/project/api/project/items/graphql",
            headers={"Ones-Auth-Token": self.settings.token},
            json={
                "query": "query SearchWorkItems { workItems { total } }",
                "variables": {
                    "keyword": "status",
                    "issue_type": "defect",
                    "limit": 1,
                    "user_id": self.settings.user_uuid,
                    "team_id": self.settings.team_uuid,
                },
            },
        )
        self.assertEqual(200, response.status_code)
        result = response.json()["data"]["workItems"]
        self.assertEqual(1, result["total"])
        self.assertEqual(
            {
                "number": 900103,
                "name": "Mock defect: order status is not refreshed",
                "type": "defect",
            },
            result["items"][0],
        )
        self.assertFalse(result["truncated"])

    def test_governed_search_covers_safe_failure_scenarios(self) -> None:
        def request(keyword: str) -> Any:
            return self.client.post(
                "/project/api/project/items/graphql",
                headers={"Ones-Auth-Token": self.settings.token},
                json={
                    "query": "query SearchWorkItems { workItems { total } }",
                    "variables": {
                        "keyword": keyword,
                        "issue_type": "defect",
                        "limit": 1,
                        "user_id": self.settings.user_uuid,
                        "team_id": self.settings.team_uuid,
                    },
                },
            )

        self.assertEqual(401, request("__401__").status_code)
        self.assertEqual(403, request("__403__").status_code)
        self.assertEqual(429, request("__429__").status_code)
        self.assertEqual(500, request("__500__").status_code)
        self.assertEqual("{not-json", request("__bad_json__").text)
        self.assertGreater(
            len(request("__oversize__").content),
            1_000_000,
        )
        malformed = request("__missing_field__").json()
        self.assertNotIn(
            "number",
            malformed["data"]["workItems"]["items"][0],
        )

    def test_project_role_members_and_team_users_follow_the_exact_rest_contract(self) -> None:
        role_response = self.client.request(
            "GET",
            (
                f"/project/api/project/team/{self.settings.team_uuid}/project/"
                f"{self.settings.config.project_uuid}/role_members"
            ),
            headers={
                **self.auth_headers,
                "Referer": "http://ones-mock:8001",
                "cache-control": "no-cache",
                "Content-Type": "application/json",
            },
            content=b"{}",
        )
        self.assertEqual(200, role_response.status_code)
        roles = role_response.json()["role_members"]
        self.assertEqual(2, len(roles))
        self.assertIn(self.settings.user_uuid, roles[0]["members"])
        shared_uuid = self.settings.config.users[1].uuid
        self.assertIn(shared_uuid, roles[0]["members"])
        self.assertIn(shared_uuid, roles[1]["members"])

        users_response = self.client.post(
            f"/project/api/project/team/{self.settings.team_uuid}/users",
            headers={
                **self.auth_headers,
                "Referer": "http://ones-mock:8001",
                "cache-control": "no-cache",
            },
            json={"uuids": [self.settings.user_uuid, shared_uuid]},
        )
        self.assertEqual(200, users_response.status_code)
        self.assertEqual(
            {self.settings.user_uuid, shared_uuid},
            {user["uuid"] for user in users_response.json()["users"]},
        )
        self.assertIn("email", users_response.json()["users"][0])

    def test_project_role_members_requires_auth_headers_and_empty_json_body(self) -> None:
        path = (
            f"/project/api/project/team/{self.settings.team_uuid}/project/"
            f"{self.settings.config.project_uuid}/role_members"
        )
        headers = {
            **self.auth_headers,
            "Referer": "http://ones-mock:8001",
            "cache-control": "no-cache",
            "Content-Type": "application/json",
        }

        no_body = self.client.request("GET", path, headers=headers)
        wrong_body = self.client.request("GET", path, headers=headers, content=b'{"x":1}')
        no_auth = self.client.request(
            "GET",
            path,
            headers={
                "Referer": "http://ones-mock:8001",
                "cache-control": "no-cache",
                "Content-Type": "application/json",
            },
            content=b"{}",
        )

        self.assertEqual(400, no_body.status_code)
        self.assertEqual(400, wrong_body.status_code)
        self.assertEqual(401, no_auth.status_code)

    def test_project_role_members_mock_supports_empty_and_missing_user_contracts(self) -> None:
        def get(project_uuid: str) -> Any:
            return self.client.request(
                "GET",
                (
                    f"/project/api/project/team/{self.settings.team_uuid}/project/"
                    f"{project_uuid}/role_members"
                ),
                headers={
                    **self.auth_headers,
                    "Referer": "http://ones-mock:8001",
                    "cache-control": "no-cache",
                    "Content-Type": "application/json",
                },
                content=b"{}",
            )

        self.assertEqual([], get("MOCK-ONES-PROJECT-EMPTY").json()["role_members"])
        missing = get("MOCK-ONES-PROJECT-MISSING-USER").json()["role_members"]
        self.assertEqual(["MOCK-ONES-USER-MISSING"], missing[0]["members"])


if __name__ == "__main__":
    unittest.main()
