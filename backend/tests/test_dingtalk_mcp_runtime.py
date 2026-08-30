from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from urllib.error import HTTPError

import pytest

from app.modules.external_action.domain import json_hash, normalize_todo_arguments
from app.modules.external_action.repository import ExternalActionRepository
from app.modules.external_action.service import ExternalActionService, ExternalActionTokenSigner
from app.modules.mcp_tool_runtime.manifest import MCP_TOOL_MANIFEST
from app.python_runtime.tool_policy import contains_forbidden_tool_input
from app.shared.database import Database
from app.shared.dingtalk_tool_contracts import DINGTALK_TOOL_CONTRACTS
from app.shared.exceptions import NonRetryableExecutionError, RetryableExecutionError
from services.dingtalk_mcp_server.contracts import TOOL_IDENTIFIER
from services.dingtalk_mcp_server.auth.principal import (
    DingTalkPrincipalResolver,
    ResolvedDingTalkPrincipal,
)
from services.dingtalk_mcp_server.provider import (
    DingTalkAiTableMutationClient,
    DingTalkAiTableReadClient,
    DingTalkCalendarMutationClient,
    DingTalkCalendarReadClient,
    DingTalkCardClient,
    DingTalkContactsClient,
    DingTalkDepartmentClient,
    DingTalkRobotMutationClient,
    DingTalkTodoClient,
    DingTalkTodoReadClient,
    DingTalkWorkNotificationReadClient,
    DingTalkWorkNotificationMutationClient,
    UrllibDingTalkJsonTransport,
)
from services.dingtalk_mcp_server.tools.read_tool import _safe_payload_summary, _validated_payload
from services.dingtalk_mcp_server.tools.mutation_tool import DingTalkMutationToolService
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


