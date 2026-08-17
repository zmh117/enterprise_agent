from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.delivery.application.delivery_dispatch_service import (
    DeliveryOutboxDispatcher,
)
from app.modules.delivery.application.report_chunker import ReportChunker
from app.modules.delivery.application.result_delivery_service import ResultDeliveryService
from app.modules.channel.infrastructure.connector_registry import Connector
from app.modules.agent.application.agent_result_service import AgentResultService
from app.modules.file_workspace.application import FileWorkspaceApplicationService
from app.modules.file_workspace.authorization import FileAuthorizationContext
from app.modules.file_workspace.delivery_service import FileVersionDeliveryService
from app.modules.file_workspace.domain import (
    FileAction,
    FileSourceKind,
    FileOwner,
    FileVersionKind,
    FileVersionStatus,
    WorkspaceOwnerType,
    WorkspaceFileRole,
)
from app.modules.file_workspace.lifecycle_service import FileLifecycleService
from app.modules.job.infrastructure.repositories import AgentRepository
from app.shared.config import DeliverySettings
from app.shared.exceptions import NonRetryableExecutionError, RetryableExecutionError
from backend.tests.test_file_commit_streaming import NOW, _body, _fixture, _new_intent


class _Authorization:
    def decide(self, **_: Any) -> dict[str, bool]:
        return {"allowed": True}


class _ConnectorRegistry:
    def require_delivery(self, connector_id: str) -> object:
        raise AssertionError(connector_id)


class _StreamFileConnectorRegistry(_ConnectorRegistry):
    def __init__(self) -> None:
        self.requested: list[str] = []

    def require_dingtalk_stream_file_delivery(self, connector_id: str) -> Connector:
        self.requested.append(connector_id)
        return Connector(
            id=connector_id,
            connector_type="dingtalk_enterprise_stream",
            name="stream-file",
            base_url="",
            enabled=True,
            allow_ingress=True,
            allow_delivery=False,
            secret_ref="secret://platform/test",
            endpoint_ref="",
            host_allowlist=(),
            metadata={},
        )


class _Audit:
    def record(self, *_: Any, **__: Any) -> None:
        return None


class _ResponseLostSender:
    def __init__(self, streaming: Any) -> None:
        self.streaming = streaming
        self.external_files: dict[str, bytes] = {}
        self.calls = 0

    def send(
        self,
        *,
        delivery_id: str,
        connector: object,
        route: object,
        idempotency_key: str,
    ) -> None:
        del connector, route
        self.calls += 1

        async def read() -> bytes:
            stream, _metadata = await self.streaming.download_delivery(
                delivery_id=delivery_id,
                service_claims={"sub": "delivery-worker"},
            )
            return b"".join([chunk async for chunk in stream])

        content = asyncio.run(read())
        self.external_files.setdefault(idempotency_key, content)
        if self.calls == 1:
            raise RetryableExecutionError(
                "simulated response loss after provider accepted file",
                safe_message="文件交付响应丢失",
                error_code="file_delivery_response_lost",
            )


class _AlwaysTimeoutSender:
    def send(self, **_: Any) -> None:
        raise RetryableExecutionError(
            "simulated provider timeout",
            safe_message="文件交付超时",
            error_code="file_delivery_timeout",
        )


class _AlwaysTerminalSender:
    def send(self, **_: Any) -> None:
        raise NonRetryableExecutionError(
            "simulated terminal provider rejection",
            safe_message="文件交付配置无效",
            error_code="file_delivery_terminal",
        )


class _CaptureTextAdapter:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def send(self, **arguments: Any) -> None:
        self.messages.append(str(arguments["text"]))


class _CaptureFileSender:
    def __init__(self) -> None:
        self.connector_ids: list[str] = []

    def send(self, **arguments: Any) -> None:
        self.connector_ids.append(str(arguments["connector"].id))


def _enable_file_delivery(repository: Any) -> None:
    repository.database.execute(
        """
        update agent_job
           set reply_route_json = ?, business_application_route_decision_json = ?
         where id = 'job-file'
        """,
        (
            json.dumps(
                {
                    "type": "dingtalk_conversation",
                    "connector_id": "",
                    "target": {"conversation_id": "conversation-a"},
                }
            ),
            json.dumps(
                {
                    "correlation_id": "correlation-file",
                    "task_file_features": {
                        "workspace_enabled": True,
                        "file_mcp_enabled": True,
                        "runtime_file_edit_enabled": True,
                        "default_file_delivery_enabled": True,
                    },
                }
            ),
        ),
    )


