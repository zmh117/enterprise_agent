from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from app.modules.job.infrastructure.execution_audit_repository import (
    ExecutionAuditRepository,
    _classify_failure,
)
from app.modules.job.domain.execution_audit import ExecutionFailureStage
from app.modules.job.infrastructure.repositories import AgentRepository
from app.shared.database import Database, default_migrations_dir
from app.shared.exceptions import NonRetryableExecutionError
from app.shared.migrations import Migrator


def _database(
    tmp_path: Path,
    *,
    protocol_version: str = "1.2",
) -> tuple[Database, str]:
    database = Database(f"sqlite:///{tmp_path / 'agent-run-audit.db'}")
    Migrator(database, default_migrations_dir(), migrator_build="agent-run-audit-repository-test").run()
    timestamp = "2026-08-12T00:00:00+00:00"
    database.execute(
        """
        insert into agent_session
          (id, project_code, created_at, updated_at, source_channel,
           source_connector_id, external_conversation_id, requester_id, session_key)
        values ('audit-session', 'default', ?, ?, 'test', 'connector-test',
                'audit-conversation', 'audit-user', 'audit-session-key')
        """,
        (timestamp, timestamp),
    )
    database.execute(
        """
        insert into agent_job
          (id, session_id, idempotency_key, project_code, status, created_at,
           source_channel, source_connector_id, requester_id,
           agent_runtime_protocol_version)
        values ('audit-job', 'audit-session', 'audit-job-key', 'default',
                'SUCCEEDED', ?, 'test', 'connector-test', 'audit-user', ?)
        """,
        (timestamp, protocol_version),
    )
    return database, "audit-job"


def _events() -> list[dict[str, object]]:
    fixture = json.loads(
        Path("contracts/agent-runtime/v1.2/golden/safe-runtime-fixture.json").read_text(
            encoding="utf-8"
        )
    )
    identity = {
        "protocol_version": "1.2",
        "invocation_id": "invocation-1",
        "request_digest": fixture["terminal_event"]["request_digest"],
    }
    return [
        {
            **identity,
            "sequence": 1,
            "event_type": "execution_started",
            "timestamp": "2026-08-12T00:00:00Z",
            "payload": {"runtime_kind": "typescript-v1"},
        },
        fixture["runtime_initialized_event"],
        fixture["model_call_event"],
        fixture["api_retry_event"],
        fixture["terminal_event"],
    ]


def test_runtime_events_are_idempotently_projected_and_summary_is_rebuilt(
    tmp_path: Path,
) -> None:
    database, job_id = _database(tmp_path)
    repository = ExecutionAuditRepository(database)

    for event in _events():
        repository.record_runtime_event(job_id, event)
    for event in _events():
        repository.record_runtime_event(job_id, event)

    summary = repository.rebuild_summary(job_id)
    model_calls = repository.list_model_calls(job_id, limit=20)

    assert summary["accounting_status"] == "COMPLETE"
    assert summary["observed_model_turn_count"] == 1
    assert summary["api_retry_count"] == 1
    assert summary["runtime_invocation_count"] == 1
    assert summary["total_duration_ms"] == 2400
    assert summary["total_api_duration_ms"] == 1800
    assert summary["input_tokens"] == 120
    assert summary["output_tokens"] == 32
    assert summary["cache_creation_input_tokens"] == 8
    assert summary["cache_read_input_tokens"] == 16
    assert summary["estimated_cost_usd"] == "0.012345000000"
    assert summary["execution_status"] == "SUCCEEDED"
    assert summary["execution_failure_stage"] is None
    assert summary["retry_exhausted"] is False
    assert summary["model_usage"] == fixture_model_usage()
    assert len(model_calls["items"]) == 1
    assert model_calls["items"][0]["duration_source"] == "SDK_OBSERVED"
    assert model_calls["items"][0]["duration_ms"] == 1000
    assert model_calls["next_cursor"] is None
    assert len(AgentRepository(database).list_runtime_events(job_id)) == 5