def test_fixed_read_provider_clients_use_the_18_allowlisted_endpoints() -> None:
    transport = _Transport()
    token = _TokenClient()

    contacts = DingTalkContactsClient(token, transport=transport)
    contacts.search_users(query="张三", offset=0, page_size=20, exact_match=False)
    contacts.get_user(user_id="staff-1", language="zh_CN")
    contacts.list_department_users(department_id=1)

    departments = DingTalkDepartmentClient(token, transport=transport)
    departments.search(query="研发", offset=0, page_size=20)
    departments.get(department_id=1, language="zh_CN")
    departments.list_sub_departments(parent_department_id=1, language="zh_CN")

    DingTalkTodoReadClient(token, transport=transport).list_for_self(
        union_id="union-1",
        cursor="",
        is_done=False,
        role_types=["executor"],
    )

    calendar = DingTalkCalendarReadClient(token, transport=transport)
    calendar.get_event(union_id="union-1", event_id="event-1", max_attendees=20)
    calendar.list_events(
        union_id="union-1",
        time_min="2026-08-30T00:00:00+08:00",
        time_max="2026-08-31T00:00:00+08:00",
        page_size=20,
        cursor="",
        max_attendees=20,
    )
    calendar.list_attendees(
        union_id="union-1",
        event_id="event-1",
        page_size=20,
        cursor="cursor-1",
    )

    aitable = DingTalkAiTableReadClient(token, transport=transport)
    aitable.search(operator_id="union-1", query="项目", page_size=20, cursor="")
    aitable.list_sheets(operator_id="union-1", base_id="base-1")
    aitable.get_sheet(operator_id="union-1", base_id="base-1", sheet_id="sheet-1")
    aitable.list_fields(operator_id="union-1", base_id="base-1", sheet_id="sheet-1")
    aitable.list_records(
        operator_id="union-1",
        base_id="base-1",
        sheet_id="sheet-1",
        page_size=100,
        cursor="",
    )
    aitable.get_record(
        operator_id="union-1",
        base_id="base-1",
        sheet_id="sheet-1",
        record_id="record-1",
    )

    notice = DingTalkWorkNotificationReadClient(token, transport=transport)
    notice.get_progress(agent_id=123, task_id=456)
    notice.get_result(agent_id=123, task_id=456)

    assert len(transport.calls) == 18
    assert [(method, url) for method, url, *_ in transport.calls] == [
        ("POST", "https://api.dingtalk.com/v1.0/contact/users/search"),
        ("POST", "https://oapi.dingtalk.com/topapi/v2/user/get"),
        ("POST", "https://oapi.dingtalk.com/topapi/user/listid"),
        ("POST", "https://api.dingtalk.com/v1.0/contact/departments/search"),
        ("POST", "https://oapi.dingtalk.com/topapi/v2/department/get"),
        ("POST", "https://oapi.dingtalk.com/topapi/v2/department/listsub"),
        ("POST", "https://api.dingtalk.com/v1.0/todo/users/union-1/org/tasks/query"),
        (
            "GET",
            "https://api.dingtalk.com/v1.0/calendar/users/union-1/calendars/primary/events/event-1?maxAttendees=20",
        ),
        (
            "GET",
            "https://api.dingtalk.com/v1.0/calendar/users/union-1/calendars/primary/eventsview?timeMin=2026-08-30T00%3A00%3A00%2B08%3A00&timeMax=2026-08-31T00%3A00%3A00%2B08%3A00&maxResults=20&maxAttendees=20",
        ),
        (
            "GET",
            "https://api.dingtalk.com/v1.0/calendar/users/union-1/calendars/primary/events/event-1/attendees?maxResults=20&nextToken=cursor-1",
        ),
        ("POST", "https://api.dingtalk.com/v2.0/storage/dentries/search?operatorId=union-1"),
        ("GET", "https://api.dingtalk.com/v1.0/notable/bases/base-1/sheets?operatorId=union-1"),
        (
            "GET",
            "https://api.dingtalk.com/v1.0/notable/bases/base-1/sheets/sheet-1?operatorId=union-1",
        ),
        (
            "GET",
            "https://api.dingtalk.com/v1.0/notable/bases/base-1/sheets/sheet-1/fields?operatorId=union-1",
        ),
        (
            "POST",
            "https://api.dingtalk.com/v1.0/notable/bases/base-1/sheets/sheet-1/records/list?operatorId=union-1",
        ),
        (
            "GET",
            "https://api.dingtalk.com/v1.0/notable/bases/base-1/sheets/sheet-1/records/record-1?operatorId=union-1",
        ),
        ("POST", "https://oapi.dingtalk.com/topapi/message/corpconversation/getsendprogress"),
        ("POST", "https://oapi.dingtalk.com/topapi/message/corpconversation/getsendresult"),
    ]
    assert all(
        call[3] == {"x-acs-dingtalk-access-token": "test-access-token"} for call in transport.calls
    )
    assert transport.calls[0][2] == {
        "queryWord": "张三",
        "offset": 0,
        "size": 20,
    }
    assert transport.calls[6][2] == {
        "nextToken": "0",
        "isDone": False,
        "roleTypes": [["executor"]],
    }
    assert transport.calls[10][2] == {
        "keyword": "项目",
        "option": {
            "dentryCategories": ["alidoc"],
            "creatorIds": [],
            "nextToken": "",
            "maxResults": 20,
        },
    }
    assert transport.calls[-1][2] == {"agent_id": 123, "task_id": 456}


def test_contact_projection_and_audit_summary_remove_sensitive_values() -> None:
    transport = _Transport(
        {
            "result": {
                "list": [
                    {
                        "userid": "staff-1",
                        "unionid": "union-1",
                        "name": "张三",
                        "title": "工程师",
                        "mobile": "13800000000",
                        "email": "private@example.invalid",
                        "homeAddress": "secret",
                    }
                ],
                "nextToken": "cursor-2",
            }
        }
    )
    result = DingTalkContactsClient(_TokenClient(), transport=transport).search_users(
        query="张三",
        offset=0,
        page_size=20,
        exact_match=True,
    )
    assert result == {
        "users": [
            {
                "user_id": "staff-1",
                "union_id": "union-1",
                "name": "张三",
                "title": "工程师",
                "department_ids": [],
            }
        ],
        "returned": 1,
        "truncated": True,
        "untrusted_data": True,
        "next_cursor": "cursor-2",
    }
    assert transport.calls[0][2]["fullMatchField"] == 1
    encoded = str(result)
    assert "13800000000" not in encoded
    assert "private@example.invalid" not in encoded
    assert "homeAddress" not in encoded

    summary = _safe_payload_summary({"query": "张三", "records": [{"secret": "value"}]})
    assert summary["field_names"] == ["query", "records"]
    assert summary["list_counts"] == {"records": 1}
    assert "张三" not in str(summary)
    assert "value" not in str(summary)