def test_exact_file_delivery_retries_without_agent_rerun_or_duplicate_file() -> None:
    repository, streaming, context, _storage = _fixture()
    _enable_file_delivery(repository)
    agent_repository = AgentRepository(repository.database)
    delivery = FileVersionDeliveryService(
        repository, agent_repository, DeliverySettings()
    )
    streaming.delivery_intents = delivery
    commit_id = _new_intent(streaming, context, handle="delivered-output")
    committed = asyncio.run(
        streaming.upload_commit(
            commit_id=commit_id,
            token="file-principal-token",
            body=_body(b"deliver this exact version\n"),
        )
    )
    event = repository.database.execute_one(
        """
        select * from delivery_outbox
         where job_id = 'job-file' and delivery_kind = 'FILE_VERSION'
        """
    )
    assert event is not None
    assert committed["file_id"] == event["file_id"]
    assert committed["delivery_id"] == event["id"]
    assert committed["delivery_status"] == "PENDING"
    assert event["file_version_id"] == committed["version_id"]
    assert event["file_content_sha256"] == committed["sha256"]
    assert event["session_id"] == "session-file"
    assert event["principal_user_id"] == "user-a"
    repeated = asyncio.run(
        streaming.upload_commit(
            commit_id=commit_id,
            token="file-principal-token",
            body=_body(b"deliver this exact version\n"),
        )
    )
    assert repeated == committed

    workspace_only = streaming.prepare_commit(
        context=context,
        arguments={
            "sandbox_entry_handle": "workspace-only-output",
            "display_name": "workspace-only.txt",
            "user_intent": "GENERATE",
            "delivery_mode": "WORKSPACE_ONLY",
        },
    )
    workspace_only_commit = str(
        workspace_only["__file_transfer_meta"]["enterprise-agent/file-transfer"][
            "commit_id"
        ]
    )
    asyncio.run(
        streaming.upload_commit(
            commit_id=workspace_only_commit,
            token="file-principal-token",
            body=_body(b"do not deliver\n"),
        )
    )
    assert repository.database.execute_one(
        "select count(*) as value from delivery_outbox where delivery_kind = 'FILE_VERSION'"
    ) == {"value": 1}

    repository.database.execute(
        "update agent_job set status = 'SUCCEEDED' where id = 'job-file'"
    )
    sender = _ResponseLostSender(streaming)
    delivery_runtime = SimpleNamespace(
        connector_registry=_ConnectorRegistry(),
        business_authorization_service=_Authorization(),
        adapters={},
    )
    dispatcher = DeliveryOutboxDispatcher(
        repository=agent_repository,
        delivery_service=delivery_runtime,  # type: ignore[arg-type]
        audit_service=_Audit(),  # type: ignore[arg-type]
        settings=DeliverySettings(),
        worker_id="delivery-worker",
        file_delivery_sender=sender,
        file_delivery_service=delivery,
    )
    first = dispatcher.dispatch_pending(limit=1)
    assert first.retrying == 1
    repository.database.execute(
        "update delivery_outbox set next_attempt_at = ? where id = ?",
        ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), event["id"]),
    )
    second = dispatcher.dispatch_pending(limit=1)
    assert second.succeeded == 1
    assert sender.calls == 2
    assert len(sender.external_files) == 1
    assert next(iter(sender.external_files.values())) == b"deliver this exact version\n"
    assert repository.database.execute_one(
        """
        select count(*) as value from file_retention_fact
         where version_id = ? and reason = 'DELIVERED'
        """,
        (committed["version_id"],),
    ) == {"value": 1}
    assert agent_repository.get_job("job-file").status.value == "SUCCEEDED"
    AgentResultService(agent_repository).save_result(
        agent_repository.get_job("job-file"), "normal Runtime reply"
    )
    file_results = agent_repository.get_artifact_for_job(
        job_id="job-file",
        artifact_type="file_commit_results",
        name="file-commit-results.json",
    )
    assert file_results is not None
    result_payload = json.loads(str(file_results["content"]))
    assert result_payload["status"] == "SUCCEEDED"
    assert [item["status"] for item in result_payload["files"]] == [
        "COMMITTED",
        "COMMITTED",
    ]
    assert "PARTIAL" not in json.dumps(result_payload)


