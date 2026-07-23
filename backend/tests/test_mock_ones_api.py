from __future__ import annotations

import unittest
from typing import Any

from fastapi.testclient import TestClient

from app.mock_ones_api import MOCK_ISSUE_TYPES, MockOnesSettings, create_app


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
        self.assertEqual({"status": "ok", "service": "ones-mock"}, response.json())

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

    def test_login_rejects_wrong_password_without_echoing_it(self) -> None:
        response = self.client.post(
            "/project/api/project/auth/login",
            json={"email": self.settings.email, "password": "wrong-password"},
        )

        self.assertEqual(401, response.status_code)
        self.assertNotIn("wrong-password", response.text)
        self.assertEqual("invalid_credentials", response.json()["detail"]["code"])

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


if __name__ == "__main__":
    unittest.main()