def test_read_schema_rejects_identity_and_network_overrides_before_provider_io() -> None:
    schema = MCP_TOOL_MANIFEST["dingtalk_list_todos"].input_schema
    with pytest.raises(NonRetryableExecutionError) as identity:
        _validated_payload({"union_id": "forged"}, schema, kind="request")
    assert identity.value.error_code == "dingtalk_request_invalid"

    search_schema = MCP_TOOL_MANIFEST["dingtalk_search_users"].input_schema
    with pytest.raises(NonRetryableExecutionError) as network:
        _validated_payload(
            {"query": "张三", "url": "https://attacker.invalid"},
            search_schema,
            kind="request",
        )
    assert network.value.error_code == "dingtalk_request_invalid"


@pytest.mark.parametrize(
    ("status", "error_type", "error_code"),
    [
        (403, NonRetryableExecutionError, "dingtalk_permission_denied"),
        (429, RetryableExecutionError, "dingtalk_rate_limited"),
        (503, RetryableExecutionError, "dingtalk_http_503"),
    ],
)
def test_provider_http_errors_have_stable_safe_classification(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    error_type: type[Exception],
    error_code: str,
) -> None:
    def _raise(*_args: Any, **_kwargs: Any) -> None:
        raise HTTPError(
            "https://api.dingtalk.com/fixed",
            status,
            "provider body must not escape",
            None,
            None,
        )

    monkeypatch.setattr("services.dingtalk_mcp_server.provider.urlopen", _raise)
    with pytest.raises(error_type) as caught:
        UrllibDingTalkJsonTransport().request_json(
            "GET",
            "https://api.dingtalk.com/fixed",
            {},
            {"x-acs-dingtalk-access-token": "token-secret"},
            5,
        )
    assert getattr(caught.value, "error_code") == error_code
    assert "provider body" not in str(getattr(caught.value, "safe_message", ""))
    assert "token-secret" not in str(caught.value)


def test_todo_subject_is_business_input_not_a_principal_override() -> None:
    assert contains_forbidden_tool_input({"subject": "回访客户"}) is False
    assert contains_forbidden_tool_input({"sub": "forged-principal"}) is True
    assert contains_forbidden_tool_input({"actor_id": "forged-actor"}) is True
    assert contains_forbidden_tool_input({"user_id": "forged-user"}) is True


