from __future__ import annotations

import io
import json
import unittest
import urllib.error
from typing import Any

from app.modules.internal_tools.infrastructure.internal_api_client import (
    HttpInternalApiClient,
    ToolRequestContext,
)
from app.shared.exceptions import (
    NonRetryableExecutionError,
    RetryableExecutionError,
    ToolPolicyError,
)


class FakeResponse:
    def __init__(self, body: dict[str, Any]) -> None:
        self.body = json.dumps(body).encode("utf-8")

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


class HttpInternalApiClientTests(unittest.TestCase):
    def test_posts_context_headers_and_parses_summary_envelope(self) -> None:
        captured: dict[str, Any] = {}

        def fake_urlopen(request: Any, timeout: int) -> FakeResponse:
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            return FakeResponse(
                {
                    "summary": {"row_count": 1},
                    "raw": {"rows": [{"secret": "hidden"}]},
                    "truncated": True,
                    "metadata": {"request_id": "corr-1", "source": "mock-db"},
                }
            )

        client = HttpInternalApiClient(
            "http://internal.test",
            auth_token="secret-token",
            timeout_seconds=7,
            urlopen_func=fake_urlopen,
        )
        result = client.query_database(
            "default",
            "select * from ws_a_order",
            10,
            self._context(),
        )

        self.assertEqual("http://internal.test/tools/database/query", captured["url"])
        self.assertEqual(7, captured["timeout"])
        self.assertEqual("Bearer secret-token", captured["headers"]["Authorization"])
        self.assertEqual("job-1", captured["headers"]["X-agent-job-id"])
        self.assertEqual("local-user", captured["headers"]["X-agent-user-id"])
        self.assertEqual("default", captured["headers"]["X-agent-project-code"])
        self.assertEqual("corr-1", captured["headers"]["X-correlation-id"])
        self.assertEqual("select * from ws_a_order", captured["payload"]["sql"])
        self.assertEqual({"row_count": 1}, result.summary)
        self.assertTrue(result.truncated)
        self.assertEqual("mock-db", result.metadata["source"])

    def test_legacy_body_is_treated_as_summary(self) -> None:
        def fake_urlopen(request: Any, timeout: int) -> FakeResponse:
            return FakeResponse({"line_count": 1})

        client = HttpInternalApiClient("http://internal.test", urlopen_func=fake_urlopen)
        result = client.query_loki("order-service", "", 15, 10, self._context())

        self.assertEqual({"line_count": 1}, result.summary)
        self.assertEqual({"line_count": 1}, result.raw)

    def test_transient_http_status_is_retryable(self) -> None:
        def fake_urlopen(request: Any, timeout: int) -> FakeResponse:
            raise self._http_error(503, {"message": "overloaded token=secret-token"})

        client = HttpInternalApiClient("http://internal.test", urlopen_func=fake_urlopen)

        with self.assertRaises(RetryableExecutionError) as raised:
            client.query_redis_get("default", "order:1", self._context())

        self.assertIn("503", raised.exception.safe_message)
        self.assertIn("token=<redacted>", raised.exception.safe_message)
        self.assertNotIn("secret-token", raised.exception.safe_message)

    def test_network_error_is_retryable_and_redacted(self) -> None:
        def fake_urlopen(request: Any, timeout: int) -> FakeResponse:
            raise urllib.error.URLError("authorization: bearer secret-token")

        client = HttpInternalApiClient("http://internal.test", urlopen_func=fake_urlopen)

        with self.assertRaises(RetryableExecutionError) as raised:
            client.query_loki("order-service", "", 15, 10, self._context())

        self.assertIn("Internal API Platform request failed", raised.exception.safe_message)
        self.assertIn("bearer <redacted>", raised.exception.safe_message)
        self.assertNotIn("secret-token", raised.exception.safe_message)

    def test_policy_denied_is_tool_policy_error(self) -> None:
        def fake_urlopen(request: Any, timeout: int) -> FakeResponse:
            raise self._http_error(
                403,
                {"detail": {"error": {"code": "policy_denied", "message": "denied"}}},
            )

        client = HttpInternalApiClient("http://internal.test", urlopen_func=fake_urlopen)

        with self.assertRaises(ToolPolicyError):
            client.query_redis_scan("default", "order:*", 5, self._context())

    def test_non_retryable_http_status_is_non_retryable(self) -> None:
        def fake_urlopen(request: Any, timeout: int) -> FakeResponse:
            raise self._http_error(401, {"message": "bad authorization"})

        client = HttpInternalApiClient("http://internal.test", urlopen_func=fake_urlopen)

        with self.assertRaises(NonRetryableExecutionError):
            client.get_er_context("order", self._context())

    def _context(self) -> ToolRequestContext:
        return ToolRequestContext(
            job_id="job-1",
            user_id="local-user",
            project_code="default",
            correlation_id="corr-1",
        )

    def _http_error(self, status: int, body: dict[str, Any]) -> urllib.error.HTTPError:
        return urllib.error.HTTPError(
            url="http://internal.test",
            code=status,
            msg="error",
            hdrs={},
            fp=io.BytesIO(json.dumps(body).encode("utf-8")),
        )


if __name__ == "__main__":
    unittest.main()
