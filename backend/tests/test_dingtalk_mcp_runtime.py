from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.external_action.domain import json_hash, normalize_todo_arguments
from app.modules.external_action.repository import ExternalActionRepository
from app.modules.external_action.service import ExternalActionService, ExternalActionTokenSigner
from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST
from app.python_runtime.tool_policy import contains_forbidden_tool_input
from app.shared.database import Database
from app.shared.exceptions import NonRetryableExecutionError
from services.dingtalk_mcp_server.contracts import TOOL_IDENTIFIER
from services.dingtalk_mcp_server.provider import (
    DingTalkCardClient,
    DingTalkTodoClient,
)
from services.dingtalk_mcp_server.worker import ExternalActionWorker


class _Audit:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def record(self, event_type: str, **values: Any) -> str:
        self.events.append((event_type, values))
        return f"audit-{len(self.events)}"


class _TokenClient:
    def access_token(self) -> str:
        return "test-access-token"


class _Transport:
    def __init__(self, response: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, str, dict[str, Any], dict[str, str], int]] = []
        self.response = response or {}

    def request_json(
        self,
        method: str,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        timeout_seconds: int,
    ) -> dict[str, Any]:
        self.calls.append((method, url, payload, headers, timeout_seconds))
        return self.response


def _database() -> Database:
    database = Database("sqlite:///:memory:")
    database.execute_script(
        """
        create table dingtalk_enterprise (id text primary key, corp_id text not null);
        insert into dingtalk_enterprise values ('enterprise-1', 'corp-1');
        create table external_action_intent (
          id text primary key, job_id text not null, session_id text not null,
          actor_user_id text not null, business_application_id text not null,
          agent_publication_id text not null, application_publication_id text not null,
          source_connector_id text not null, dingtalk_enterprise_id text not null,
          target_external_subject_id text not null, target_union_id text not null,
          server_code text not null, tool_identifier text not null, schema_hash text not null,
          confirmation_policy text not null, operation_code text not null,
          revision integer not null, status text not null, arguments_json text not null,
          arguments_hash text not null, safe_summary_json text not null, mcp_call_id text not null,
          expires_at text not null, approved_at text, rejected_at text,
          execution_claimed_by text not null default '', execution_claim_expires_at text,
          execution_attempts integer not null default 0, provider_request_id text not null default '',
          result_json text not null default '{}', last_error_code text not null default '',
          last_error_summary text not null default '', created_at text not null,
          updated_at text not null, completed_at text,
          unique(job_id, tool_identifier, arguments_hash)
        );
        create table external_action_card_outbox (
          id text primary key, action_intent_id text not null, event_kind text not null,
          status text not null, idempotency_key text not null unique, payload_json text not null,
          attempt_count integer not null, next_attempt_at text, claimed_by text not null default '',
          claim_expires_at text, last_error_code text not null default '',
          last_error_summary text not null default '', created_at text not null, updated_at text not null
        );
        """,
        ignore_existing_errors=False,
    )
    return database


def _facts() -> dict[str, str]:
    return {
        "job_id": "job-1",
        "session_id": "session-1",
        "actor_user_id": "user-1",
        "business_application_id": "application-1",
        "agent_publication_id": "agent-publication-1",
        "application_publication_id": "application-publication-1",
        "source_connector_id": "connector-1",
        "dingtalk_enterprise_id": "enterprise-1",
        "target_external_subject_id": "staff-1",
        "target_union_id": "union-1",
        "server_code": "dingtalk-mcp",
        "tool_identifier": "dingtalk_create_todo",
        "schema_hash": "a" * 64,
        "confirmation_policy": "external_action_card_v1",
        "operation_code": "dingtalk.todo.create",
    }


def test_todo_subject_is_business_input_not_a_principal_override() -> None:
    assert contains_forbidden_tool_input({"subject": "回访客户"}) is False
    assert contains_forbidden_tool_input({"sub": "forged-principal"}) is True
    assert contains_forbidden_tool_input({"actor_id": "forged-actor"}) is True
    assert contains_forbidden_tool_input({"user_id": "forged-user"}) is True