def test_principal_resolver_uses_invoked_contract_and_server_owned_targets() -> None:
    contract = DINGTALK_TOOL_CONTRACTS["dingtalk_send_work_notification"]
    definition = MCP_TOOL_MANIFEST[contract.identifier]

    class _PrincipalDatabase:
        @staticmethod
        def execute_one(sql: str, _params: tuple[Any, ...]) -> dict[str, Any] | None:
            if "from agent_job j" in sql:
                return {
                    "id": "job-1",
                    "session_id": "session-1",
                    "internal_user_id": "user-1",
                    "business_application_id": "application-1",
                    "agent_publication_id": "agent-publication-1",
                    "business_application_publication_id": "application-publication-1",
                    "application_publication_id": "application-publication-1",
                    "source_connector_id": "connector-1",
                    "session_source_connector_id": "connector-1",
                    "external_conversation_id": "conversation-1",
                    "conversation_type": "group",
                    "bot_identity": "",
                    "reply_route_json": (
                        '{"connector_id":"connector-1","target":'
                        '{"open_conversation_id":"open-1","robot_code":"robot-1"}}'
                    ),
                    "user_status": "enabled",
                    "user_account_type": "human",
                }
            if "from integration_connector c" in sql:
                return {
                    "id": "connector-1",
                    "connector_type": "dingtalk_enterprise_stream",
                    "enabled": 1,
                    "allow_ingress": 1,
                    "dingtalk_enterprise_id": "enterprise-1",
                    "enterprise_status": "ACTIVE",
                    "corp_id": "corp-1",
                    "metadata": '{"work_notification_agent_id":123456}',
                }
            if "select retry_count" in sql:
                return {"retry_count": 0}
            return None

        @staticmethod
        def execute(sql: str, _params: tuple[Any, ...]) -> list[dict[str, Any]]:
            assert "from user_external_identity" in sql
            return [
                {
                    "id": "identity-1",
                    "external_subject_id": "staff-1",
                    "union_id": "union-1",
                }
            ]

    class _Verifier:
        def __init__(self) -> None:
            self.scope = ""

        def verify_for_running_job(
            self, _token: str, _database: Any, _snapshot: Any, *, required_scope: str
        ) -> dict[str, Any]:
            self.scope = required_scope
            return {"job_id": "job-1"}

    class _Snapshot:
        @staticmethod
        def verify(_job_id: str) -> dict[str, Any]:
            return {
                "authorization_hash": "authorization-hash",
                "snapshot": {
                    "tools": [
                        {
                            "server_code": "dingtalk-mcp",
                            "tool_identifier": contract.identifier,
                            "effect": contract.effect,
                            "confirmation_policy": contract.confirmation_policy,
                            "schema_hash": definition.schema_hash,
                        }
                    ]
                },
            }

    class _Authorization:
        def __init__(self) -> None:
            self.values: list[dict[str, Any]] = []

        def require(self, **values: Any) -> dict[str, Any]:
            self.values.append(values)
            return values

    verifier = _Verifier()
    authorization = _Authorization()
    resolver = DingTalkPrincipalResolver(
        _PrincipalDatabase(),  # type: ignore[arg-type]
        verifier,  # type: ignore[arg-type]
        _Snapshot(),  # type: ignore[arg-type]
        authorization,
    )
    resolver.authenticate("principal-jwt", contract)
    assert verifier.scope == contract.required_scope
    principal = resolver.resolve(
        {
            "job_id": "job-1",
            "sub": "user-1",
            "session_id": "session-1",
            "agent_publication_id": "agent-publication-1",
            "application_publication_id": "application-publication-1",
            "authorization_hash": "authorization-hash",
            "jti": "jti-1",
        },
        contract,
    )
    assert principal.target_external_subject_id == "staff-1"
    assert principal.target_union_id == "union-1"
    assert principal.primary_calendar_id == "primary"
    assert principal.aitable_operator_id == "union-1"
    assert principal.source_open_conversation_id == "open-1"
    assert principal.source_robot_code == "robot-1"
    assert principal.work_notification_agent_id == 123456
    assert authorization.values[-1]["tool_identifier"] == contract.identifier


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
    assert (
        database.execute_one("select count(*) as count from external_action_card_outbox")["count"]
        == 1
    )

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

        def verify(self, job_id: str) -> dict[str, Any]:
            self.job_ids.append(job_id)
            definition = MCP_TOOL_MANIFEST[TOOL_IDENTIFIER]
            return {
                "snapshot": {
                    "tools": [
                        {
                            "server_code": definition.server_code,
                            "tool_identifier": definition.identifier,
                            "schema_hash": definition.schema_hash,
                        }
                    ]
                }
            }

    class _AuthorizationService:
        def __init__(self) -> None:
            self.requests: list[dict[str, str]] = []
            self.denied = False

        def require(self, **values: str) -> None:
            self.requests.append(values)
            if self.denied:
                raise NonRetryableExecutionError(
                    "grant revoked",
                    safe_message="工具授权已撤销",
                    error_code="business_tool_not_authorized",
                )

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

    database.execute(
        "update agent_job set business_application_id = 'application-1' where id = 'job-1'"
    )
    with pytest.raises(ValueError, match="manifest facts"):
        worker._reauthorize({**intent, "operation_code": "dingtalk.todo.update"})

    database.execute(
        "update user_external_identity set union_id = 'union-rebound' where id = 'identity-1'"
    )
    with pytest.raises(ValueError, match="identity"):
        worker._reauthorize(intent)

    database.execute(
        "update user_external_identity set union_id = 'union-1' where id = 'identity-1'"
    )
    authorization_service.denied = True
    with pytest.raises(NonRetryableExecutionError) as revoked:
        worker._reauthorize(intent)
    assert revoked.value.error_code == "business_tool_not_authorized"


