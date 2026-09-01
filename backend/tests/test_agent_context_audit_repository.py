from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.job.infrastructure.repositories import AgentRepository
from app.shared.database import Database, default_migrations_dir
from app.shared.exceptions import NonRetryableExecutionError
from app.shared.migrations import Migrator


def _repository(tmp_path: Path) -> tuple[AgentRepository, str]:
    database = Database(f"sqlite:///{tmp_path / 'context-audit.db'}")
    Migrator(database, default_migrations_dir(), migrator_build="context-audit-test").run()
    timestamp = "2026-09-01T00:00:00+00:00"
    database.execute(
        """
        insert into agent_session
          (id, project_code, created_at, updated_at, source_channel,
           source_connector_id, external_conversation_id, requester_id, session_key)
        values ('session-audit', 'default', ?, ?, 'test', 'connector-test',
                'conversation-audit', 'user-audit', 'session-key-audit')
        """,
        (timestamp, timestamp),
    )
    database.execute(
        """
        insert into agent_job
          (id, session_id, idempotency_key, project_code, status, created_at,
           source_channel, source_connector_id, requester_id,
           agent_runtime_protocol_version)
        values ('job-audit', 'session-audit', 'job-audit-key', 'default',
                'SUCCEEDED', ?, 'test', 'connector-test', 'user-audit', '1.5')
        """,
        (timestamp,),
    )
    return AgentRepository(database), "job-audit"


def _audit(marker: str = "完整未脱敏正文") -> dict[str, object]:
    return {
        "started_at": "2026-09-01T00:00:01+00:00",
        "finished_at": "2026-09-01T00:00:02+00:00",
        "context_manifest": {"sources": [{"content": marker}]},
        "system_prompt": f"system::{marker}",
        "user_prompt": f"user::{marker}",
        "tool_definitions": [{"name": "mcp__example", "schema": {"type": "object"}}],
        "permission_snapshot": {"allowed_tools": ["mcp__example"]},
        "init_snapshot": {"tools": ["mcp__example"]},
        "sdk_messages": [{"data": {"content": marker}}],
        "api_requests": [{"body": {"messages": [marker]}}],
        "api_responses": [{"body": {"content": marker}}],
        "tool_executions": [{"input": marker, "output": marker}],
        "model_requests": [{"usage": {"input_tokens": 17}}],
        "usage": {"result": {"input_tokens": 17, "output_tokens": 5}},
        "summary": {"model_request_count": 1, "max_request_context_tokens": 17},
        "raw_api_capture_status": "captured",
        "provider_thinking_disclosure": "只保存 Provider 实际暴露内容",
        "error": {},
    }


def test_complete_audit_is_unfiltered_and_idempotent(tmp_path: Path) -> None:
    repository, job_id = _repository(tmp_path)
    audit = _audit("secret-like-business-text::api_key=kept-because-model-visible")

    first_id = repository.record_run_audit(
        job_id=job_id,
        invocation_id=f"{job_id}.attempt-0",
        request_digest="d" * 64,
        attempt_no=1,
        status="SUCCEEDED",
        audit=audit,
    )
    replay_id = repository.record_run_audit(
        job_id=job_id,
        invocation_id=f"{job_id}.attempt-0",
        request_digest="d" * 64,
        attempt_no=1,
        status="SUCCEEDED",
        audit=audit,
    )

    rows = repository.list_run_audits(job_id)
    assert replay_id == first_id
    assert len(rows) == 1
    assert rows[0]["system_prompt"] == audit["system_prompt"]
    assert rows[0]["api_responses"][0]["body"]["content"] in audit["system_prompt"]


def test_conflicting_invocation_replay_is_rejected(tmp_path: Path) -> None:
    repository, job_id = _repository(tmp_path)
    repository.record_run_audit(
        job_id=job_id,
        invocation_id=f"{job_id}.attempt-0",
        request_digest="d" * 64,
        attempt_no=1,
        status="FAILED",
        audit=_audit("first"),
    )

    with pytest.raises(NonRetryableExecutionError, match="conflicts"):
        repository.record_run_audit(
            job_id=job_id,
            invocation_id=f"{job_id}.attempt-0",
            request_digest="d" * 64,
            attempt_no=1,
            status="FAILED",
            audit=_audit("changed"),
        )