def test_explicit_delivery_accepts_exact_version_committed_by_current_job() -> None:
    repository, streaming, context, _storage = _fixture()
    _enable_file_delivery(repository)
    delivery = FileVersionDeliveryService(
        repository, AgentRepository(repository.database), DeliverySettings()
    )
    committed = asyncio.run(
        streaming.upload_commit(
            commit_id=_new_intent(streaming, context, handle="explicit-output"),
            token="file-principal-token",
            body=_body(b"explicit delivery\n"),
        )
    )
    version = repository.get_version(str(committed["version_id"]))
    streaming.delivery_intents = delivery
    application = FileWorkspaceApplicationService(
        repository,
        streaming.authorization,
        streaming,
    )

    first = application.invoke(
        context=context,
        tool_identifier="file_deliver_version",
        arguments={
            "file_id": str(version["file_id"]),
            "version_id": str(version["id"]),
        },
    )
    repeated = application.invoke(
        context=context,
        tool_identifier="file_deliver_version",
        arguments={
            "file_id": str(version["file_id"]),
            "version_id": str(version["id"]),
        },
    )

    assert first["delivery_status"] == "PENDING"
    assert repeated == first
    assert repository.database.execute_one(
        "select count(*) as value from delivery_outbox where delivery_kind = 'FILE_VERSION'"
    ) == {"value": 1}


def test_text_v2_log_delivery_uses_existing_exact_version_without_commit() -> None:
    repository, streaming, context, storage = _fixture(
        file_format_policy_version="text-v2"
    )
    _enable_file_delivery(repository)
    log_content = b"immutable diagnostic log\n"
    object_key = storage.new_object_key(kind="attachment")
    storage.objects[object_key] = log_content
    repository.create_file(
        file_id="file-log",
        tenant_id="tenant-a",
        owner=FileOwner(WorkspaceOwnerType.PRIVATE_USER, user_id="user-a"),
        display_name="service.log",
        actor_id="file-worker",
        format_code="LOG",
    )
    repository.create_version(
        version_id="version-log-1",
        file_id="file-log",
        version_number=1,
        version_kind=FileVersionKind.ATTACHMENT,
        status=FileVersionStatus.AVAILABLE,
        media_type="text/plain",
        encoding="utf-8",
        size_bytes=len(log_content),
        content_sha256=hashlib.sha256(log_content).hexdigest(),
        object_key=object_key,
        source_kind=FileSourceKind.MESSAGE_ATTACHMENT,
        actor_id="file-worker",
        format_code="LOG",
        advance_current_from="",
    )
    repository.link_workspace_file(
        workspace_id="workspace-a",
        file_id="file-log",
        version_id="version-log-1",
        logical_name="service.log",
        role=WorkspaceFileRole.INPUT,
    )
    repository.database.execute(
        """
        insert into agent_job_file_snapshot_item
          (id, snapshot_id, ordinal, file_id, version_id, display_name,
           format_code, source_kind, allowed_actions_json, auto_materialize,
           conflict_candidate, version_created_at, created_at)
        values ('snapshot-log-item', 'snapshot-file', 1, 'file-log',
                'version-log-1', 'service.log', 'LOG', 'WORKSPACE', ?, 0, 0, ?, ?)
        """,
        (
            json.dumps(
                [
                    FileAction.READ_METADATA.value,
                    FileAction.MATERIALIZE.value,
                    FileAction.RETAIN.value,
                    FileAction.DELIVER.value,
                ]
            ),
            NOW.isoformat(),
            NOW.isoformat(),
        ),
    )
    refreshed = FileAuthorizationContext(
        context.claims,
        context.job,
        context.workspace,
        repository.get_job_snapshot("job-file"),
    )
    delivery = FileVersionDeliveryService(
        repository,
        AgentRepository(repository.database),
        DeliverySettings(),
    )
    streaming.delivery_intents = delivery
    before_versions = repository.database.execute_one(
        "select count(*) as value from managed_file_version"
    )

    first = streaming.deliver_version(
        context=refreshed,
        arguments={"file_id": "file-log", "version_id": "version-log-1"},
    )
    repeated = streaming.deliver_version(
        context=refreshed,
        arguments={"file_id": "file-log", "version_id": "version-log-1"},
    )

    assert repeated == first
    assert delivery.exact_binding(first["delivery_id"])["file_version_id"] == (
        "version-log-1"
    )
    assert repository.database.execute_one(
        "select count(*) as value from managed_file_version"
    ) == before_versions
    assert repository.database.execute_one(
        "select count(*) as value from file_commit_intent"
    ) == {"value": 0}