@pytest.mark.parametrize(
    ("failure", "uncertain", "audit_status"),
    [
        (
            NonRetryableExecutionError(
                "provider rejected",
                safe_message="操作被钉钉拒绝",
                error_code="dingtalk_provider_rejected",
            ),
            False,
            "FAILED",
        ),
        (
            RetryableExecutionError(
                "provider result unknown",
                safe_message="钉钉接口暂时不可用",
                error_code="dingtalk_transport_failed",
            ),
            True,
            "FAILED_UNCERTAIN",
        ),
    ],
)
def test_worker_classifies_provider_failure_without_automatic_replay(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    uncertain: bool,
    audit_status: str,
) -> None:
    class _Repository:
        def __init__(self) -> None:
            self.failed: list[dict[str, Any]] = []

        @staticmethod
        def decode_json(_value: str) -> dict[str, Any]:
            return {"subject": "测试"}

        def fail_execution(self, intent_id: str, **values: Any) -> None:
            self.failed.append({"intent_id": intent_id, **values})

    audit = _Audit()
    runtime = SimpleNamespace(database=object(), audit_service=audit)
    worker = ExternalActionWorker(runtime, worker_id="worker-1")
    repository = _Repository()
    worker.repository = repository  # type: ignore[assignment]
    contract = DINGTALK_TOOL_CONTRACTS["dingtalk_create_todo"]
    monkeypatch.setattr(worker, "_reauthorize", lambda _intent: contract)
    monkeypatch.setattr(worker, "_connector_credentials", lambda _intent: ("id", "secret"))
    monkeypatch.setattr(
        "services.dingtalk_mcp_server.worker.DingTalkAccessTokenClient",
        lambda **_values: object(),
    )
    attempts: list[str] = []

    def _fail(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        attempts.append("called")
        raise failure

    worker._dispatchers[contract.operation_code] = _fail
    worker._execute(
        {
            "id": "action-1",
            "job_id": "job-1",
            "actor_user_id": "user-1",
            "operation_code": contract.operation_code,
            "arguments_json": "{}",
        }
    )
    assert attempts == ["called"]
    assert repository.failed == [
        {
            "intent_id": "action-1",
            "error_code": getattr(failure, "error_code"),
            "error_summary": getattr(failure, "safe_message"),
            "uncertain": uncertain,
        }
    ]
    assert audit.events[-1][1]["status"] == audit_status


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
                "operation_code": "dingtalk.todo.create",
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
    monkeypatch.setattr("services.dingtalk_mcp_server.worker.DingTalkCardClient", _CardClient)
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


def test_fixed_mutation_clients_use_the_nine_allowlisted_operations() -> None:
    transport = _Transport({"id": "resource-1", "task_id": 321})
    token = _TokenClient()
    todo = DingTalkTodoClient(token, transport=transport)
    todo.create_for_self(union_id="union/1", arguments={"subject": "创建"})
    todo.update_for_self(
        union_id="union/1",
        arguments={"task_id": "todo/1", "subject": "更新", "due_time_ms": 1},
    )
    todo.complete_for_self(
        union_id="union/1",
        arguments={"task_id": "todo/1", "subject": "完成"},
    )
    calendar = DingTalkCalendarMutationClient(token, transport=transport)
    calendar.create_for_self(
        union_id="union/1",
        arguments={
            "title": "会议",
            "start_time": "2026-08-30T10:00:00+08:00",
            "end_time": "2026-08-30T11:00:00+08:00",
            "time_zone": "Asia/Shanghai",
        },
    )
    calendar.update_for_self(
        union_id="union/1",
        arguments={"event_id": "event/1", "title": "新标题"},
    )
    aitable = DingTalkAiTableMutationClient(token, transport=transport)
    aitable.insert_records(
        operator_id="union/1",
        arguments={
            "base_id": "base/1",
            "sheet_id": "sheet/1",
            "records": [{"fields": {"名称": "记录"}}],
        },
    )
    aitable.update_records(
        operator_id="union/1",
        arguments={
            "base_id": "base/1",
            "sheet_id": "sheet/1",
            "records": [{"record_id": "record/1", "fields": {"名称": "更新"}}],
        },
    )
    DingTalkRobotMutationClient(token, transport=transport).send_current(
        arguments={
            "title": "标题",
            "text": "正文",
            "_target": {
                "conversation_type": "group",
                "open_conversation_id": "cid/1",
                "robot_code": "robot-1",
            },
        }
    )
    DingTalkWorkNotificationMutationClient(token, transport=transport).send_to_self(
        arguments={
            "title": "标题",
            "text": "正文",
            "_target": {"agent_id": 123, "staff_id": "staff-1"},
        }
    )

    assert [(method, url) for method, url, *_ in transport.calls] == [
        ("POST", "https://api.dingtalk.com/v1.0/todo/users/union%2F1/tasks"),
        (
            "PUT",
            "https://api.dingtalk.com/v1.0/todo/users/union%2F1/tasks/todo%2F1",
        ),
        (
            "PUT",
            "https://api.dingtalk.com/v1.0/todo/users/union%2F1/tasks/todo%2F1",
        ),
        (
            "POST",
            "https://api.dingtalk.com/v1.0/calendar/users/union%2F1/calendars/primary/events",
        ),
        (
            "PUT",
            "https://api.dingtalk.com/v1.0/calendar/users/union%2F1/calendars/primary/events/event%2F1",
        ),
        (
            "POST",
            "https://api.dingtalk.com/v1.0/notable/bases/base%2F1/sheets/sheet%2F1/records?operatorId=union%2F1",
        ),
        (
            "PUT",
            "https://api.dingtalk.com/v1.0/notable/bases/base%2F1/sheets/sheet%2F1/records?operatorId=union%2F1",
        ),
        ("POST", "https://api.dingtalk.com/v1.0/robot/groupMessages/send"),
        (
            "POST",
            "https://oapi.dingtalk.com/topapi/message/corpconversation/asyncsend_v2",
        ),
    ]
    assert all(
        call[3] == {"x-acs-dingtalk-access-token": "test-access-token"} for call in transport.calls
    )
    assert transport.calls[7][2] == {
        "robotCode": "robot-1",
        "msgKey": "sampleMarkdown",
        "msgParam": {"title": "标题", "text": "正文"},
        "openConversationId": "cid/1",
    }
    assert transport.calls[8][2] == {
        "agent_id": 123,
        "userid_list": "staff-1",
        "to_all_user": False,
        "msg": {
            "msgtype": "markdown",
            "markdown": {"title": "标题", "text": "正文"},
        },
    }


@pytest.mark.parametrize(
    ("operation_code", "summary", "target"),
    [
        (
            "dingtalk.todo.create",
            {"operation": "创建钉钉待办", "subject": "回访", "due_time": "未设置"},
            "当前用户本人",
        ),
        (
            "dingtalk.calendar.event.create",
            {
                "operation": "创建钉钉日程",
                "title": "评审",
                "start_time": "10:00",
                "end_time": "11:00",
                "time_zone": "Asia/Shanghai",
            },
            "当前用户主日历",
        ),
        (
            "dingtalk.aitable.record.update",
            {
                "operation": "更新钉钉 AI 表格记录",
                "base_id": "base-1",
                "sheet_id": "sheet-1",
                "record_count": 1,
                "field_names": ["状态"],
            },
            "当前用户可访问的 AI 表格",
        ),
        (
            "dingtalk.robot.message.send",
            {
                "operation": "发送钉钉机器人消息",
                "target": "当前群聊",
                "title": "结果",
                "text": "已完成",
            },
            "当前群聊",
        ),
    ],
)
def test_confirmation_card_fields_are_operation_specific_and_bounded(
    operation_code: str,
    summary: dict[str, Any],
    target: str,
) -> None:
    fields = ExternalActionWorker._confirmation_card_fields(
        {"operation_code": operation_code}, summary
    )
    assert fields["operationName"] == summary["operation"]
    assert fields["targetName"] == target
    assert 1 <= len(fields["detailText"]) <= 4000


def test_mutation_mcp_audit_excludes_message_values_and_target_secrets() -> None:
    principal = ResolvedDingTalkPrincipal(
        job_id="job-1",
        session_id="session-1",
        actor_user_id="user-1",
        business_application_id="application-1",
        agent_publication_id="agent-publication-1",
        application_publication_id="application-publication-1",
        source_connector_id="connector-1",
        dingtalk_enterprise_id="enterprise-1",
        external_identity_id="identity-1",
        target_external_subject_id="staff-secret",
        target_union_id="union-secret",
        primary_calendar_id="primary",
        aitable_operator_id="union-secret",
        source_conversation_type="group",
        source_conversation_id="conversation-secret",
        source_open_conversation_id="open-conversation-secret",
        source_robot_code="robot-secret",
        work_notification_agent_id=123456,
        principal_jti="jti-secret",
    )

    class _Resolver:
        @staticmethod
        def audit_context(*_args: Any, **_kwargs: Any) -> object:
            return object()

        @staticmethod
        def resolve(*_args: Any, **_kwargs: Any) -> ResolvedDingTalkPrincipal:
            return principal

    class _McpAudit:
        def __init__(self) -> None:
            self.values: list[Any] = []

        def begin(self, context: object, **values: Any) -> Any:
            self.values.append((context, values))
            return SimpleNamespace(mcp_call_id="mcp-call-1")

        def append_event(self, _handle: Any, **values: Any) -> None:
            self.values.append(values)

        def complete(self, _handle: Any, **values: Any) -> None:
            self.values.append(values)

    class _Actions:
        @staticmethod
        def prepare(**_values: Any) -> tuple[dict[str, Any], bool]:
            return {
                "id": "action-1",
                "revision": 1,
                "expires_at": "2026-08-30T12:00:00+00:00",
            }, True

    audit = _McpAudit()
    tool_contract = DINGTALK_TOOL_CONTRACTS["dingtalk_send_robot_message"]

    def _normalize(
        _principal: ResolvedDingTalkPrincipal,
        values: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return {
            **values,
            "_target": {
                "open_conversation_id": "open-conversation-secret",
                "robot_code": "robot-secret",
            },
        }, {
            "operation": "发送钉钉机器人消息",
            "target": "当前群聊",
            "title": values["title"],
            "text": values["text"],
        }

    service = DingTalkMutationToolService(
        tool_contract,
        _Resolver(),  # type: ignore[arg-type]
        _Actions(),  # type: ignore[arg-type]
        audit,  # type: ignore[arg-type]
        _normalize,
    )
    service.invoke(
        claims={},
        arguments={"title": "机密标题", "text": "正文绝密 private@example.invalid"},
        correlation_id="correlation-1",
        invocation_id="job-1.attempt-0",
    )
    encoded_audit = str(audit.values)
    for forbidden in (
        "机密标题",
        "正文绝密",
        "private@example.invalid",
        "open-conversation-secret",
        "robot-secret",
        "staff-secret",
        "union-secret",
        "jti-secret",
    ):
        assert forbidden not in encoded_audit
