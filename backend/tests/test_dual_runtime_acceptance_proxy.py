from __future__ import annotations

import json

from app.acceptance.runtime_fault_proxy import _must_fail_first_job_attempt


def _body(invocation_id: str, question: str) -> bytes:
    return json.dumps(
        {
            "invocation_id": invocation_id,
            "prompt": {"user_question": question},
        }
    ).encode("utf-8")


def test_fault_proxy_fails_only_marked_first_job_attempt() -> None:
    assert _must_fail_first_job_attempt(
        path="internal/v1/executions",
        method="POST",
        body=_body("job-1.attempt-0", "[acceptance:retry-once] retry"),
    )
    assert not _must_fail_first_job_attempt(
        path="internal/v1/executions",
        method="POST",
        body=_body("job-1.attempt-1", "[acceptance:retry-once] retry"),
    )
    assert not _must_fail_first_job_attempt(
        path="internal/v1/executions",
        method="POST",
        body=_body("job-1.attempt-0", "normal request"),
    )
    assert not _must_fail_first_job_attempt(
        path="internal/v1/executions/job-1.attempt-0/cancel",
        method="POST",
        body=b"{}",
    )
