from __future__ import annotations

import sqlite3

import pytest

from app.modules.agent.application.agent_context_builder import AgentContextBuilder
from app.modules.job.application.create_agent_job_service import (
    CreateAgentJobCommand,
    _session_key,
)
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.helpers import container


def _command(*, key: str = "canonical-input") -> CreateAgentJobCommand:
    return CreateAgentJobCommand(
        idempotency_key=key,
        requester_id="local-user",
        external_conversation_id="conversation-canonical",
        user_message="canonical question",
        project_code="default",
        source_channel="dingding",
        source_connector_id="connector-dingtalk-stream-default",
        external_event_id=f"event:{key}",
    )


def test_job_creation_writes_only_canonical_session_job_and_message_facts() -> None:
    runtime = container()

    job = runtime.create_agent_job_service.execute(_command())

    session_row = runtime.database.execute_one(
        "select * from agent_session where id = ?", (job.session_id,)
    )
    job_row = runtime.database.execute_one("select * from agent_job where id = ?", (job.id,))
    message_row = runtime.database.execute_one(
        "select * from agent_message where id = ?", (job.input_message_id,)
    )
    assert session_row is not None
    assert job_row is not None
    assert message_row is not None
    session_columns = {
        row["name"] for row in runtime.database.execute("pragma table_info(agent_session)")
    }
    job_columns = {
        row["name"] for row in runtime.database.execute("pragma table_info(agent_job)")
    }
    assert {
        "dingding_conversation_id",
        "dingding_user_id",
        "source",
    }.isdisjoint(session_columns)
    assert {"user_id", "source", "user_message"}.isdisjoint(job_columns)
    assert job_row["input_message_id"] == message_row["id"]
    assert message_row["job_id"] == job.id
    assert message_row["session_id"] == job.session_id
    assert message_row["role"] == "user"
    assert job.input_message == "canonical question"
    assert job.input_message_state == "available"


def test_duplicate_ingress_reuses_the_same_job_and_canonical_message() -> None:
    runtime = container()

    first = runtime.create_agent_job_service.execute(_command(key="duplicate-input"))
    second = runtime.create_agent_job_service.execute(_command(key="duplicate-input"))

    assert second.id == first.id
    assert second.input_message_id == first.input_message_id
    assert runtime.agent_repository.count_rows("agent_job") == 1
    assert runtime.agent_repository.count_rows("agent_message") == 1
    assert runtime.agent_repository.count_rows("job_dispatch_outbox") == 1


def test_database_rejects_multiple_user_messages_for_one_job() -> None:
    runtime = container()
    job = runtime.create_agent_job_service.execute(_command(key="single-user-message"))

    with pytest.raises(sqlite3.IntegrityError):
        runtime.agent_repository.add_message(
            session_id=job.session_id,
            job_id=job.id,
            role="user",
            content="second question",
        )


def test_legacy_job_without_explicit_message_link_is_read_only_and_not_executable() -> None:
    runtime = container()
    session = runtime.agent_repository.create_session(
        project_code="default",
        source_channel="debug_api",
        source_connector_id="connector-debug-api",
        external_conversation_id="legacy-history",
        requester_id="local-user",
        session_key="legacy-history-session",
    )
    runtime.database.execute(
        "update agent_session set history_read_only = 1 where id = ?",
        (session.id,),
    )
    runtime.database.execute(
        """
        insert into agent_job
          (id, session_id, idempotency_key, project_code, status, retry_count,
           max_retry_count, source_channel, source_connector_id, requester_id,
           created_at, input_message_id)
        values ('legacy-job', ?, 'legacy-job', 'default', 'FAILED', 0, 0,
                'debug_api', 'connector-debug-api', 'local-user',
                '2026-08-12T00:00:00Z', null)
        """,
        (session.id,),
    )

    job = runtime.agent_repository.get_job("legacy-job")
    detail = runtime.agent_repository.get_job_detail("legacy-job")

    assert job.input_message is None
    assert job.input_message_state == "legacy_message_unavailable"
    assert detail["input_message_state"] == "legacy_message_unavailable"
    assert detail["business_application_runtime_status"] == "legacy_unattributed"
    with pytest.raises(NonRetryableExecutionError) as raised:
        AgentContextBuilder(
            tool_registry=None,  # type: ignore[arg-type]
            skill_loader=None,  # type: ignore[arg-type]
        ).build(job)
    assert raised.value.error_code == "legacy_message_unavailable"


def test_job_detail_projects_canonical_facts_to_the_stable_query_shape() -> None:
    runtime = container()
    job = runtime.create_agent_job_service.execute(_command(key="detail-projection"))

    detail = runtime.agent_repository.get_job_detail(job.id)

    assert detail["user_id"] == "local-user"
    assert detail["requester_id"] == "local-user"
    assert detail["source"] == "dingding"
    assert detail["source_channel"] == "dingding"
    assert detail["user_message"] == "canonical question"
    assert detail["input_message_id"] == job.input_message_id
    assert detail["input_message_state"] == "available"


def test_session_key_isolates_project_publication_scope_and_external_identity() -> None:
    common = {
        "source_channel": "dingding",
        "connector_id": "connector-dingtalk-stream-default",
        "project_code": "project-a",
        "conversation_type": "direct",
        "conversation_id": "conversation-a",
        "requester_id": "local-user",
        "bot_identity": "robot-a",
        "external_identity_id": "identity-a",
        "business_application_id": "application-a",
        "business_application_publication_id": "publication-a",
        "execution_scope_hash": "scope-a",
        "conversation_mode": "channel",
    }
    baseline = _session_key(**common)

    for field, changed in (
        ("project_code", "project-b"),
        ("business_application_publication_id", "publication-b"),
        ("execution_scope_hash", "scope-b"),
        ("external_identity_id", "identity-b"),
    ):
        assert _session_key(**{**common, field: changed}) != baseline


def test_retry_reads_the_original_canonical_message() -> None:
    runtime = container()
    job = runtime.create_agent_job_service.execute(_command(key="retry-message"))
    assert runtime.agent_repository.claim_job(job.id, "worker-one") is not None
    runtime.agent_repository.schedule_retry(
        job.id,
        error_message="transient",
        error_code="temporary",
        next_retry_at="2026-08-12T00:00:00Z",
    )

    retried = runtime.agent_repository.get_job(job.id)

    assert retried.input_message_id == job.input_message_id
    assert retried.input_message == "canonical question"
