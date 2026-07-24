from __future__ import annotations

import hashlib
import json

import pytest

from app.modules.delivery.infrastructure.adapters import DeliveryAdapter
from app.modules.agent.domain.runtime import ToolCallBudget
from app.modules.job.application.create_agent_job_service import CreateAgentJobCommand
from app.modules.job.application.legacy_runtime_purge_service import (
    LegacyRuntimePurgeService,
)
from app.modules.job.domain.execution_policy import (
    EffectiveExecutionPolicyResolver,
    JobExecutionPolicySnapshot,
)
from app.modules.job.domain.job_status import JobStatus
from app.modules.message_bus.application.message_publisher import AgentJobMessage
from app.shared.config import ExecutionSettings
from app.shared.exceptions import ExecutionPolicyExceeded, NonRetryableExecutionError
from app.workers.agent_job_worker import AgentJobWorker
from backend.tests.helpers import container


class _CaptureFailureDeliveryAdapter(DeliveryAdapter):
    def __init__(self) -> None:
        self.messages: list[str] = []

    def send(self, *, connector: object, route: object, title: str, text: str) -> None:
        del connector, route, title
        self.messages.append(text)


def test_business_application_policy_only_tightens_agent_limits() -> None:
    resolver = EffectiveExecutionPolicyResolver(
        ExecutionSettings(max_turns=20, timeout_seconds=600, max_tool_calls=30)
    )
    snapshot = resolver.resolve(
        application_policy={
            "max_turns": 40,
            "timeout_seconds": 120,
            "max_tool_calls": 0,
        },
        agent_snapshot={
            "execution": {"max_turns": 12, "timeout_seconds": 300}
        },
        sources={
            "business_application_publication_id": "app-publication",
            "agent_publication_id": "agent-publication",
        },
    )

    assert snapshot.requested.to_dict() == {
        "max_turns": 40,
        "timeout_seconds": 120,
        "max_tool_calls": 0,
    }
    assert snapshot.effective.to_dict() == {
        "max_turns": 12,
        "timeout_seconds": 120,
        "max_tool_calls": 0,
    }
    assert snapshot.sources["source_kind"] == "business_application"


def test_non_business_job_uses_versioned_runtime_default_snapshot() -> None:
    c = container()
    job = c.create_agent_job_service.execute(
        CreateAgentJobCommand(
            idempotency_key="policy-default",
            dingding_conversation_id="conversation-policy",
            dingding_user_id="local-user",
            user_message="check",
        )
    )

    parsed = JobExecutionPolicySnapshot.from_dict(job.execution_policy)
    assert parsed.schema_version == 1
    assert parsed.sources["source_kind"] == "runtime_default"
    assert parsed.effective.max_tool_calls == c.settings.execution.max_tool_calls


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        {"schema_version": 2},
        {
            "schema_version": 1,
            "requested": {},
            "effective": {},
            "sources": {"source_kind": "runtime_default"},
        },
        {
            "schema_version": "1",
            "requested": {
                "max_turns": 12,
                "timeout_seconds": 300,
                "max_tool_calls": 30,
            },
            "effective": {
                "max_turns": 12,
                "timeout_seconds": 300,
                "max_tool_calls": 30,
            },
            "sources": {"source_kind": "runtime_default"},
        },
        {
            "schema_version": 1,
            "requested": {
                "max_turns": True,
                "timeout_seconds": 300,
                "max_tool_calls": 30,
            },
            "effective": {
                "max_turns": 1,
                "timeout_seconds": 300,
                "max_tool_calls": 30,
            },
            "sources": {"source_kind": "runtime_default"},
        },
    ],
)
def test_invalid_policy_snapshots_fail_closed(value: object) -> None:
    with pytest.raises(NonRetryableExecutionError) as raised:
        JobExecutionPolicySnapshot.from_dict(value)  # type: ignore[arg-type]
    assert raised.value.error_code == "execution_policy_integrity_error"


def test_repository_rejects_job_without_execution_policy() -> None:
    c = container()
    session = c.agent_repository.create_session(
        dingding_conversation_id="conversation",
        dingding_user_id="local-user",
        source="debug_api",
        project_code="default",
    )
    with pytest.raises(NonRetryableExecutionError):
        c.agent_repository.create_job(
            session_id=session.id,
            idempotency_key="missing-policy",
            user_id="local-user",
            project_code="default",
            source="debug_api",
            user_message="check",
            max_retry_count=0,
        )


