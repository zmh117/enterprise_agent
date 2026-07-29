"""Executable red-line tests for the runtime-foundation change.

These tests assert the target security/reliability behavior and are strict
xfails until the corresponding implementation task removes the current gap.
When a fix makes a test XPASS, remove its xfail marker and keep the assertion
as a permanent regression test.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.internal_api_platform.app import create_app as create_internal_api_app
from app.modules.job.application.create_agent_job_service import CreateAgentJobCommand
from app.shared.config import Settings
from app.shared.database import Database, default_migrations_dir
from backend.tests.helpers import container, test_settings as make_settings
from backend.tests.test_internal_api_platform_service import _service


RUNTIME_FOUNDATION_GAP = pytest.mark.xfail(
    strict=True,
    reason="Expected red line until stabilize-platform-runtime-foundation implements the gate",
)


def test_debug_api_must_not_accept_body_identity_without_login() -> None:
    runtime = container()
    with TestClient(create_app(make_settings(), container_factory=lambda _: runtime)) as client:
        response = client.post(
            "/api/agent/jobs",
            json={
                "message": "identity override must be rejected",
                "user_id": "local-user",
                "conversation_id": "debug-characterization",
                "project_code": "default",
                "idempotency_key": "debug-identity-characterization",
            },
        )

        assert response.status_code in {400, 401, 403, 422}
        assert runtime.agent_repository.count_rows("agent_job") == 0


def test_internal_api_must_reject_forged_identity_without_service_bearer(
    tmp_path: Path,
) -> None:
    token_path = tmp_path / "internal-api-token.json"
    token_path.write_text(
        '{"current":"characterization-current-token-000001"}',
        encoding="utf-8",
    )
    client = TestClient(
        create_internal_api_app(
            Settings(
                environment="test",
                internal_api_auth_token_file=str(token_path),
            ),
            service=_service(),
        )
    )
    response = client.post(
        "/tools/database/query",
        json={
            "environment": "sanjiu",
            "base": "guanlan",
            "workshop": "GL001",
            "sql": "select * from GL001_EBR_order",
        },
        headers={
            "x-agent-user-id": "alice",
            "x-agent-job-id": "forged-job",
        },
    )

    assert response.status_code == 401


def test_unbound_generic_channel_route_cannot_fail_open() -> None:
    runtime = container()
    with TestClient(create_app(make_settings(), container_factory=lambda _: runtime)) as client:
        response = client.post(
            "/webhooks/channel/agent",
            json={
                "from": {
                    "type": "debug_api",
                    "connector_id": "connector-debug-api",
                    "event_id": "empty-secret-characterization",
                    "actor_id": "local-user",
                },
                "delivery": {"type": "none"},
                "routing": {"project_code": "default"},
                "message": "empty connector secret must not authenticate",
            },
        )
        job_count = runtime.agent_repository.count_rows("agent_job")

    assert response.status_code == 404
    assert job_count == 0


def test_migration_versions_must_be_unique() -> None:
    migration_paths = sorted(Path(default_migrations_dir()).glob("*.sql"))
    versions = [path.name.split("_", 1)[0] for path in migration_paths]

    assert len(versions) == len(set(versions))


def test_database_must_not_hold_global_connection_or_transaction_depth() -> None:
    database = Database("sqlite:///:memory:")
    try:
        assert "_connection" not in vars(database)
        assert "_transaction_depth" not in vars(database)
    finally:
        database.close()


class _FailOnDirectPublish:
    def publish_agent_job(
        self,
        event_id: str,
        job_id: str,
        correlation_id: str,
    ) -> None:
        del event_id, job_id, correlation_id
        raise AssertionError("Job creation must commit an Outbox event, not publish directly")


def test_job_creation_must_not_directly_publish_after_database_commit() -> None:
    runtime = container()
    runtime.create_agent_job_service.publisher = _FailOnDirectPublish()  # type: ignore[assignment]
    try:
        job = runtime.create_agent_job_service.execute(
            CreateAgentJobCommand(
                idempotency_key="job-outbox-characterization",
                requester_id="local-user",
                external_conversation_id="debug-characterization",
                user_message="persist through outbox",
                project_code="default",
                source_channel="debug_api",
                source_connector_id="connector-debug-api",
                reply_route={"type": "none"},
            )
        )

        assert runtime.agent_repository.get_job(job.id).id == job.id
        dispatch = runtime.agent_repository.get_dispatch_event_for_job(job.id)
        assert dispatch is not None
        assert dispatch.status.value == "PENDING"
    finally:
        runtime.database.close()
