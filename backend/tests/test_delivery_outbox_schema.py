from __future__ import annotations

import sqlite3

import pytest

from app.modules.job.application.create_agent_job_service import (
    CreateAgentJobCommand,
)
from app.modules.job.infrastructure.repositories import now_iso
from backend.tests.helpers import container


def _job_and_artifact() -> tuple[object, object, str]:
    runtime = container()
    job = runtime.create_agent_job_service.execute(
        CreateAgentJobCommand(
            idempotency_key="delivery-outbox-schema",
            requester_id="local-user",
            external_conversation_id="delivery-schema",
            user_message="diagnose",
            source_channel="debug_api",
            source_connector_id="connector-debug-api",
            project_code="default",
            correlation_id="delivery-schema-correlation",
            reply_route={"type": "none"},
        )
    )
    artifact_id = runtime.agent_repository.add_artifact(
        job_id=job.id,
        artifact_type="report",
        name="diagnostic-report.md",
        content="persisted result",
    )
    return runtime, job, artifact_id


def _insert_event(
    runtime: object,
    job_id: str,
    artifact_id: str,
    *,
    event_id: str = "delivery-schema-event",
    event_key: str = "delivery.result:artifact",
    status: str = "PENDING",
    max_attempts: int = 3,
) -> None:
    timestamp = now_iso()
    runtime.database.execute(
        """
        insert into delivery_outbox
          (id, event_key, job_id, result_artifact_id,
           application_publication_id, delivery_binding_json,
           target_summary, correlation_id, status, attempt_count,
           max_attempts, replay_count, max_replay_count,
           next_attempt_at, created_at, updated_at)
        values (?, ?, ?, ?, '', '{"type":"none"}', '{}', ?,
                ?, 0, ?, 0, 2, ?, ?, ?)
        """,
        (
            event_id,
            event_key,
            job_id,
            artifact_id,
            "delivery-schema-correlation",
            status,
            max_attempts,
            timestamp,
            timestamp,
            timestamp,
        ),
    )


def test_delivery_outbox_schema_has_states_claims_and_required_indexes() -> None:
    runtime, job, artifact_id = _job_and_artifact()
    try:
        _insert_event(runtime, job.id, artifact_id)
        row = runtime.database.execute_one(
            "select * from delivery_outbox where id = ?",
            ("delivery-schema-event",),
        )
        assert row is not None
        assert row["status"] == "PENDING"
        assert row["attempt_count"] == 0
        assert row["max_attempts"] == 3
        assert row["claim_token"] == ""

        indexes = {
            row["name"]
            for row in runtime.database.execute(
                "select name from sqlite_master where type = 'index'"
            )
        }
        assert {
            "idx_delivery_outbox_claim",
            "idx_delivery_outbox_job",
            "idx_delivery_outbox_correlation",
            "idx_delivery_outbox_stale_claim",
            "uq_delivery_attempt_idempotency",
            "uq_delivery_attempt_outbox_number",
            "uq_delivery_chunk_logical_success",
        }.issubset(indexes)
    finally:
        runtime.database.close()


@pytest.mark.parametrize(
    "status",
    [
        "PENDING",
        "RUNNING",
        "RETRY_WAIT",
        "SUCCEEDED",
        "FAILED",
        "DEAD",
        "SKIPPED",
    ],
)
def test_delivery_outbox_accepts_only_defined_states(status: str) -> None:
    runtime, job, artifact_id = _job_and_artifact()
    try:
        _insert_event(runtime, job.id, artifact_id, status=status)
        assert runtime.database.execute_one(
            "select status from delivery_outbox"
        ) == {"status": status}
    finally:
        runtime.database.close()


def test_delivery_outbox_rejects_invalid_state_attempt_limit_and_duplicates() -> None:
    runtime, job, artifact_id = _job_and_artifact()
    try:
        with pytest.raises(sqlite3.IntegrityError):
            _insert_event(
                runtime,
                job.id,
                artifact_id,
                status="STARTED",
            )
        with pytest.raises(sqlite3.IntegrityError):
            _insert_event(
                runtime,
                job.id,
                artifact_id,
                event_id="delivery-zero-attempts",
                event_key="delivery.result:zero",
                max_attempts=0,
            )
        _insert_event(runtime, job.id, artifact_id)
        with pytest.raises(sqlite3.IntegrityError):
            _insert_event(
                runtime,
                job.id,
                artifact_id,
                event_id="delivery-duplicate",
                event_key="delivery.result:duplicate",
            )
    finally:
        runtime.database.close()


def test_delivery_chunk_allows_only_one_success_per_logical_chunk() -> None:
    runtime, job, artifact_id = _job_and_artifact()
    try:
        _insert_event(runtime, job.id, artifact_id)
        timestamp = now_iso()
        for attempt_no in (1, 2):
            runtime.database.execute(
                """
                insert into delivery_attempt
                  (id, job_id, route_type, connector_id, target_summary,
                   status, created_at, delivery_outbox_id, attempt_no,
                   correlation_id, idempotency_key, error_code)
                values (?, ?, 'none', '', '{}', 'STARTED', ?, ?, ?, ?,
                        ?, '')
                """,
                (
                    f"attempt-{attempt_no}",
                    job.id,
                    timestamp,
                    "delivery-schema-event",
                    attempt_no,
                    "delivery-schema-correlation",
                    f"delivery.attempt:{attempt_no}",
                ),
            )
        runtime.database.execute(
            """
            insert into delivery_chunk
              (id, attempt_id, chunk_index, chunk_count, status,
               payload_summary, created_at, delivery_outbox_id,
               attempt_no, idempotency_key, payload_hash, sent_at)
            values ('chunk-success-1', 'attempt-1', 1, 1, 'SUCCEEDED',
                    '{}', ?, 'delivery-schema-event', 1,
                    'delivery.chunk:1', ?, ?)
            """,
            (timestamp, "a" * 64, timestamp),
        )
        with pytest.raises(sqlite3.IntegrityError):
            runtime.database.execute(
                """
                insert into delivery_chunk
                  (id, attempt_id, chunk_index, chunk_count, status,
                   payload_summary, created_at, delivery_outbox_id,
                   attempt_no, idempotency_key, payload_hash, sent_at)
                values ('chunk-success-2', 'attempt-2', 1, 1, 'SUCCEEDED',
                        '{}', ?, 'delivery-schema-event', 2,
                        'delivery.chunk:1:retry', ?, ?)
                """,
                (timestamp, "a" * 64, timestamp),
            )
    finally:
        runtime.database.close()