def test_conflicting_model_call_replay_is_rejected(tmp_path: Path) -> None:
    database, job_id = _database(tmp_path)
    repository = ExecutionAuditRepository(database)
    events = _events()
    for event in events[:3]:
        repository.record_runtime_event(job_id, event)
    conflict = json.loads(json.dumps(events[2]))
    conflict["payload"]["usage"]["output_tokens"] = 999

    with pytest.raises(NonRetryableExecutionError, match="conflicts"):
        repository.record_runtime_event(job_id, conflict)


def test_repeated_model_message_identity_projects_once_without_data_migration(
    tmp_path: Path,
) -> None:
    database, job_id = _database(tmp_path)
    repository = ExecutionAuditRepository(database)
    events = _events()
    for event in events[:3]:
        repository.record_runtime_event(job_id, event)
    duplicate = json.loads(json.dumps(events[2]))
    duplicate["sequence"] = 4
    duplicate["timestamp"] = "2026-08-12T00:00:02Z"
    duplicate["payload"]["completed_at"] = "2026-08-12T00:00:02Z"
    repository.record_runtime_event(job_id, duplicate)
    duplicate["sequence"] = 5
    duplicate["timestamp"] = "2026-08-12T00:00:03Z"
    duplicate["payload"]["completed_at"] = "2026-08-12T00:00:03Z"
    repository.record_runtime_event(job_id, duplicate)

    summary = repository.rebuild_summary(job_id)

    assert len(AgentRepository(database).list_runtime_events(job_id)) == 5
    assert len(repository.list_model_calls(job_id)["items"]) == 1
    assert summary["accounting_status"] == "PARTIAL"
    assert summary["observed_model_turn_count"] == 1
    assert summary["input_tokens"] == 120
    assert summary["output_tokens"] == 32


def test_repeated_model_message_identity_rejects_conflicting_measurements(
    tmp_path: Path,
) -> None:
    database, job_id = _database(tmp_path)
    repository = ExecutionAuditRepository(database)
    events = _events()
    for event in events[:3]:
        repository.record_runtime_event(job_id, event)
    conflict = json.loads(json.dumps(events[2]))
    conflict["sequence"] = 4
    conflict["payload"]["usage"]["output_tokens"] = 999

    with pytest.raises(NonRetryableExecutionError, match="conflicts"):
        repository.record_runtime_event(job_id, conflict)

    assert len(AgentRepository(database).list_runtime_events(job_id)) == 3
    assert len(repository.list_model_calls(job_id)["items"]) == 1


def test_model_call_cursor_preserves_numeric_sequence_order(tmp_path: Path) -> None:
    database, job_id = _database(tmp_path)
    repository = ExecutionAuditRepository(database)
    template = _events()[2]
    for sequence in range(1, 11):
        event = json.loads(json.dumps(template))
        event["sequence"] = sequence
        event["payload"]["model_call_id"] = f"model-call-{sequence}"
        if sequence not in {1, 10}:
            event["event_type"] = "tool_event"
            event["payload"] = {"tool_name": "safe-tool", "status": "SUCCEEDED"}
        repository.record_runtime_event(job_id, event)

    first_page = repository.list_model_calls(job_id, limit=1)
    second_page = repository.list_model_calls(
        job_id,
        limit=1,
        cursor=first_page["next_cursor"],
    )

    assert [item["runtime_sequence"] for item in first_page["items"]] == [1]
    assert first_page["has_more"] is True
    assert [item["runtime_sequence"] for item in second_page["items"]] == [10]
    assert second_page["has_more"] is False


def test_summary_preserves_unknowns_when_terminal_accounting_is_unavailable(
    tmp_path: Path,
) -> None:
    database, job_id = _database(tmp_path)
    repository = ExecutionAuditRepository(database)
    event = _events()[0]
    repository.record_runtime_event(job_id, event)

    summary = repository.rebuild_summary(job_id)

    assert summary["accounting_status"] == "UNAVAILABLE"
    assert summary["input_tokens"] is None
    assert summary["total_duration_ms"] is None
    assert summary["estimated_cost_usd"] is None


def test_summary_accepts_current_runtime_protocol_v13(tmp_path: Path) -> None:
    database, job_id = _database(tmp_path, protocol_version="1.3")

    summary = ExecutionAuditRepository(database).rebuild_summary(job_id)

    assert summary["source_protocol_version"] == "1.3"
    assert summary["accounting_status"] == "UNAVAILABLE"


