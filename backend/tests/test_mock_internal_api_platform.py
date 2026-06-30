from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from app.mock_internal_api_platform import create_app


class MockInternalApiPlatformTests(unittest.TestCase):
    def test_mock_endpoints_return_summary_envelope(self) -> None:
        client = TestClient(create_app())
        endpoints = [
            ("/tools/context/er", {"query": "order", "project_code": "default"}),
            ("/tools/context/business-flow", {"query": "order", "project_code": "default"}),
            ("/tools/loki/query", {"service": "order-service", "query": "", "minutes": 15}),
            ("/tools/database/query", {"datasource": "default", "sql": "select 1"}),
            ("/tools/redis/get", {"datasource": "default", "key": "order:1"}),
            ("/tools/redis/scan", {"datasource": "default", "pattern": "order:*"}),
        ]

        for path, payload in endpoints:
            response = client.post(path, json=payload, headers={"x-correlation-id": "corr-1"})
            body = response.json()
            self.assertEqual(200, response.status_code)
            self.assertIn("summary", body)
            self.assertIn("raw", body)
            self.assertIn("metadata", body)
            self.assertEqual("corr-1", body["metadata"]["request_id"])

    def test_mock_policy_denial(self) -> None:
        client = TestClient(create_app())
        response = client.post(
            "/tools/database/query",
            json={"datasource": "default", "sql": "select 1", "mock_scenario": "policy_denied"},
        )

        self.assertEqual(403, response.status_code)
        self.assertEqual("policy_denied", response.json()["detail"]["error"]["code"])


if __name__ == "__main__":
    unittest.main()