def test_text_v2_markdown_default_delivery_and_workspace_only_remain_distinct() -> None:
    repository, streaming, context, _storage = _fixture(
        file_format_policy_version="text-v2"
    )
    _enable_file_delivery(repository)
    streaming.delivery_intents = FileVersionDeliveryService(
        repository,
        AgentRepository(repository.database),
        DeliverySettings(),
    )
    delivered = asyncio.run(
        streaming.upload_commit(
            commit_id=_new_intent(
                streaming,
                context,
                handle="markdown-delivered",
                display_name="report.md",
            ),
            token="file-principal-token",
            body=_body(b"# delivered\n"),
        )
    )
    workspace_only = streaming.prepare_commit(
        context=context,
        arguments={
            "sandbox_entry_handle": "markdown-workspace-only",
            "display_name": "notes.md",
            "user_intent": "GENERATE",
            "delivery_mode": "WORKSPACE_ONLY",
        },
    )
    workspace_only_commit = str(
        workspace_only["__file_transfer_meta"]["enterprise-agent/file-transfer"][
            "commit_id"
        ]
    )
    retained = asyncio.run(
        streaming.upload_commit(
            commit_id=workspace_only_commit,
            token="file-principal-token",
            body=_body(b"# retained\n"),
        )
    )

    assert delivered["format_code"] == "MARKDOWN"
    assert delivered["delivery_status"] == "PENDING"
    assert retained["format_code"] == "MARKDOWN"
    assert retained["delivery_status"] == "NOT_REQUESTED"
    assert repository.database.execute_one(
        "select count(*) as value from delivery_outbox where delivery_kind = 'FILE_VERSION'"
    ) == {"value": 1}


def test_stream_session_file_delivery_uses_originating_stream_connector() -> None:
    repository, streaming, context, _storage = _fixture()
    repository.database.execute(
        """
        update agent_job
           set reply_route_json = ?, business_application_route_decision_json = ?
         where id = 'job-file'
        """,
        (
            json.dumps(
                {
                    "type": "dingtalk_stream_session_webhook",
                    "connector_id": "",
                    "target": {
                        "conversation_id": "conversation-a",
                        "conversation_type": "direct",
                        "recipient_user_id": "staff-a",
                        "robot_code": "robot-a",
                        "session_webhook": "https://example.invalid/session",
                    },
                }
            ),
            json.dumps(
                {
                    "task_file_features": {
                        "default_file_delivery_enabled": True,
                    }
                }
            ),
        ),
    )
    agent_repository = AgentRepository(repository.database)
    delivery = FileVersionDeliveryService(
        repository, agent_repository, DeliverySettings()
    )
    streaming.delivery_intents = delivery
    asyncio.run(
        streaming.upload_commit(
            commit_id=_new_intent(streaming, context, handle="stream-output"),
            token="file-principal-token",
            body=_body(b"stream delivery\n"),
        )
    )
    repository.database.execute(
        "update agent_job set status = 'SUCCEEDED' where id = 'job-file'"
    )
    connector_registry = _StreamFileConnectorRegistry()
    sender = _CaptureFileSender()
    dispatcher = DeliveryOutboxDispatcher(
        repository=agent_repository,
        delivery_service=SimpleNamespace(
            connector_registry=connector_registry,
            business_authorization_service=_Authorization(),
            adapters={},
        ),  # type: ignore[arg-type]
        audit_service=_Audit(),  # type: ignore[arg-type]
        settings=DeliverySettings(),
        worker_id="delivery-worker",
        file_delivery_sender=sender,
        file_delivery_service=delivery,
    )

    assert dispatcher.dispatch_pending(limit=1).succeeded == 1
    assert connector_registry.requested == ["connector-a"]
    assert sender.connector_ids == ["connector-a"]


def test_delivery_provenance_rejects_cross_session_mutation() -> None:
    repository, streaming, context, _storage = _fixture()
    _enable_file_delivery(repository)
    delivery = FileVersionDeliveryService(
        repository, AgentRepository(repository.database), DeliverySettings()
    )
    streaming.delivery_intents = delivery
    committed = asyncio.run(
        streaming.upload_commit(
            commit_id=_new_intent(streaming, context, handle="cross-session"),
            token="file-principal-token",
            body=_body(b"cross session must fail\n"),
        )
    )
    event = repository.database.execute_one(
        "select id from delivery_outbox where file_version_id = ?",
        (committed["version_id"],),
    )
    assert event is not None
    repository.database.execute(
        "update delivery_outbox set status = 'RUNNING', session_id = 'session-other' where id = ?",
        (event["id"],),
    )
    with pytest.raises(NonRetryableExecutionError) as captured:
        asyncio.run(
            streaming.download_delivery(
                delivery_id=str(event["id"]),
                service_claims={"sub": "delivery-worker"},
            )
        )
    assert captured.value.error_code == "file_delivery_provenance_mismatch"