def test_worker_rejects_missing_policy_before_context_tools_or_model() -> None:
    c = container()
    job = c.create_agent_job_service.execute(
        CreateAgentJobCommand(
            idempotency_key="invalid-worker-policy",
            dingding_conversation_id="conversation-invalid-policy",
            dingding_user_id="local-user",
            user_message="check",
        )
    )
    c.database.execute(
        "update agent_job set execution_policy_json = null where id = ?",
        (job.id,),
    )

    class RecordingClient:
        calls = 0

        def run(self, request: object) -> object:
            del request
            self.calls += 1
            raise AssertionError("model must not be called")

    client = RecordingClient()
    c.agent_executor.claude_client = client
    with pytest.raises(NonRetryableExecutionError) as raised:
        c.agent_executor.execute(job.id)

    assert raised.value.error_code == "execution_policy_integrity_error"
    assert client.calls == 0
    assert c.agent_repository.list_tool_calls(job.id) == []


def test_tool_budget_counts_rejected_attempt() -> None:
    budget = ToolCallBudget(maximum=1)
    budget.consume()
    with pytest.raises(ExecutionPolicyExceeded):
        budget.consume()
    assert budget.attempted == 2


def test_executor_persists_attempt_usage_and_exhaustion_separately_from_context_tools() -> None:
    c = container()
    job = c.create_agent_job_service.execute(
        CreateAgentJobCommand(
            idempotency_key="persist-policy-usage",
            dingding_conversation_id="conversation-policy-usage",
            dingding_user_id="local-user",
            user_message="check",
        )
    )
    tool_events = [
        {
            "tool_name": "query_database",
            "request_payload": {"sql": "select 1"},
            "response_summary": {"row_count": 1},
            "status": "SUCCEEDED",
            "duration_ms": 1,
            "risk_level": "medium",
        },
        {
            "tool_name": "query_database",
            "request_payload": {"sql": "select 1"},
            "response_summary": {"error": "budget exhausted"},
            "status": "REJECTED",
            "duration_ms": 0,
            "risk_level": "medium",
        },
    ]

    class ExhaustingClient:
        def run(self, request: object) -> object:
            del request
            raise ExecutionPolicyExceeded(
                "budget exhausted",
                safe_message="budget exhausted",
                error_code="execution_policy_max_tool_calls_exhausted",
                tool_events=tool_events,
            )

    c.agent_executor.claude_client = ExhaustingClient()
    with pytest.raises(ExecutionPolicyExceeded):
        c.agent_executor.execute(job.id)

    persisted = c.agent_repository.get_job(job.id)
    assert persisted.execution_policy_tool_call_count == 2
    assert persisted.execution_policy_exhausted is True


def test_worker_delivers_safe_non_retryable_tool_budget_failure_once() -> None:
    c = container()
    adapter = _CaptureFailureDeliveryAdapter()
    c.result_delivery_service.adapters["policy_failure_capture"] = adapter
    job = c.create_agent_job_service.execute(
        CreateAgentJobCommand(
            idempotency_key="worker-policy-exhaustion",
            dingding_conversation_id="conversation-policy-exhaustion",
            dingding_user_id="local-user",
            user_message="check",
            reply_route={"type": "policy_failure_capture", "target": {}},
        )
    )
    tool_events = [
        {
            "tool_name": "query_database",
            "request_payload": {"sql": "select 1"},
            "response_summary": {"row_count": 1},
            "status": "SUCCEEDED",
            "duration_ms": 1,
            "risk_level": "medium",
        },
        {
            "tool_name": "query_database",
            "request_payload": {},
            "response_summary": {"error": "tool call budget exhausted"},
            "status": "REJECTED",
            "duration_ms": 0,
            "risk_level": "medium",
        },
    ]

    class ExhaustingClient:
        def run(self, request: object) -> object:
            del request
            raise ExecutionPolicyExceeded(
                "internal detail must not be delivered",
                safe_message="Agent 工具调用次数已达到本次执行上限",
                error_code="execution_policy_max_tool_calls_exhausted",
                tool_events=tool_events,
            )

    c.agent_executor.claude_client = ExhaustingClient()
    worker = AgentJobWorker(c.settings, container=c)
    message = AgentJobMessage(job.id, "corr-policy-exhaustion")

    worker.handle(message)
    worker.handle(message)

    persisted = c.agent_repository.get_job(job.id)
    assert persisted.status == JobStatus.FAILED
    assert persisted.retry_count == 0
    assert persisted.last_error_code == "execution_policy_max_tool_calls_exhausted"
    assert persisted.execution_policy_tool_call_count == 2
    assert persisted.execution_policy_exhausted is True
    assert len(c.message_bus.retries) == 0
    assert len(c.message_bus.dead_letters) == 1
    assert len(adapter.messages) == 1
    delivered = json.loads(adapter.messages[0])
    assert delivered["error_code"] == "execution_policy_max_tool_calls_exhausted"
    assert "internal detail" not in delivered["message"]