def test_intent_is_idempotent_and_only_original_actor_can_approve() -> None:
    database = _database()
    audit = _Audit()
    signer = ExternalActionTokenSigner("k" * 32)
    service = ExternalActionService(ExternalActionRepository(database), signer, audit)
    arguments = normalize_todo_arguments({"subject": "回访客户"}).as_dict()
    summary = {"operation": "创建钉钉待办", "subject": "回访客户", "due_time": ""}
    first, created = service.prepare(
        facts=_facts(),
        arguments=arguments,
        arguments_hash=json_hash(arguments),
        safe_summary=summary,
        mcp_call_id="mcp-call-1",
    )
    second, reused = service.prepare(
        facts=_facts(),
        arguments=arguments,
        arguments_hash=json_hash(arguments),
        safe_summary=summary,
        mcp_call_id="mcp-call-2",
    )
    assert created is True
    assert reused is False
    assert second["id"] == first["id"]
    assert database.execute_one(
        "select count(*) as count from external_action_card_outbox"
    )["count"] == 1

    token = signer.issue(str(first["id"]), 1)
    revised = service.handle_callback(
        connector_id="connector-1",
        corp_id="corp-1",
        out_track_id=str(first["id"]),
        user_id="staff-1",
        action="revise",
        revision=1,
        intent_token=token,
    )
    assert revised.acknowledged is True
    assert revised.status == "PENDING_CONFIRMATION"
    assert service.repository.get(str(first["id"]))["status"] == "PENDING_CONFIRMATION"
    with pytest.raises(NonRetryableExecutionError) as stale:
        service.handle_callback(
            connector_id="connector-1",
            corp_id="corp-1",
            out_track_id=str(first["id"]),
            user_id="staff-1",
            action="agree",
            revision=2,
            intent_token=token,
        )
    assert stale.value.error_code == "external_action_revision_mismatch"
    with pytest.raises(NonRetryableExecutionError) as denied:
        service.handle_callback(
            connector_id="connector-1",
            corp_id="corp-1",
            out_track_id=str(first["id"]),
            user_id="another-staff",
            action="agree",
            revision=1,
            intent_token=token,
        )
    assert denied.value.error_code == "external_action_actor_mismatch"

    accepted = service.handle_callback(
        connector_id="connector-1",
        corp_id="corp-1",
        out_track_id=str(first["id"]),
        user_id="staff-1",
        action="agree",
        revision=1,
        intent_token=token,
    )
    duplicate = service.handle_callback(
        connector_id="connector-1",
        corp_id="corp-1",
        out_track_id=str(first["id"]),
        user_id="staff-1",
        action="agree",
        revision=1,
        intent_token=token,
    )
    assert accepted.status == "APPROVED"
    assert accepted.duplicate is False
    assert duplicate.duplicate is True
    claimed = service.repository.claim_approved(worker_id="worker-1", lease_seconds=-1)
    assert claimed is not None and claimed["status"] == "EXECUTING"
    recovered = service.repository.recover_stale_execution()
    assert recovered is not None and recovered["status"] == "FAILED_UNCERTAIN"
    assert service.repository.claim_approved(worker_id="worker-2") is None

    rejected_arguments = normalize_todo_arguments({"subject": "取消的操作"}).as_dict()
    rejected, _ = service.prepare(
        facts=_facts(),
        arguments=rejected_arguments,
        arguments_hash=json_hash(rejected_arguments),
        safe_summary={"operation": "创建钉钉待办", "subject": "取消的操作", "due_time": ""},
        mcp_call_id="mcp-call-reject",
    )
    rejected_token = signer.issue(str(rejected["id"]), 1)
    result = service.handle_callback(
        connector_id="connector-1",
        corp_id="corp-1",
        out_track_id=str(rejected["id"]),
        user_id="staff-1",
        action="reject",
        revision=1,
        intent_token=rejected_token,
    )
    assert result.status == "REJECTED"
    with pytest.raises(NonRetryableExecutionError) as conflict:
        service.handle_callback(
            connector_id="connector-1",
            corp_id="corp-1",
            out_track_id=str(rejected["id"]),
            user_id="staff-1",
            action="agree",
            revision=1,
            intent_token=rejected_token,
        )
    assert conflict.value.error_code == "external_action_state_conflict"

    expired_arguments = normalize_todo_arguments({"subject": "过期的操作"}).as_dict()
    expired, _ = service.prepare(
        facts=_facts(),
        arguments=expired_arguments,
        arguments_hash=json_hash(expired_arguments),
        safe_summary={"operation": "创建钉钉待办", "subject": "过期的操作", "due_time": ""},
        mcp_call_id="mcp-call-expired",
    )
    database.execute(
        "update external_action_intent set expires_at = ? where id = ?",
        ("2000-01-01T00:00:00+00:00", expired["id"]),
    )
    expired_result = service.handle_callback(
        connector_id="connector-1",
        corp_id="corp-1",
        out_track_id=str(expired["id"]),
        user_id="staff-1",
        action="agree",
        revision=1,
        intent_token=signer.issue(str(expired["id"]), 1),
    )
    assert expired_result.status == "EXPIRED"
    assert service.repository.claim_approved(worker_id="worker-expired") is None