def test_workspace_expiry_waits_for_file_delivery_then_cleans_after_terminal_failure() -> None:
    repository, streaming, context, storage = _fixture()
    _enable_file_delivery(repository)
    agent_repository = AgentRepository(repository.database)
    delivery = FileVersionDeliveryService(
        repository, agent_repository, DeliverySettings()
    )
    streaming.delivery_intents = delivery
    asyncio.run(
        streaming.upload_commit(
            commit_id=_new_intent(streaming, context, handle="timeout-output"),
            token="file-principal-token",
            body=_body(b"timeout but keep committed version\n"),
        )
    )
    event = repository.database.execute_one(
        "select id from delivery_outbox where delivery_kind = 'FILE_VERSION'"
    )
    assert event is not None
    repository.database.execute(
        "update agent_job set status = 'SUCCEEDED' where id = 'job-file'"
    )
    repository.database.execute(
        "update task_workspace set expires_at = ? where id = 'workspace-a'",
        ((NOW - timedelta(minutes=1)).isoformat(),),
    )
    lifecycle = FileLifecycleService(repository, storage, now=lambda: NOW)
    assert lifecycle.run_once()["workspaces_deferred"] == 1

    repository.database.execute(
        "update delivery_outbox set max_attempts = 1, next_attempt_at = ? where id = ?",
        ((NOW - timedelta(seconds=1)).isoformat(), event["id"]),
    )
    dispatcher = DeliveryOutboxDispatcher(
        repository=agent_repository,
        delivery_service=SimpleNamespace(
            connector_registry=_ConnectorRegistry(),
            business_authorization_service=_Authorization(),
            adapters={},
        ),  # type: ignore[arg-type]
        audit_service=_Audit(),  # type: ignore[arg-type]
        settings=DeliverySettings(),
        worker_id="delivery-worker",
        file_delivery_sender=_AlwaysTimeoutSender(),  # type: ignore[arg-type]
        file_delivery_service=delivery,
    )
    assert dispatcher.dispatch_pending(limit=1).dead == 1
    result = lifecycle.run_once()
    assert result["workspaces_expired"] == 1
    assert repository.get_workspace("workspace-a")["status"] == "CLEANED"