def test_legacy_runtime_purge_preserves_control_plane() -> None:
    c = container()
    before_users = c.agent_repository.count_rows("app_user")
    before_agents = c.agent_repository.count_rows("agent_definition")
    job = c.create_agent_job_service.execute(
        CreateAgentJobCommand(
            idempotency_key="purge-policy-test",
            dingding_conversation_id="conversation-purge",
            dingding_user_id="local-user",
            user_message="check",
        )
    )
    message = c.agent_repository.list_messages(job.session_id)[0]
    attachment = c.agent_repository.add_attachment(
        message_id=str(message["id"]),
        job_id=job.id,
        ordinal=1,
        media_type="file",
        file_name="legacy.txt",
        declared_mime="text/plain",
        credential_ciphertext="encrypted",
    )
    payload = b"legacy runtime object"
    digest = hashlib.sha256(payload).hexdigest()
    object_key = f"attachments/{attachment.id}/{digest}.txt"
    c.object_storage.put(
        key=object_key,
        data=payload,
        content_type="text/plain",
        sha256=digest,
    )
    c.database.execute(
        """
        update message_attachment
        set object_bucket = ?, object_key = ?
        where id = ?
        """,
        (c.settings.object_storage.bucket, object_key, attachment.id),
    )
    before_control_audits = int(
        c.database.execute_one(
            "select count(*) as count from audit_event where job_id is null"
        )["count"]
    )
    service = LegacyRuntimePurgeService(
        database=c.database,
        storage=c.object_storage,
        storage_bucket=c.settings.object_storage.bucket,
    )

    report = service.purge()

    assert report["after"]["runtime_rows"]["agent_job"] == 0
    assert report["after"]["runtime_rows"]["agent_session"] == 0
    assert c.agent_repository.count_rows("app_user") == before_users
    assert c.agent_repository.count_rows("agent_definition") == before_agents
    assert report["after"]["preserved_unattributed_audit_rows"] == before_control_audits
    assert c.object_storage.list_keys() == []
    with pytest.raises(Exception, match="execution_policy_json is required"):
        c.database.execute(
            """
            insert into agent_session
              (id, dingding_conversation_id, dingding_user_id, source, project_code,
               created_at, updated_at)
            values ('session-invalid', 'c', 'u', 'debug_api', 'default', 'now', 'now')
            """
        )
        c.database.execute(
            """
            insert into agent_job
              (id, session_id, idempotency_key, user_id, project_code, source,
               user_message, status, created_at)
            values (
              'job-invalid', 'session-invalid', 'job-invalid', 'u', 'default',
              'debug_api', 'x', 'PENDING', 'now'
            )
            """
        )


def test_legacy_runtime_purge_stops_before_database_delete_on_object_failure() -> None:
    c = container()
    job = c.create_agent_job_service.execute(
        CreateAgentJobCommand(
            idempotency_key="purge-object-failure",
            dingding_conversation_id="conversation-object-failure",
            dingding_user_id="local-user",
            user_message="check",
        )
    )
    message = c.agent_repository.list_messages(job.session_id)[0]
    attachment = c.agent_repository.add_attachment(
        message_id=str(message["id"]),
        job_id=job.id,
        ordinal=1,
        media_type="file",
        file_name="legacy.txt",
        declared_mime="text/plain",
        credential_ciphertext="encrypted",
    )
    c.database.execute(
        """
        update message_attachment
        set object_bucket = ?, object_key = 'attachments/failing.txt'
        where id = ?
        """,
        (c.settings.object_storage.bucket, attachment.id),
    )

    class FailingStorage:
        def delete(self, *, key: str) -> None:
            del key
            raise RuntimeError("storage unavailable")

    service = LegacyRuntimePurgeService(
        database=c.database,
        storage=FailingStorage(),  # type: ignore[arg-type]
        storage_bucket=c.settings.object_storage.bucket,
    )
    with pytest.raises(NonRetryableExecutionError) as raised:
        service.purge()

    assert raised.value.error_code == "legacy_runtime_object_delete_failed"
    assert c.agent_repository.count_rows("agent_job") == 1
    assert c.agent_repository.count_rows("message_attachment") == 1
