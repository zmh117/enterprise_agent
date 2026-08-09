from __future__ import annotations

import json
import logging

from app.shared.logging import JsonFormatter, set_correlation_id


def test_json_formatter_redacts_credentials_headers_dsn_and_exceptions() -> None:
    set_correlation_id("correlation-sensitive-log-test")
    record = logging.LogRecord(
        name="security-test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=10,
        msg=(
            "Authorization: Bearer header-secret-value "
            "password=db-password-value "
            "postgresql://db-user:uri-password@10.0.0.9/app"
        ),
        args=(),
        exc_info=None,
    )
    payload = json.loads(JsonFormatter().format(record))
    assert "[REDACTED]" in payload["message"]
    for forbidden in (
        "header-secret-value",
        "db-password-value",
        "uri-password",
        "10.0.0.9",
    ):
        assert forbidden not in payload["message"]

    try:
        raise RuntimeError("token=exception-secret-value")
    except RuntimeError:
        exception_record = logging.LogRecord(
            name="security-test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=20,
            msg="provider failed",
            args=(),
            exc_info=__import__("sys").exc_info(),
        )
    exception_payload = json.loads(JsonFormatter().format(exception_record))
    assert "exception-secret-value" not in exception_payload["exception"]
    assert "[REDACTED]" in exception_payload["exception"]