@pytest.mark.parametrize(
    ("sender", "expected_status"),
    [
        (_AlwaysTerminalSender(), "FAILED"),
        (_AlwaysTimeoutSender(), "DEAD"),
    ],
)
def test_terminal_file_delivery_failure_enqueues_one_non_recursive_notice(
    sender: object,
    expected_status: str,
) -> None:
    repository, streaming, context, _storage = _fixture()
    _enable_file_delivery(repository)
    repository.database.execute(
        "update agent_job set reply_route_json = ? where id = 'job-file'",
        (json.dumps({"type": "test_text", "target": {}}),),
    )
    agent_repository = AgentRepository(repository.database)
    file_delivery = FileVersionDeliveryService(
        repository, agent_repository, DeliverySettings()
    )
    streaming.delivery_intents = file_delivery
    committed = asyncio.run(
        streaming.upload_commit(
            commit_id=_new_intent(streaming, context, handle=f"notice-{expected_status}"),
            token="file-principal-token",
            body=_body(b"keep the committed file\n"),
        )
    )
    original_id = str(committed["delivery_id"])
    repository.database.execute(
        "update agent_job set status = 'SUCCEEDED' where id = 'job-file'"
    )
    if expected_status == "DEAD":
        repository.database.execute(
            "update delivery_outbox set max_attempts = 1 where id = ?",
            (original_id,),
        )
    text_adapter = _CaptureTextAdapter()
    delivery_runtime = ResultDeliveryService(
        repository=agent_repository,
        audit_service=_Audit(),  # type: ignore[arg-type]
        connector_registry=_ConnectorRegistry(),  # type: ignore[arg-type]
        adapters={"test_text": text_adapter},  # type: ignore[dict-item]
        chunker=ReportChunker(4000),
        settings=DeliverySettings(),
        business_authorization_service=_Authorization(),  # type: ignore[arg-type]
    )
    dispatcher = DeliveryOutboxDispatcher(
        repository=agent_repository,
        delivery_service=delivery_runtime,
        audit_service=_Audit(),  # type: ignore[arg-type]
        settings=DeliverySettings(),
        worker_id="delivery-worker",
        file_delivery_sender=sender,  # type: ignore[arg-type]
        file_delivery_service=file_delivery,
    )

    failed = dispatcher.dispatch_pending(limit=1)
    assert getattr(failed, "failed" if expected_status == "FAILED" else "dead") == 1
    assert agent_repository.get_delivery_event(original_id).status.value == expected_status
    notices = repository.database.execute(
        """
        select d.id, d.status, a.content
          from delivery_outbox d
          join agent_artifact a on a.id = d.result_artifact_id
         where a.artifact_type = 'file_delivery_failure_notification'
        """
    )
    assert len(notices) == 1
    assert notices[0]["status"] == "PENDING"
    assert "文件已保存到工作区" in str(notices[0]["content"])

    assert dispatcher.dispatch_pending(limit=10).succeeded == 1
    assert len(text_adapter.messages) == 1
    assert "回发失败" in text_adapter.messages[0]
    dispatcher.dispatch_pending(limit=10)
    assert repository.database.execute_one(
        """
        select count(*) as value from agent_artifact
         where artifact_type = 'file_delivery_failure_notification'
        """
    ) == {"value": 1}
    assert len(text_adapter.messages) == 1
    assert agent_repository.get_job("job-file").status.value == "SUCCEEDED"
    assert repository.get_version(str(committed["version_id"]))["status"] == "AVAILABLE"


def test_dispatcher_reconciles_crash_gap_for_terminal_file_delivery_notice() -> None:
    repository, streaming, context, _storage = _fixture()
    _enable_file_delivery(repository)
    repository.database.execute(
        "update agent_job set reply_route_json = ? where id = 'job-file'",
        (json.dumps({"type": "test_text", "target": {}}),),
    )
    agent_repository = AgentRepository(repository.database)
    file_delivery = FileVersionDeliveryService(
        repository, agent_repository, DeliverySettings()
    )
    streaming.delivery_intents = file_delivery
    committed = asyncio.run(
        streaming.upload_commit(
            commit_id=_new_intent(streaming, context, handle="crash-gap"),
            token="file-principal-token",
            body=_body(b"crash gap file\n"),
        )
    )
    repository.database.execute(
        "update agent_job set status = 'SUCCEEDED' where id = 'job-file'"
    )
    source_delivery_id = str(committed["delivery_id"])
    repository.database.execute(
        """
        update delivery_outbox
           set status = 'FAILED', last_error_code = 'synthetic_terminal',
               finished_at = ?, updated_at = ?
         where id = ?
        """,
        (NOW.isoformat(), NOW.isoformat(), source_delivery_id),
    )
    agent_repository.ensure_artifact(
        artifact_id=f"artifact_file_delivery_failure_{source_delivery_id}",
        job_id="job-file",
        artifact_type="file_delivery_failure_notification",
        name=f"file-delivery-failure-{source_delivery_id}.txt",
        content=(
            "文件已保存到工作区，但回发失败。"
            "你可以稍后要求我重新发送该文件。"
        ),
    )
    text_adapter = _CaptureTextAdapter()
    delivery_runtime = ResultDeliveryService(
        repository=agent_repository,
        audit_service=_Audit(),  # type: ignore[arg-type]
        connector_registry=_ConnectorRegistry(),  # type: ignore[arg-type]
        adapters={"test_text": text_adapter},  # type: ignore[dict-item]
        chunker=ReportChunker(4000),
        settings=DeliverySettings(),
        business_authorization_service=_Authorization(),  # type: ignore[arg-type]
    )
    dispatcher = DeliveryOutboxDispatcher(
        repository=agent_repository,
        delivery_service=delivery_runtime,
        audit_service=_Audit(),  # type: ignore[arg-type]
        settings=DeliverySettings(),
        file_delivery_service=file_delivery,
    )

    result = dispatcher.dispatch_pending(limit=10)
    assert result.failure_notices_enqueued == 1
    assert result.succeeded == 1
    assert len(text_adapter.messages) == 1