def test_protocol_v13_migration_preserves_existing_execution_summary(
    tmp_path: Path,
) -> None:
    source_migrations = default_migrations_dir()
    staged_migrations = tmp_path / "migrations"
    staged_migrations.mkdir()
    shutil.copy2(
        source_migrations / "legacy-v1-manifest.json",
        staged_migrations / "legacy-v1-manifest.json",
    )
    for source in source_migrations.glob("*.sql"):
        if int(source.name.split("_", 1)[0]) <= 113:
            shutil.copy2(source, staged_migrations / source.name)

    database = Database(f"sqlite:///{tmp_path / 'protocol-v13-migration.db'}")
    first = Migrator(
        database,
        staged_migrations,
        migrator_build="protocol-v13-before",
    ).run()
    assert first.head == "113"

    timestamp = "2026-08-18T00:00:00+00:00"
    database.execute(
        """
        insert into agent_session
          (id, project_code, created_at, updated_at, source_channel,
           source_connector_id, external_conversation_id, requester_id, session_key)
        values ('protocol-v13-session', 'default', ?, ?, 'test', 'connector-test',
                'protocol-v13-conversation', 'audit-user', 'protocol-v13-session')
        """,
        (timestamp, timestamp),
    )
    database.execute(
        """
        insert into agent_job
          (id, session_id, idempotency_key, project_code, status, created_at,
           source_channel, source_connector_id, requester_id,
           agent_runtime_protocol_version)
        values ('protocol-v13-job', 'protocol-v13-session', 'protocol-v13-job',
                'default', 'FAILED', ?, 'test', 'connector-test', 'audit-user', '1.2')
        """,
        (timestamp,),
    )
    database.execute(
        """
        insert into agent_job_execution_summary
          (job_id, accounting_status, observed_model_turn_count, api_retry_count,
           runtime_invocation_count, model_usage_json, execution_status,
           failure_code, retry_exhausted, source_protocol_version,
           created_at, updated_at)
        values ('protocol-v13-job', 'PARTIAL', 2, 1, 1, '[]', 'FAILED',
                'safe_failure', 1, '1.2', ?, ?)
        """,
        (timestamp, timestamp),
    )

    shutil.copy2(
        source_migrations / "114_expand_execution_summary_protocol_v13.sql",
        staged_migrations / "114_expand_execution_summary_protocol_v13.sql",
    )
    upgraded = Migrator(
        database,
        staged_migrations,
        migrator_build="protocol-v13-after",
    ).run()

    assert upgraded.applied == ("114",)
    assert database.execute_one(
        """
        select accounting_status, observed_model_turn_count, api_retry_count,
               runtime_invocation_count, execution_status, failure_code,
               retry_exhausted, source_protocol_version, created_at
          from agent_job_execution_summary
         where job_id = 'protocol-v13-job'
        """
    ) == {
        "accounting_status": "PARTIAL",
        "observed_model_turn_count": 2,
        "api_retry_count": 1,
        "runtime_invocation_count": 1,
        "execution_status": "FAILED",
        "failure_code": "safe_failure",
        "retry_exhausted": 1,
        "source_protocol_version": "1.2",
        "created_at": timestamp,
    }

    database.execute(
        """
        update agent_job
           set agent_runtime_protocol_version = '1.3'
         where id = 'protocol-v13-job'
        """
    )
    summary = ExecutionAuditRepository(database).rebuild_summary("protocol-v13-job")
    assert summary["source_protocol_version"] == "1.3"


