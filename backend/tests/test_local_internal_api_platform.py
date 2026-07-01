from __future__ import annotations

import io
import json
import unittest
import urllib.error
from typing import Any

from fastapi.testclient import TestClient

from app.local_internal_api_platform import create_app
from app.modules.local_internal_api_platform.loki_gateway import (
    LokiGateway,
    build_logql,
    summarize_loki_response,
)
from app.shared.config import LokiSettings, Settings


class FakeResponse:
    def __init__(self, body: dict[str, Any]) -> None:
        self.body = json.dumps(body).encode("utf-8")

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


class LocalInternalApiPlatformTests(unittest.TestCase):
    def test_health_reports_loki_configuration(self) -> None:
        client = TestClient(create_app(self._settings()))

        response = client.get("/health")

        self.assertEqual(200, response.status_code)
        self.assertEqual("local-internal-api-platform", response.json()["mode"])
        self.assertEqual(5, response.json()["loki"]["max_minutes"])

    def test_logql_builder_escapes_service_and_keyword(self) -> None:
        self.assertEqual('{service="order-service"}', build_logql({"service": "order-service"}, ""))
        self.assertEqual(
            '{service="order-service"} |= "Material\\\\Error \\"bad\\""',
            build_logql({"service": "order-service"}, 'Material\\Error "bad"'),
        )
        self.assertEqual(
            '{cluster="mes-cluster"} |= "Alloy"',
            build_logql({"cluster": "mes-cluster"}, "Alloy"),
        )

    def test_loki_endpoint_returns_summary_envelope(self) -> None:
        captured: dict[str, Any] = {}

        def fake_urlopen(request: Any, timeout: int) -> FakeResponse:
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            captured["timeout"] = timeout
            return FakeResponse(self._loki_body(["ok token=secret-token"]))

        client = TestClient(
            create_app(self._settings(tenant_id="tenant-a"), urlopen_func=fake_urlopen)
        )
        response = client.post(
            "/tools/loki/query",
            json={
                "selector": {"cluster": "mes-cluster"},
                "query": "Material",
                "minutes": 5,
                "limit": 10,
            },
            headers={"x-correlation-id": "corr-1"},
        )
        body = response.json()

        self.assertEqual(200, response.status_code)
        self.assertIn("/loki/api/v1/query_range?", captured["url"])
        self.assertIn("%7Bcluster%3D%22mes-cluster%22%7D+%7C%3D+%22Material%22", captured["url"])
        self.assertEqual("tenant-a", captured["headers"]["X-scope-orgid"])
        self.assertEqual("corr-1", body["metadata"]["request_id"])
        self.assertEqual("local-loki", body["metadata"]["source"])
        self.assertEqual({"cluster": "mes-cluster"}, body["summary"]["selector"])
        self.assertEqual(1, body["summary"]["line_count"])
        self.assertIn("token=<redacted>", body["summary"]["highlights"][0])
        self.assertNotIn("secret-token", json.dumps(body))

    def test_loki_validation_rejects_unsafe_input_before_upstream_call(self) -> None:
        called = False

        def fake_urlopen(request: Any, timeout: int) -> FakeResponse:
            nonlocal called
            called = True
            return FakeResponse({})

        client = TestClient(create_app(self._settings(), urlopen_func=fake_urlopen))
        response = client.post(
            "/tools/loki/query",
            json={"selector": {"cluster": '{service=~".*"}'}, "query": "", "minutes": 5, "limit": 10},
        )

        self.assertEqual(400, response.status_code)
        self.assertFalse(called)
        self.assertEqual("invalid_loki_query", response.json()["detail"]["error"]["code"])

    def test_loki_large_response_is_truncated(self) -> None:
        gateway = LokiGateway(self._settings(max_response_chars=20).loki)
        loki_query = gateway.validate(
            {"selector": {"cluster": "mes-cluster"}, "query": "", "minutes": 5, "limit": 10}
        )

        result = summarize_loki_response(
            self._loki_body(["x" * 30, "y" * 30]),
            loki_query,
            max_response_chars=20,
        )

        self.assertTrue(result.truncated)
        self.assertEqual(2, result.summary["line_count"])

    def test_loki_upstream_errors_are_classified(self) -> None:
        def transient_urlopen(request: Any, timeout: int) -> FakeResponse:
            raise self._http_error(503, {"error": "overloaded token=secret-token"})

        transient_client = TestClient(create_app(self._settings(), urlopen_func=transient_urlopen))
        transient = transient_client.post(
            "/tools/loki/query",
            json={"selector": {"service": "order-service"}, "query": "", "minutes": 5, "limit": 10},
        )
        self.assertEqual(503, transient.status_code)
        self.assertEqual("loki_unavailable", transient.json()["detail"]["error"]["code"])
        self.assertNotIn("secret-token", json.dumps(transient.json()))

        def rejected_urlopen(request: Any, timeout: int) -> FakeResponse:
            raise self._http_error(400, {"error": "bad query"})

        rejected_client = TestClient(create_app(self._settings(), urlopen_func=rejected_urlopen))
        rejected = rejected_client.post(
            "/tools/loki/query",
            json={"selector": {"service": "order-service"}, "query": "", "minutes": 5, "limit": 10},
        )
        self.assertEqual(400, rejected.status_code)
        self.assertEqual("loki_rejected_query", rejected.json()["detail"]["error"]["code"])

    def test_placeholder_and_unconfigured_endpoints(self) -> None:
        client = TestClient(create_app(self._settings()))

        er_context = client.post("/tools/context/er", json={"query": "order", "project_code": "p1"})
        flow_context = client.post(
            "/tools/context/business-flow",
            json={"query": "order", "project_code": "p1"},
        )
        database = client.post("/tools/database/query", json={"sql": "select 1"})
        redis_get = client.post("/tools/redis/get", json={"key": "order:1"})
        redis_scan = client.post("/tools/redis/scan", json={"pattern": "order:*"})

        self.assertEqual("local-placeholder-er-context", er_context.json()["summary"]["source"])
        self.assertEqual(
            "local-placeholder-business-flow-context",
            flow_context.json()["summary"]["source"],
        )
        for response in (database, redis_get, redis_scan):
            self.assertEqual(400, response.status_code)
            self.assertEqual("tool_not_configured", response.json()["detail"]["error"]["code"])

    def _settings(
        self,
        *,
        max_response_chars: int = 4000,
        tenant_id: str = "",
    ) -> Settings:
        return Settings(
            loki=LokiSettings(
                base_url="http://loki.test:3100",
                max_minutes=5,
                max_lines=10,
                max_response_chars=max_response_chars,
                tenant_id=tenant_id,
            )
        )

    def _loki_body(self, lines: list[str]) -> dict[str, Any]:
        return {
            "status": "success",
            "data": {
                "resultType": "streams",
                "result": [
                    {
                        "stream": {"service": "order-service", "level": "error"},
                        "values": [[str(index), line] for index, line in enumerate(lines)],
                    }
                ],
            },
        }

    def _http_error(self, status: int, body: dict[str, Any]) -> urllib.error.HTTPError:
        return urllib.error.HTTPError(
            url="http://loki.test",
            code=status,
            msg="error",
            hdrs={},
            fp=io.BytesIO(json.dumps(body).encode("utf-8")),
        )


if __name__ == "__main__":
    unittest.main()
