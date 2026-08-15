from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.delivery.application.delivery_dispatch_service import (
    DeliveryOutboxDispatcher,
)
from app.modules.agent.application.agent_result_service import AgentResultService
from app.modules.file_workspace.delivery_service import FileVersionDeliveryService
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
    assert event["file_version_id"] == committed["version_id"]
    assert event["file_content_sha256"] == committed["sha256"]
    assert event["session_id"] == "session-file"
    assert event["principal_user_id"] == "user-a"

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