def test_worker_reauthorizes_current_actor_application_and_identity() -> None:
    database = _database()
    database.execute_script(
        """
        create table app_user (
          id text primary key, status text not null, account_type text not null
        );
        create table agent_job (
          id text primary key, internal_user_id text not null,
          business_application_id text not null, source_connector_id text not null
        );
        create table user_external_identity (
          id text primary key, user_id text not null, provider text not null,
          status text not null, dingtalk_enterprise_id text not null,
          external_subject_id text not null, union_id text not null
        );
        insert into app_user values ('user-1', 'enabled', 'human');
        insert into agent_job values ('job-1', 'user-1', 'application-1', 'connector-1');
        insert into user_external_identity values (
          'identity-1', 'user-1', 'dingtalk', 'enabled',
          'enterprise-1', 'staff-1', 'union-1'
        );
        """,
        ignore_existing_errors=False,
    )

    class _SnapshotService:
        def __init__(self) -> None:
            self.job_ids: list[str] = []

        def verify(self, job_id: str) -> None:
            self.job_ids.append(job_id)

    class _AuthorizationService:
        def __init__(self) -> None:
            self.requests: list[dict[str, str]] = []

        def require(self, **values: str) -> None:
            self.requests.append(values)

    snapshot_service = _SnapshotService()
    authorization_service = _AuthorizationService()
    runtime = SimpleNamespace(
        database=database,
        mcp_tool_snapshot_service=snapshot_service,
        business_authorization_service=authorization_service,
    )
    worker = ExternalActionWorker(runtime, worker_id="worker-1")
    worker_manifest = MCP_TOOL_MANIFEST[TOOL_IDENTIFIER]
    intent = {
        **_facts(),
        "schema_hash": worker_manifest.schema_hash,
    }

    worker._reauthorize(intent)
    assert snapshot_service.job_ids == ["job-1"]
    assert authorization_service.requests[0]["stage"] == "dingtalk_external_action_execute"

    database.execute("update app_user set status = 'disabled' where id = 'user-1'")
    with pytest.raises(ValueError, match="actor facts"):
        worker._reauthorize(intent)

    database.execute("update app_user set status = 'enabled' where id = 'user-1'")
    database.execute(
        "update agent_job set business_application_id = 'other-application' where id = 'job-1'"
    )
    with pytest.raises(ValueError, match="actor facts"):
        worker._reauthorize(intent)