def test_multi_invocation_retry_replay_and_rebuild_never_double_count(
    tmp_path: Path,
) -> None:
    database, job_id = _database(tmp_path)
    repository = ExecutionAuditRepository(database)
    first_attempt = _events()
    second_attempt = json.loads(json.dumps(first_attempt))
    for event in second_attempt:
        event["invocation_id"] = "invocation-2"
        event["request_digest"] = "b" * 64

    # Replaying both attempt streams simulates duplicate MQ delivery after a retry.
    for event in first_attempt + second_attempt + first_attempt + second_attempt:
        repository.record_runtime_event(job_id, event)

    first_rebuild = repository.rebuild_summary(job_id)
    second_rebuild = repository.rebuild_summary(job_id)

    assert {key: value for key, value in second_rebuild.items() if key != "updated_at"} == {
        key: value for key, value in first_rebuild.items() if key != "updated_at"
    }
    assert second_rebuild["runtime_invocation_count"] == 2
    assert second_rebuild["observed_model_turn_count"] == 2
    assert second_rebuild["input_tokens"] == 240
    assert second_rebuild["output_tokens"] == 64
    assert second_rebuild["estimated_cost_usd"] == "0.024690000000"
    assert len(repository.list_model_calls(job_id)["items"]) == 2


def test_job_delete_cascades_execution_audit_projections(tmp_path: Path) -> None:
    database, job_id = _database(tmp_path)
    repository = ExecutionAuditRepository(database)
    for event in _events():
        repository.record_runtime_event(job_id, event)
    repository.rebuild_summary(job_id)

    # Existing detailed Runtime evidence has an independent cleanup order.
    database.execute("delete from agent_runtime_event where job_id = ?", (job_id,))
    database.execute("delete from agent_job where id = ?", (job_id,))

    assert database.execute("select * from agent_job_execution_summary") == []
    assert database.execute("select * from agent_model_call") == []


def fixture_model_usage() -> list[dict[str, object]]:
    return [
        {
            "canonical_model": "claude-safe-model",
            "estimated_cost_usd": "0.012345000000",
            "model_id": "claude-safe-model",
            "provider": "firstParty",
            "usage": {
                "cache_creation_input_tokens": 8,
                "cache_read_input_tokens": 16,
                "input_tokens": 120,
                "output_tokens": 32,
            },
        }
    ]


def test_runtime_event_projection_omits_execution_content_and_secret_material(
    tmp_path: Path,
) -> None:
    database, job_id = _database(tmp_path)
    repository = ExecutionAuditRepository(database)
    events = _events()
    events[-1]["payload"]["final_answer"] = "full-answer-must-not-persist"
    events[-1]["payload"]["raw_sdk_message"] = {
        "authorization": "secret-must-not-persist"
    }
    for event in events:
        repository.record_runtime_event(job_id, event)

    serialized = json.dumps(AgentRepository(database).list_runtime_events(job_id))

    assert "full-answer-must-not-persist" not in serialized
    assert "secret-must-not-persist" not in serialized
    assert "raw_sdk_message" not in serialized


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        (
            {"event_type": "terminal", "payload": {"status": "FAILED", "failure": {"code": "runtime_transport_error"}}},
            ExecutionFailureStage.RUNTIME_START,
        ),
        (
            {"event_type": "terminal", "payload": {"status": "FAILED", "failure": {"code": "runtime_protocol_error"}}},
            ExecutionFailureStage.RUNTIME_PROTOCOL,
        ),
        (
            {"event_type": "runtime_initialized", "payload": {"mcp_servers": [{"server_code": "ones-mcp", "status": "FAILED"}]}},
            ExecutionFailureStage.MCP_CONNECTION,
        ),
        (
            {"event_type": "model_call", "payload": {"status": "FAILED", "error_code": "runtime_model_api_error"}},
            ExecutionFailureStage.MODEL_API,
        ),
        (
            {"event_type": "tool_event", "payload": {"status": "DENIED", "error_code": "tool_denied"}},
            ExecutionFailureStage.TOOL_PERMISSION,
        ),
        (
            {"event_type": "tool_event", "payload": {"status": "FAILED", "error_code": "tool_failed"}},
            ExecutionFailureStage.TOOL_EXECUTION,
        ),
        (
            {"event_type": "terminal", "payload": {"status": "FAILED", "failure": {"code": "other_typed_error"}}},
            ExecutionFailureStage.UNKNOWN,
        ),
    ],
)
def test_failure_classifier_uses_typed_evidence_only(
    event: dict[str, object], expected: ExecutionFailureStage
) -> None:
    stage, _code, _summary = _classify_failure([event])
    assert stage == expected