def test_worker_create_card_matches_published_template_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class _Repository:
        completed: list[str] = []
        failed: list[str] = []

        @staticmethod
        def get(_intent_id: str) -> dict[str, Any]:
            return {
                "id": "action-1",
                "revision": 3,
                "target_external_subject_id": "staff-1",
                "safe_summary_json": "{}",
            }

        @staticmethod
        def decode_json(_value: str) -> dict[str, str]:
            return {"subject": "回访客户", "due_time": "未设置"}

        def complete_card(self, outbox_id: str) -> None:
            self.completed.append(outbox_id)

        def fail_card(self, outbox_id: str, **_values: str) -> None:
            self.failed.append(outbox_id)

    class _CardClient:
        def __init__(self, _token_client: Any) -> None:
            pass

        @staticmethod
        def create_confirmation(**values: Any) -> None:
            captured.update(values)

    monkeypatch.setattr(
        "services.dingtalk_mcp_server.worker.DingTalkAccessTokenClient",
        lambda **_values: object(),
    )
    monkeypatch.setattr(
        "services.dingtalk_mcp_server.worker.DingTalkCardClient", _CardClient
    )
    worker = ExternalActionWorker(SimpleNamespace(database=object()), worker_id="worker-1")
    repository = _Repository()
    worker.repository = repository  # type: ignore[assignment]
    monkeypatch.setattr(worker, "_connector_credentials", lambda _intent: ("id", "secret"))
    monkeypatch.setattr(worker, "_intent_token", lambda _intent_id, _revision: "signed")

    worker._dispatch_card(
        {"id": "card-outbox-1", "action_intent_id": "action-1", "event_kind": "CREATE"}
    )

    assert repository.completed == ["card-outbox-1"]
    assert repository.failed == []
    assert captured["card_fields"]["status"] == ""
    assert "intentToken" not in captured["card_fields"]
    assert captured["private_fields"] == {
        "revisionNo": "3",
        "intentToken": "signed",
        "supplement": "",
        "inputStatus": "normal",
        "errorText": "",
    }


def test_card_and_todo_clients_emit_only_fixed_bounded_provider_contracts() -> None:
    card_transport = _Transport()
    card = DingTalkCardClient(_TokenClient(), transport=card_transport)
    card.create_confirmation(
        out_track_id="action-1",
        staff_id="staff-1",
        card_fields={"subject": "回访客户", "status": ""},
        private_fields={
            "revisionNo": "1",
            "intentToken": "signed",
            "inputStatus": "normal",
        },
    )
    method, url, payload, headers, _timeout = card_transport.calls[0]
    assert method == "POST"
    assert url.endswith("/v1.0/card/instances/createAndDeliver")
    assert payload["cardTemplateId"] == "0ad7c643-7e30-4797-8284-da5ef89d3841.schema"
    assert payload["callbackType"] == "STREAM"
    assert payload["userId"] == "staff-1"
    assert payload["cardData"]["cardParamMap"]["status"] == ""
    assert payload["privateData"] == {
        "staff-1": {
            "cardParamMap": {
                "revisionNo": "1",
                "intentToken": "signed",
                "inputStatus": "normal",
            }
        }
    }
    assert payload["imRobotOpenSpaceModel"] == {"supportForward": False}
    assert payload["openSpaceId"] == "dtv1.card//IM_ROBOT.staff-1"
    assert headers == {"x-acs-dingtalk-access-token": "test-access-token"}

    todo_transport = _Transport({"id": "todo-1"})
    todo = DingTalkTodoClient(_TokenClient(), transport=todo_transport)
    result = todo.create_for_self(
        union_id="union/id",
        arguments={"subject": "回访客户", "description": "确认范围", "due_time_ms": 1},
    )
    _method, todo_url, todo_payload, _headers, _timeout = todo_transport.calls[0]
    assert todo_url.endswith("/v1.0/todo/users/union%2Fid/tasks")
    assert todo_payload == {
        "subject": "回访客户",
        "description": "确认范围",
        "executorIds": ["union/id"],
        "participantIds": ["union/id"],
        "dueTime": 1,
    }
    assert result == {"task_id": "todo-1", "created": True}
