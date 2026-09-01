from __future__ import annotations

import io
import json
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
from app.shared.dingtalk_tool_contracts import (
    DINGTALK_BATCH_SEND_MESSAGE_TO_USERS_TOOL_IDENTIFIER,
    DINGTALK_SEND_MESSAGE_TO_GROUP_TOOL_IDENTIFIER,
    DINGTALK_TOOL_CONTRACTS,
)
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
    LEGACY_ALLOWED_PATHS,
    UrllibDingTalkJsonTransport,
)
from services.dingtalk_mcp_server.tools.mutation_catalog import (
    DingTalkMutationPreparationCatalog,
)
from services.dingtalk_mcp_server.tools.mutation_tool import DingTalkMutationToolService
from services.dingtalk_mcp_server.tools.read_catalog import DingTalkReadExecutorCatalog
from services.dingtalk_mcp_server.tools.read_tool import _safe_payload_summary, _validated_payload
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


class _SequenceTransport(_Transport):
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        super().__init__()
        self.responses = list(responses)

    def request_json(
        self,
        method: str,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        timeout_seconds: int,
    ) -> dict[str, Any]:
        self.calls.append((method, url, payload, headers, timeout_seconds))
        return self.responses.pop(0)


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
    transport.response = {"list": [], "hasMore": False, "totalCount": 0}
    contacts.search_users(query="张三", offset=0, page_size=20, exact_match=False)
    transport.response = {
        "userList": [{"userid": "staff-1", "unionid": "union-1", "name": "张三"}],
        "unauthorizedUserIdList": [],
    }
    contacts.get_user(user_id="staff-1", language="zh_CN")
    transport.response = {"result": {"userid_list": []}}
    contacts.list_department_users(department_id=1)

    departments = DingTalkDepartmentClient(token, transport=transport)
    transport.response = {"list": [2], "hasMore": False, "totalCount": 1}
    assert departments.search(query="研发", offset=0, page_size=20)["departments"] == [
        {"department_id": 2}
    ]
    transport.response = {"result": {"dept_id": 1, "name": "研发"}}
    departments.get(department_id=1, language="zh_CN")
    transport.response = {"result": []}
    departments.list_sub_departments(parent_department_id=1, language="zh_CN")

    transport.response = {"todoCards": [], "nextToken": ""}
    DingTalkTodoReadClient(token, transport=transport).list_for_self(
        union_id="union-1",
        cursor="",
        is_done=False,
        role_types=["executor"],
    )

    calendar = DingTalkCalendarReadClient(token, transport=transport)
    transport.response = {
        "id": "event-1",
        "summary": "会议",
        "start": {"dateTime": "2026-08-30T10:00:00+08:00"},
        "end": {"dateTime": "2026-08-30T11:00:00+08:00"},
    }
    calendar.get_event(union_id="union-1", event_id="event-1", max_attendees=20)
    transport.response = {"events": [], "nextToken": ""}
    calendar.list_events(
        union_id="union-1",
        time_min="2026-08-30T00:00:00+08:00",
        time_max="2026-08-31T00:00:00+08:00",
        page_size=20,
        cursor="",
        max_attendees=20,
    )
    transport.response = {"attendees": [], "nextToken": ""}
    calendar.list_attendees(
        union_id="union-1",
        event_id="event-1",
        page_size=20,
        cursor="cursor-1",
    )

    aitable = DingTalkAiTableReadClient(token, transport=transport)
    transport.response = {"items": [], "nextToken": ""}
    aitable.search(operator_id="union-1", query="项目", page_size=20, cursor="")
    transport.response = {"value": []}
    aitable.list_sheets(operator_id="union-1", base_id="base-1")
    transport.response = {"id": "sheet-1", "name": "数据表"}
    aitable.get_sheet(operator_id="union-1", base_id="base-1", sheet_id="sheet-1")
    transport.response = {"value": []}
    aitable.list_fields(operator_id="union-1", base_id="base-1", sheet_id="sheet-1")
    transport.response = {"records": [], "hasMore": False, "nextToken": ""}
    aitable.list_records(
        operator_id="union-1",
        base_id="base-1",
        sheet_id="sheet-1",
        page_size=100,
        cursor="",
    )
    transport.response = {"id": "record-1", "fields": {"名称": "记录"}}
    aitable.get_record(
        operator_id="union-1",
        base_id="base-1",
        sheet_id="sheet-1",
        record_id="record-1",
    )

    notice = DingTalkWorkNotificationReadClient(token, transport=transport)
    transport.response = {"progress": {"progress_in_percent": 100, "status": 2}}
    notice.get_progress(agent_id=123, task_id=456)
    transport.response = {
        "send_result": {
            "invalid_user_id_list": [],
            "forbidden_user_id_list": [],
            "failed_user_id_list": [],
            "read_user_id_list": ["staff-1"],
            "unread_user_id_list": [],
            "invalid_dept_id_list": [],
        }
    }
    notice.get_result(agent_id=123, task_id=456)

    assert len(transport.calls) == 18
    assert [(method, url) for method, url, *_ in transport.calls] == [
        ("POST", "https://api.dingtalk.com/v1.0/contact/users/search"),
        (
            "GET",
            (
                "https://api.dingtalk.com/v1.0/contact/users/batch/get?"
                "userIdList=%5B%22staff-1%22%5D"
            ),
        ),
        (
            "POST",
            "https://oapi.dingtalk.com/topapi/user/listid?access_token=test-access-token",
        ),
        ("POST", "https://api.dingtalk.com/v1.0/contact/departments/search"),
        (
            "POST",
            "https://oapi.dingtalk.com/topapi/v2/department/get?access_token=test-access-token",
        ),
        (
            "POST",
            "https://oapi.dingtalk.com/topapi/v2/department/listsub?access_token=test-access-token",
        ),
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
        (
            "GET",
            "https://api.dingtalk.com/v1.0/notable/bases/base-1/sheets?operatorId=union-1",
        ),
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
        (
            "POST",
            "https://oapi.dingtalk.com/topapi/message/corpconversation/getsendprogress?access_token=test-access-token",
        ),
        (
            "POST",
            "https://oapi.dingtalk.com/topapi/message/corpconversation/getsendresult?access_token=test-access-token",
        ),
    ]
    for _method, url, _payload, headers, _timeout in transport.calls:
        if url.startswith("https://oapi.dingtalk.com/"):
            assert headers == {}
            assert "access_token=test-access-token" in url
        else:
            assert headers == {"x-acs-dingtalk-access-token": "test-access-token"}
            assert "access_token=" not in url
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


def test_legacy_provider_paths_are_closed_to_officially_unreplaced_operations() -> None:
    assert LEGACY_ALLOWED_PATHS == {
        "/topapi/user/listid",
        "/topapi/v2/department/get",
        "/topapi/v2/department/listsub",
        "/topapi/message/corpconversation/asyncsend_v2",
        "/topapi/message/corpconversation/getsendprogress",
        "/topapi/message/corpconversation/getsendresult",
    }

    client = DingTalkContactsClient(_TokenClient(), transport=_Transport())
    with pytest.raises(ValueError, match="legacy operation is not allowlisted"):
        client._request("POST", "/topapi/unknown", legacy=True)
    with pytest.raises(ValueError, match="legacy operation is not allowlisted"):
        client._request("POST", "/topapi/v2/user/get", legacy=True)


def test_contact_projection_and_audit_summary_remove_sensitive_values() -> None:
    transport = _Transport(
        {
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


def test_contact_search_projects_string_user_ids_and_provider_pagination_facts() -> None:
    transport = _Transport(
        {
            "list": ["staff-1", "staff-2"],
            "hasMore": False,
            "totalCount": 2,
        }
    )
    result = DingTalkContactsClient(_TokenClient(), transport=transport).search_users(
        query="庄慕焕",
        offset=0,
        page_size=20,
        exact_match=False,
    )

    assert result == {
        "users": [{"user_id": "staff-1"}, {"user_id": "staff-2"}],
        "returned": 2,
        "truncated": False,
        "untrusted_data": True,
    }
    assert transport.calls[0][2] == {"queryWord": "庄慕焕", "offset": 0, "size": 20}

    transport.response = {
        "list": ["staff-3"],
        "hasMore": False,
        "totalCount": 4,
    }
    next_page = DingTalkContactsClient(_TokenClient(), transport=transport).search_users(
        query="庄慕焕",
        offset=2,
        page_size=1,
        exact_match=False,
    )
    assert next_page["users"] == [{"user_id": "staff-3"}]
    assert next_page["returned"] == 1
    assert next_page["truncated"] is True

    transport.response = {
        "list": ["staff-4"],
        "hasMore": True,
        "totalCount": 1,
    }
    has_more_page = DingTalkContactsClient(_TokenClient(), transport=transport).search_users(
        query="庄慕焕",
        offset=0,
        page_size=20,
        exact_match=False,
    )
    assert has_more_page["truncated"] is True


def test_get_user_uses_latest_batch_endpoint_and_projects_safe_identity_fields() -> None:
    transport = _Transport(
        {
            "userList": [
                {
                    "userid": "staff-1",
                    "unionid": "union-1",
                    "name": "张三",
                    "job_number": "A-001",
                    "mobile": "13800000000",
                    "avatar": "https://example.invalid/private-avatar",
                }
            ],
            "unauthorizedUserIdList": [],
        }
    )

    result = DingTalkContactsClient(_TokenClient(), transport=transport).get_user(
        user_id="staff-1",
        language="zh_CN",
    )

    assert result == {
        "user": {
            "user_id": "staff-1",
            "union_id": "union-1",
            "name": "张三",
            "job_number": "A-001",
        },
        "untrusted_data": True,
    }
    assert transport.calls == [
        (
            "GET",
            (
                "https://api.dingtalk.com/v1.0/contact/users/batch/get?"
                "userIdList=%5B%22staff-1%22%5D"
            ),
            {},
            {"x-acs-dingtalk-access-token": "test-access-token"},
            5,
        )
    ]
    assert "13800000000" not in str(result)
    assert "private-avatar" not in str(result)


@pytest.mark.parametrize(
    ("response", "error_code"),
    [
        (
            {"userList": [], "unauthorizedUserIdList": ["staff-1"]},
            "dingtalk_permission_denied",
        ),
        (
            {"userList": [], "unauthorizedUserIdList": []},
            "dingtalk_user_not_visible",
        ),
    ],
)
def test_get_user_classifies_latest_batch_endpoint_empty_results(
    response: dict[str, Any],
    error_code: str,
) -> None:
    with pytest.raises(NonRetryableExecutionError) as exc_info:
        DingTalkContactsClient(_TokenClient(), transport=_Transport(response)).get_user(
            user_id="staff-1",
            language="zh_CN",
        )

    assert exc_info.value.error_code == error_code


@pytest.mark.parametrize(
    "response",
    [
        {"result": {"userid": "staff-1"}},
        {"userList": {"userid": "staff-1"}, "unauthorizedUserIdList": []},
        {"userList": [{"userid": "different-user"}], "unauthorizedUserIdList": []},
    ],
)
def test_get_user_rejects_legacy_or_inconsistent_success_shapes(
    response: dict[str, Any],
) -> None:
    with pytest.raises(RetryableExecutionError) as exc_info:
        DingTalkContactsClient(_TokenClient(), transport=_Transport(response)).get_user(
            user_id="staff-1",
            language="zh_CN",
        )

    assert exc_info.value.error_code == "dingtalk_response_invalid"


def test_ambiguous_user_search_does_not_implicitly_prepare_or_send() -> None:
    transport = _Transport(
        {
            "list": ["staff-same-name-1", "staff-same-name-2"],
            "hasMore": False,
            "totalCount": 2,
        }
    )
    result = DingTalkContactsClient(_TokenClient(), transport=transport).search_users(
        query="庄慕焕",
        offset=0,
        page_size=20,
        exact_match=False,
    )
    database = _database()

    assert result["users"] == [
        {"user_id": "staff-same-name-1"},
        {"user_id": "staff-same-name-2"},
    ]
    assert [(method, url) for method, url, *_ in transport.calls] == [
        ("POST", "https://api.dingtalk.com/v1.0/contact/users/search")
    ]
    assert database.execute_one(
        "select count(*) as count from external_action_intent"
    ) == {"count": 0}


def test_contact_search_rejects_unknown_provider_item_shape() -> None:
    transport = _Transport({"list": [123], "hasMore": False, "totalCount": 1})

    with pytest.raises(RetryableExecutionError) as exc_info:
        DingTalkContactsClient(_TokenClient(), transport=transport).search_users(
            query="庄慕焕",
            offset=0,
            page_size=20,
            exact_match=False,
        )

    assert exc_info.value.error_code == "dingtalk_response_invalid"


def test_aitable_v1_projects_official_value_and_records_shapes_with_operator() -> None:
    transport = _Transport(
        {
            "value": [
                {"id": "sheet-1", "name": "数据表1"},
                {"id": "sheet-2", "name": "数据表2"},
            ]
        }
    )
    client = DingTalkAiTableReadClient(_TokenClient(), transport=transport)

    sheets = client.list_sheets(operator_id="union-1", base_id="base-1")

    assert sheets == {
        "sheets": [
            {"sheet_id": "sheet-1", "name": "数据表1"},
            {"sheet_id": "sheet-2", "name": "数据表2"},
        ],
        "returned": 2,
        "truncated": False,
        "untrusted_data": True,
    }
    assert transport.calls[0][0:3] == (
        "GET",
        "https://api.dingtalk.com/v1.0/notable/bases/base-1/sheets?operatorId=union-1",
        {},
    )

    transport.response = {
        "value": [
            {"id": "field-1", "name": "标题", "type": "text"},
            {"id": "field-2", "name": "排名", "type": "number"},
        ]
    }
    fields = client.list_fields(
        operator_id="union-1",
        base_id="base-1",
        sheet_id="sheet-1",
    )
    assert fields["returned"] == 2
    assert [item["field_id"] for item in fields["fields"]] == ["field-1", "field-2"]

    transport.response = {
        "records": [
            {
                "id": "record-1",
                "fields": {
                    "标题": "热搜",
                    "人员": [{"unionId": "union-1"}],
                    "关联": {"linkedRecordIds": ["record-2"]},
                },
            },
            {"id": "record-empty", "fields": {}},
        ],
        "hasMore": True,
        "nextToken": "next-1",
    }
    records = client.list_records(
        operator_id="union-1",
        base_id="base-1",
        sheet_id="sheet-1",
        page_size=20,
        cursor="cursor-1",
    )
    assert records["records"] == [
        {
            "record_id": "record-1",
            "fields": {
                "标题": "热搜",
                "人员": [{"unionId": "union-1"}],
                "关联": {"linkedRecordIds": ["record-2"]},
            },
        },
        {"record_id": "record-empty", "fields": {}},
    ]
    assert records["truncated"] is True
    assert records["next_cursor"] == "next-1"
    assert transport.calls[-1][0:3] == (
        "POST",
        (
            "https://api.dingtalk.com/v1.0/notable/bases/base-1/sheets/"
            "sheet-1/records/list?operatorId=union-1"
        ),
        {"maxResults": 20, "nextToken": "cursor-1"},
    )


def test_aitable_v1_targets_explicit_resources_for_current_operator() -> None:
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
        target_external_subject_id="staff-1",
        target_union_id="union-1",
        primary_calendar_id="primary",
        aitable_operator_id="union-1",
        source_conversation_type="direct",
        source_conversation_id="conversation-1",
        source_open_conversation_id="",
        source_robot_code="robot-1",
        enterprise_robot_code="robot-1",
        work_notification_agent_id=123,
        principal_jti="jti-1",
    )
    frozen, _summary = DingTalkMutationPreparationCatalog._insert_aitable_records(
        principal,
        {
            "base_id": "base-1",
            "sheet_id": "sheet-1",
            "records": [{"fields": {"名称": "记录"}}],
        },
    )

    assert frozen["_target"] == {
        "operator_id": "union-1",
        "base_id": "base-1",
        "sheet_id": "sheet-1",
    }

    read_transport = _Transport({"value": [{"id": "sheet-1", "name": "数据表"}]})
    read_result = DingTalkAiTableReadClient(
        _TokenClient(), transport=read_transport
    ).list_sheets(operator_id="union-1", base_id="base-1")
    assert read_result["returned"] == 1

    mutation_transport = _Transport({"value": [{"id": "record-1"}]})
    mutation_result = DingTalkAiTableMutationClient(
        _TokenClient(), transport=mutation_transport
    ).insert_records(operator_id="union-1", arguments=frozen)
    assert mutation_result["record_ids"] == ["record-1"]

    created_sheet, sheet_summary = (
        DingTalkMutationPreparationCatalog._create_aitable_sheet(
            principal,
            {
                "base_id": "base-1",
                "name": "验收表",
                "fields": [{"name": "标题", "type": "text"}],
            },
        )
    )
    assert created_sheet["_target"] == {
        "operator_id": "union-1",
        "base_id": "base-1",
    }
    assert sheet_summary["field_names"] == ["标题"]

    updated_field, field_summary = (
        DingTalkMutationPreparationCatalog._update_aitable_field(
            principal,
            {
                "base_id": "base-1",
                "sheet_id": "sheet-1",
                "field_id": "field-1",
                "name": "标题-更新",
            },
        )
    )
    assert updated_field["_target"] == {
        "operator_id": "union-1",
        "base_id": "base-1",
        "sheet_id": "sheet-1",
        "field_id": "field-1",
    }
    assert field_summary["field_id"] == "field-1"


def test_aitable_official_static_references_are_local_bounded_and_versioned() -> None:
    for executor in (
        DingTalkReadExecutorCatalog._get_aitable_supported_search_filters,
        DingTalkReadExecutorCatalog._get_aitable_supported_field_info,
        DingTalkReadExecutorCatalog._get_aitable_record_values_format,
    ):
        result = executor(None, {})  # type: ignore[arg-type]
        assert result["source_version"] == "dingtalk-mcp@1.1.21"
        assert result["trusted_reference"] is True
        assert 1 <= len(str(result["content"])) <= 16_000


def test_aitable_v1_non_delete_structure_mutations_use_operator_and_strict_targets() -> None:
    transport = _Transport({"id": "sheet-1", "name": "验收表"})
    client = DingTalkAiTableMutationClient(_TokenClient(), transport=transport)

    assert client.create_sheet(
        operator_id="union/1",
        arguments={
            "base_id": "base/1",
            "name": "验收表",
            "fields": [{"name": "标题", "type": "text"}],
        },
    ) == {"sheet_id": "sheet-1", "name": "验收表", "created": True}

    transport.response = {"id": "sheet-1", "name": "验收表-更新"}
    assert client.update_sheet(
        operator_id="union/1",
        arguments={"base_id": "base/1", "sheet_id": "sheet-1", "name": "验收表-更新"},
    ) == {"sheet_id": "sheet-1", "name": "验收表-更新", "updated": True}

    transport.response = {
        "id": "field-1",
        "name": "排名",
        "type": "number",
        "property": {"formatter": "INT"},
    }
    assert client.create_field(
        operator_id="union/1",
        arguments={
            "base_id": "base/1",
            "sheet_id": "sheet-1",
            "name": "排名",
            "type": "number",
            "property": {"formatter": "INT"},
        },
    ) == {
        "field_id": "field-1",
        "name": "排名",
        "field_type": "number",
        "created": True,
    }

    transport.response = {"id": "field-1"}
    assert client.update_field(
        operator_id="union/1",
        arguments={
            "base_id": "base/1",
            "sheet_id": "sheet-1",
            "field_id": "field-1",
            "name": "排名-更新",
            "property": {"formatter": "FLOAT_2"},
        },
    ) == {"field_id": "field-1", "updated": True}

    assert [(method, url, payload) for method, url, payload, *_ in transport.calls] == [
        (
            "POST",
            "https://api.dingtalk.com/v1.0/notable/bases/base%2F1/sheets?operatorId=union%2F1",
            {"name": "验收表", "fields": [{"name": "标题", "type": "text"}]},
        ),
        (
            "PUT",
            (
                "https://api.dingtalk.com/v1.0/notable/bases/base%2F1/sheets/"
                "sheet-1?operatorId=union%2F1"
            ),
            {"name": "验收表-更新"},
        ),
        (
            "GET",
            (
                "https://api.dingtalk.com/v1.0/notable/bases/base%2F1/sheets/"
                "sheet-1?operatorId=union%2F1"
            ),
            {},
        ),
        (
            "POST",
            (
                "https://api.dingtalk.com/v1.0/notable/bases/base%2F1/sheets/"
                "sheet-1/fields?operatorId=union%2F1"
            ),
            {"name": "排名", "type": "number", "property": {"formatter": "INT"}},
        ),
        (
            "PUT",
            (
                "https://api.dingtalk.com/v1.0/notable/bases/base%2F1/sheets/"
                "sheet-1/fields/field-1?operatorId=union%2F1"
            ),
            {"name": "排名-更新", "property": {"formatter": "FLOAT_2"}},
        ),
    ]


def test_aitable_sheet_update_uses_exact_get_postcondition_after_empty_ack() -> None:
    transport = _SequenceTransport(
        [
            {},
            {"id": "sheet-1", "name": "验收表-更新"},
        ]
    )

    assert DingTalkAiTableMutationClient(
        _TokenClient(), transport=transport
    ).update_sheet(
        operator_id="union/1",
        arguments={
            "base_id": "base/1",
            "sheet_id": "sheet-1",
            "name": "验收表-更新",
        },
    ) == {"sheet_id": "sheet-1", "name": "验收表-更新", "updated": True}

    assert [call[0] for call in transport.calls] == ["PUT", "GET"]


def test_aitable_sheet_update_rejects_postcondition_name_drift() -> None:
    transport = _SequenceTransport(
        [
            {},
            {"id": "sheet-1", "name": "仍是旧名称"},
        ]
    )

    with pytest.raises(RetryableExecutionError) as exc_info:
        DingTalkAiTableMutationClient(
            _TokenClient(), transport=transport
        ).update_sheet(
            operator_id="union/1",
            arguments={
                "base_id": "base/1",
                "sheet_id": "sheet-1",
                "name": "验收表-更新",
            },
        )

    assert exc_info.value.error_code == "dingtalk_response_invalid"

def test_aitable_search_projects_latest_storage_v2_items_shape() -> None:
    transport = _Transport(
        {
            "items": [
                {
                    "dentryUuid": "base-1",
                    "name": "新浪热搜",
                    "creator": {"userId": "staff-1", "name": "用户"},
                    "lastModifyTime": 1788074100000,
                }
            ],
            "nextToken": "next-1",
        }
    )

    result = DingTalkAiTableReadClient(
        _TokenClient(), transport=transport
    ).search(operator_id="union-1", query="新浪热搜", page_size=20, cursor="")

    assert result == {
        "aitables": [
            {
                "base_id": "base-1",
                "name": "新浪热搜",
                "creator_user_id": "staff-1",
                "updated_at": "1788074100000",
            }
        ],
        "returned": 1,
        "truncated": True,
        "next_cursor": "next-1",
        "untrusted_data": True,
    }


def test_aitable_search_rejects_retired_or_unknown_item_containers() -> None:
    for response in ({"dentries": []}, {"items": {}}, {}):
        with pytest.raises(RetryableExecutionError) as caught:
            DingTalkAiTableReadClient(
                _TokenClient(), transport=_Transport(response)
            ).search(
                operator_id="union-1",
                query="新浪热搜",
                page_size=20,
                cursor="",
            )
        assert caught.value.error_code == "dingtalk_response_invalid"


def test_bounded_provider_lists_report_overflow_as_truncated() -> None:
    sheet_result = DingTalkAiTableReadClient(
        _TokenClient(),
        transport=_Transport(
            {"value": [{"id": f"sheet-{index}", "name": "数据表"} for index in range(51)]}
        ),
    ).list_sheets(operator_id="union-1", base_id="base-1")

    assert sheet_result["returned"] == 50
    assert len(sheet_result["sheets"]) == 50
    assert sheet_result["truncated"] is True

    department_result = DingTalkContactsClient(
        _TokenClient(),
        transport=_Transport(
            {"result": {"userid_list": [f"staff-{index}" for index in range(51)]}}
        ),
    ).list_department_users(department_id=1)

    assert department_result["returned"] == 50
    assert len(department_result["users"]) == 50
    assert department_result["truncated"] is True


def test_provider_rejects_missing_required_business_fields_per_operation() -> None:
    with pytest.raises(RetryableExecutionError) as department_error:
        DingTalkDepartmentClient(
            _TokenClient(), transport=_Transport({"result": [{"dept_id": 2}]})
        ).list_sub_departments(parent_department_id=1, language="zh_CN")
    assert department_error.value.error_code == "dingtalk_response_invalid"

    with pytest.raises(RetryableExecutionError) as todo_error:
        DingTalkTodoReadClient(
            _TokenClient(), transport=_Transport({"todoCards": [{"taskId": "todo-1"}]})
        ).list_for_self(
            union_id="union-1",
            cursor="",
            is_done=False,
            role_types=["executor"],
        )
    assert todo_error.value.error_code == "dingtalk_response_invalid"

    with pytest.raises(RetryableExecutionError) as event_error:
        DingTalkCalendarReadClient(
            _TokenClient(), transport=_Transport({"id": "event-1", "summary": "会议"})
        ).get_event(union_id="union-1", event_id="event-1", max_attendees=20)
    assert event_error.value.error_code == "dingtalk_response_invalid"

    with pytest.raises(RetryableExecutionError) as aitable_error:
        DingTalkAiTableReadClient(
            _TokenClient(), transport=_Transport({"items": [{"dentryUuid": "base-1"}]})
        ).search(operator_id="union-1", query="表格", page_size=20, cursor="")
    assert aitable_error.value.error_code == "dingtalk_response_invalid"

    with pytest.raises(RetryableExecutionError) as sheet_error:
        DingTalkAiTableReadClient(
            _TokenClient(), transport=_Transport({"value": [{"id": "sheet-1"}]})
        ).list_sheets(operator_id="union-1", base_id="base-1")
    assert sheet_error.value.error_code == "dingtalk_response_invalid"

    with pytest.raises(RetryableExecutionError) as field_error:
        DingTalkAiTableReadClient(
            _TokenClient(),
            transport=_Transport({"value": [{"id": "field-1", "name": "标题"}]}),
        ).list_fields(operator_id="union-1", base_id="base-1", sheet_id="sheet-1")
    assert field_error.value.error_code == "dingtalk_response_invalid"

    with pytest.raises(RetryableExecutionError) as record_error:
        DingTalkAiTableReadClient(
            _TokenClient(),
            transport=_Transport({"records": [{"id": "record-1"}]}),
        ).list_records(
            operator_id="union-1",
            base_id="base-1",
            sheet_id="sheet-1",
            page_size=20,
            cursor="",
        )
    assert record_error.value.error_code == "dingtalk_response_invalid"


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"sheets": []},
        {"value": {}},
        {"value": [{"name": "缺少 ID"}]},
    ],
)
def test_aitable_sheet_list_rejects_unknown_or_incomplete_success_shapes(
    response: dict[str, Any],
) -> None:
    with pytest.raises(RetryableExecutionError) as caught:
        DingTalkAiTableReadClient(
            _TokenClient(),
            transport=_Transport(response),
        ).list_sheets(operator_id="union-1", base_id="base-1")

    assert caught.value.error_code == "dingtalk_response_invalid"


def test_work_notification_reads_project_official_legacy_response_shapes() -> None:
    transport = _Transport(
        {"progress": {"progress_in_percent": 75, "status": 1}}
    )
    client = DingTalkWorkNotificationReadClient(_TokenClient(), transport=transport)

    assert client.get_progress(agent_id=123, task_id=456) == {
        "progress": {"task_id": 456, "status": 1, "progress_percent": 75},
        "untrusted_data": True,
    }

    transport.response = {
        "send_result": {
            "invalid_user_id_list": {"string": ["invalid-1"]},
            "forbidden_user_id_list": ["forbidden-1"],
            "failed_user_id_list": [],
            "read_user_id_list": ["read-1"],
            "unread_user_id_list": ["unread-1"],
            "invalid_dept_id_list": {"number": [1, 2]},
        }
    }
    assert client.get_result(agent_id=123, task_id=456) == {
        "result": {
            "task_id": 456,
            "invalid_user_ids": ["invalid-1"],
            "invalid_user_count": 1,
            "forbidden_user_ids": ["forbidden-1"],
            "forbidden_user_count": 1,
            "failed_user_ids": [],
            "failed_user_count": 0,
            "read_user_ids": ["read-1"],
            "read_user_count": 1,
            "unread_user_ids": ["unread-1"],
            "unread_user_count": 1,
            "invalid_department_ids": [1, 2],
            "invalid_department_count": 2,
            "truncated": False,
        },
        "untrusted_data": True,
    }


def test_work_notification_result_reports_bounded_counts_and_rejects_bad_ids() -> None:
    users = [f"staff-{index}" for index in range(51)]
    result = DingTalkWorkNotificationReadClient(
        _TokenClient(),
        transport=_Transport(
            {
                "send_result": {
                    "invalid_user_id_list": users,
                    "forbidden_user_id_list": [],
                    "failed_user_id_list": [],
                    "read_user_id_list": [],
                    "unread_user_id_list": [],
                    "invalid_dept_id_list": [],
                }
            }
        ),
    ).get_result(agent_id=123, task_id=456)

    assert result["result"]["invalid_user_count"] == 51
    assert len(result["result"]["invalid_user_ids"]) == 50
    assert result["result"]["truncated"] is True

    with pytest.raises(RetryableExecutionError) as caught:
        DingTalkWorkNotificationReadClient(
            _TokenClient(),
            transport=_Transport(
                {
                    "send_result": {
                        "invalid_user_id_list": [{"unexpected": "value"}],
                    }
                }
            ),
        ).get_result(agent_id=123, task_id=456)
    assert caught.value.error_code == "dingtalk_response_invalid"


@pytest.mark.parametrize(
    ("method_name", "response"),
    [
        ("get_progress", {}),
        ("get_progress", {"progress": {"progress_in_percent": 101, "status": 2}}),
        ("get_progress", {"progress": {"progress_in_percent": 50, "status": 9}}),
        ("get_result", {}),
        ("get_result", {"send_result": {"invalid_user_id_list": "bad"}}),
    ],
)
def test_work_notification_reads_reject_unknown_success_shapes(
    method_name: str,
    response: dict[str, Any],
) -> None:
    client = DingTalkWorkNotificationReadClient(
        _TokenClient(),
        transport=_Transport(response),
    )
    with pytest.raises(RetryableExecutionError) as caught:
        getattr(client, method_name)(agent_id=123, task_id=456)
    assert caught.value.error_code == "dingtalk_response_invalid"


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


def test_robot_user_batch_schema_and_normalizer_preserve_official_input_semantics() -> None:
    contract = DINGTALK_TOOL_CONTRACTS[
        DINGTALK_BATCH_SEND_MESSAGE_TO_USERS_TOOL_IDENTIFIER
    ]
    arguments = {
        "user_ids": ["staff-2", "staff-1", "staff-2"],
        "msg_param": {"title": " 标题 ", "text": " 正文 "},
    }
    validated = _validated_payload(arguments, contract.input_schema, kind="request")
    catalog = DingTalkMutationPreparationCatalog(SimpleNamespace())
    assert catalog.preflight(contract.identifier) is None

    frozen, summary = catalog.normalizer(contract.identifier)(
        SimpleNamespace(enterprise_robot_code="robot-1"),  # type: ignore[arg-type]
        validated,
    )

    assert frozen == {
        "user_ids": ["staff-2", "staff-1", "staff-2"],
        "msg_param": {"title": " 标题 ", "text": " 正文 "},
        "_target": {"robot_code": "robot-1", "recipient_count": 3},
    }
    assert summary == {
        "operation": "批量发送钉钉机器人单聊",
        "recipient_count": 3,
        "recipient_id_suffixes": ["...taff-2", "...taff-1", "...taff-2"],
        "title": " 标题 ",
        "text": " 正文 ",
    }
    assert json_hash(frozen) != json_hash(
        {**frozen, "user_ids": ["staff-1", "staff-2", "staff-2"]}
    )


def test_group_robot_normalizer_requires_a_trusted_group_source() -> None:
    catalog = DingTalkMutationPreparationCatalog(SimpleNamespace())
    normalizer = catalog.normalizer(DINGTALK_SEND_MESSAGE_TO_GROUP_TOOL_IDENTIFIER)
    principal = SimpleNamespace(
        source_robot_code="robot-1",
        source_conversation_type="group",
        source_open_conversation_id="open-group-1",
    )

    frozen, summary = normalizer(principal, {"title": "标题", "text": "正文"})

    assert frozen == {
        "title": "标题",
        "text": "正文",
        "_target": {
            "open_conversation_id": "open-group-1",
            "robot_code": "robot-1",
        },
    }
    assert summary == {
        "operation": "向当前钉钉来源群发送机器人消息",
        "target": "当前群聊",
        "title": "标题",
        "text": "正文",
    }

    principal.source_conversation_type = "direct"
    with pytest.raises(NonRetryableExecutionError) as caught:
        normalizer(principal, {"title": "标题", "text": "正文"})
    assert caught.value.error_code == "dingtalk_mutation_not_ready"


def test_robot_user_batch_reuses_one_intent_for_identical_ordered_arguments() -> None:
    database = _database()
    service = ExternalActionService(
        ExternalActionRepository(database),
        ExternalActionTokenSigner("k" * 32),
        _Audit(),
    )
    definition = MCP_TOOL_MANIFEST[DINGTALK_BATCH_SEND_MESSAGE_TO_USERS_TOOL_IDENTIFIER]
    facts = {
        **_facts(),
        "tool_identifier": definition.identifier,
        "schema_hash": definition.schema_hash,
        "operation_code": definition.operation_code,
    }
    arguments = {
        "user_ids": ["staff-2", "staff-1", "staff-2"],
        "msg_param": {"title": "标题", "text": "正文"},
        "_target": {"robot_code": "robot-1", "recipient_count": 3},
    }
    summary = {
        "operation": "批量发送钉钉机器人单聊",
        "recipient_count": 3,
        "recipient_id_suffixes": ["...taff-2", "...taff-1", "...taff-2"],
        "title": "标题",
        "text": "正文",
    }

    first, first_created = service.prepare(
        facts=facts,
        arguments=arguments,
        arguments_hash=json_hash(arguments),
        safe_summary=summary,
        mcp_call_id="mcp-call-1",
    )
    second, second_created = service.prepare(
        facts=facts,
        arguments=arguments,
        arguments_hash=json_hash(arguments),
        safe_summary=summary,
        mcp_call_id="mcp-call-2",
    )
    reordered_arguments = {
        **arguments,
        "user_ids": ["staff-1", "staff-2", "staff-2"],
    }
    reordered, reordered_created = service.prepare(
        facts=facts,
        arguments=reordered_arguments,
        arguments_hash=json_hash(reordered_arguments),
        safe_summary={
            **summary,
            "recipient_id_suffixes": ["...taff-1", "...taff-2", "...taff-2"],
        },
        mcp_call_id="mcp-call-3",
    )

    assert first_created is True
    assert second_created is False
    assert second["id"] == first["id"]
    assert reordered_created is True
    assert reordered["id"] != first["id"]
    assert database.execute_one(
        "select count(*) as count from external_action_card_outbox"
    ) == {"count": 2}


@pytest.mark.parametrize(
    "arguments",
    [
        {"user_ids": [], "msg_param": {"title": "标题", "text": "正文"}},
        {"user_ids": [""], "msg_param": {"title": "标题", "text": "正文"}},
        {
            "user_ids": ["staff-1"],
            "msg_param": {"title": "标题", "text": "正文", "msgKey": "forged"},
        },
        {
            "user_ids": ["staff-1"],
            "msg_param": {"title": "标题", "text": "正文"},
            "robot_code": "forged",
        },
    ],
)
def test_robot_user_batch_schema_rejects_empty_or_server_owned_fields(
    arguments: dict[str, Any],
) -> None:
    schema = MCP_TOOL_MANIFEST[
        DINGTALK_BATCH_SEND_MESSAGE_TO_USERS_TOOL_IDENTIFIER
    ].input_schema
    with pytest.raises(NonRetryableExecutionError) as caught:
        _validated_payload(arguments, schema, kind="request")
    assert caught.value.error_code == "dingtalk_request_invalid"


def test_robot_user_batch_rejects_global_intent_payload_overflow_before_prepare() -> None:
    contract = DINGTALK_TOOL_CONTRACTS[
        DINGTALK_BATCH_SEND_MESSAGE_TO_USERS_TOOL_IDENTIFIER
    ]
    principal = SimpleNamespace(enterprise_robot_code="robot-1")

    class _Resolver:
        @staticmethod
        def audit_context(*_args: Any, **_kwargs: Any) -> object:
            return object()

        @staticmethod
        def resolve(*_args: Any, **_kwargs: Any) -> object:
            return principal

    class _Actions:
        @staticmethod
        def prepare(**_values: Any) -> tuple[dict[str, Any], bool]:
            raise AssertionError("oversized arguments must not create an Intent")

    class _McpAudit:
        @staticmethod
        def begin(*_args: Any, **_kwargs: Any) -> Any:
            return SimpleNamespace(mcp_call_id="mcp-call-1")

        @staticmethod
        def append_event(*_args: Any, **_kwargs: Any) -> None:
            return None

        @staticmethod
        def complete(*_args: Any, **_kwargs: Any) -> None:
            return None

    normalizer = DingTalkMutationPreparationCatalog(SimpleNamespace()).normalizer(
        contract.identifier
    )
    service = DingTalkMutationToolService(
        contract,
        _Resolver(),  # type: ignore[arg-type]
        _Actions(),  # type: ignore[arg-type]
        _McpAudit(),  # type: ignore[arg-type]
        normalizer,
    )
    large_user_ids = [f"user-{index:03d}-" + "x" * 500 for index in range(40)]

    with pytest.raises(NonRetryableExecutionError) as caught:
        service.invoke(
            claims={},
            arguments={
                "user_ids": large_user_ids,
                "msg_param": {"title": "标题", "text": "正文"},
            },
            correlation_id="correlation-1",
            invocation_id="job-1.attempt-0",
        )

    assert caught.value.error_code == "dingtalk_mutation_arguments_too_large"


def test_worker_reauthorizes_robot_user_batch_target_without_user_detail_preflight() -> None:
    class _ConnectorRegistry:
        robot_code = "robot-1"

        @staticmethod
        def require_dingtalk_stream_ingress(connector_id: str) -> dict[str, str]:
            assert connector_id == "connector-1"
            return {"id": connector_id}

        def metadata_value(self, _connector: object, key: str) -> str:
            assert key == "default_robot_code"
            return self.robot_code

    connector_registry = _ConnectorRegistry()
    worker = ExternalActionWorker.__new__(ExternalActionWorker)
    worker.runtime = SimpleNamespace(connector_registry=connector_registry)
    arguments = {
        "user_ids": ["staff-2", "staff-1", "staff-2"],
        "msg_param": {"title": "标题", "text": "正文"},
        "_target": {"robot_code": "robot-1", "recipient_count": 3},
    }
    worker.repository = SimpleNamespace(  # type: ignore[assignment]
        decode_json=lambda _value: arguments
    )
    intent = {"source_connector_id": "connector-1", "arguments_json": "{}"}
    contract = DINGTALK_TOOL_CONTRACTS[
        DINGTALK_BATCH_SEND_MESSAGE_TO_USERS_TOOL_IDENTIFIER
    ]

    worker._reauthorize_target(intent, contract)
    connector_registry.robot_code = "robot-2"
    with pytest.raises(ValueError, match="batch target facts drifted"):
        worker._reauthorize_target(intent, contract)


def test_worker_reauthorizes_explicit_aitable_resource_target() -> None:
    worker = ExternalActionWorker.__new__(ExternalActionWorker)
    arguments = {
        "base_id": "base-1",
        "sheet_id": "sheet-1",
        "records": [{"fields": {"名称": "记录"}}],
        "_target": {
            "operator_id": "union-1",
            "base_id": "base-1",
            "sheet_id": "sheet-1",
        },
    }
    worker.repository = SimpleNamespace(  # type: ignore[assignment]
        decode_json=lambda _value: arguments
    )
    intent = {"arguments_json": "{}", "target_union_id": "union-1"}
    contract = DINGTALK_TOOL_CONTRACTS["dingtalk_insert_aitable_records"]

    worker._reauthorize_target(intent, contract)
    arguments["_target"]["operator_id"] = "union-other"
    with pytest.raises(ValueError, match="AI table target facts drifted"):
        worker._reauthorize_target(intent, contract)
    arguments["_target"]["operator_id"] = "union-1"
    arguments["_target"] = {
        "operator_id": "union-1",
        "base_id": "base-1",
        "sheet_id": "sheet-other",
    }
    with pytest.raises(ValueError, match="AI table target facts drifted"):
        worker._reauthorize_target(intent, contract)


def test_worker_reauthorizes_connector_enterprise_binding_before_credentials() -> None:
    class _Database:
        eligible = True

        def execute_one(self, sql: str, values: tuple[str, str]) -> dict[str, str] | None:
            assert "join dingtalk_enterprise" in sql
            assert values == ("connector-1", "enterprise-1")
            return {"status": "ACTIVE"} if self.eligible else None

    class _ConnectorRegistry:
        @staticmethod
        def require_dingtalk_stream_ingress(connector_id: str) -> object:
            assert connector_id == "connector-1"
            return object()

        @staticmethod
        def metadata_value(_connector: object, key: str) -> str:
            assert key == "client_id"
            return "client-1"

        @staticmethod
        def resolve_secret(_connector: object) -> str:
            return "secret-1"

    database = _Database()
    worker = ExternalActionWorker.__new__(ExternalActionWorker)
    worker.runtime = SimpleNamespace(
        database=database,
        connector_registry=_ConnectorRegistry(),
    )
    intent = {
        "source_connector_id": "connector-1",
        "dingtalk_enterprise_id": "enterprise-1",
    }

    assert worker._connector_credentials(intent) == ("client-1", "secret-1")
    database.eligible = False
    with pytest.raises(ValueError, match="enterprise binding"):
        worker._connector_credentials(intent)


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


def test_provider_permission_error_preserves_only_bounded_official_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise(*_args: Any, **_kwargs: Any) -> None:
        raise HTTPError(
            "https://api.dingtalk.com/fixed",
            403,
            "provider body must not escape",
            None,
            io.BytesIO(
                json.dumps(
                    {
                        "code": "Forbidden.AccessDenied",
                        "message": "private provider explanation must not escape",
                        "details": {"credential": "secret-value"},
                    }
                ).encode()
            ),
        )

    monkeypatch.setattr("services.dingtalk_mcp_server.provider.urlopen", _raise)
    with pytest.raises(NonRetryableExecutionError) as caught:
        UrllibDingTalkJsonTransport().request_json(
            "GET",
            "https://api.dingtalk.com/fixed",
            {},
            {"x-acs-dingtalk-access-token": "token-secret"},
            5,
        )

    assert caught.value.error_code == "dingtalk_permission_denied"
    assert caught.value.diagnostics == {
        "provider_error_code": "Forbidden.AccessDenied"
    }
    assert "Forbidden.AccessDenied" in caught.value.safe_message
    assert "private provider explanation" not in caught.value.safe_message
    assert "secret-value" not in str(caught.value)
    assert "token-secret" not in str(caught.value)


@pytest.mark.parametrize(
    "unsafe_code",
    [
        "code with spaces",
        "code/with/slashes",
        "x" * 97,
        {"nested": "code"},
        True,
    ],
)
def test_provider_permission_error_rejects_unsafe_provider_code(
    monkeypatch: pytest.MonkeyPatch,
    unsafe_code: object,
) -> None:
    def _raise(*_args: Any, **_kwargs: Any) -> None:
        raise HTTPError(
            "https://api.dingtalk.com/fixed",
            403,
            "forbidden",
            None,
            io.BytesIO(json.dumps({"code": unsafe_code}).encode()),
        )

    monkeypatch.setattr("services.dingtalk_mcp_server.provider.urlopen", _raise)
    with pytest.raises(NonRetryableExecutionError) as caught:
        UrllibDingTalkJsonTransport().request_json(
            "GET",
            "https://api.dingtalk.com/fixed",
            {},
            {},
            5,
        )

    assert caught.value.error_code == "dingtalk_permission_denied"
    assert caught.value.diagnostics == {}
    assert caught.value.safe_message == "钉钉应用缺少此能力所需权限或可见范围"


def test_todo_subject_is_business_input_not_a_principal_override() -> None:
    assert contains_forbidden_tool_input({"subject": "回访客户"}) is False
    assert contains_forbidden_tool_input({"sub": "forged-principal"}) is True
    assert contains_forbidden_tool_input({"actor_id": "forged-actor"}) is True
    assert contains_forbidden_tool_input({"user_id": "forged-user"}) is True
    assert (
        contains_forbidden_tool_input(
            {"user_id": "explicit-business-target"},
            declared_root_fields=frozenset({"user_id"}),
        )
        is False
    )
    assert (
        contains_forbidden_tool_input(
            {"user_id": "explicit-business-target", "actor_id": "forged-actor"},
            declared_root_fields=frozenset({"user_id"}),
        )
        is True
    )


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
                    "metadata": (
                        '{"default_robot_code":"enterprise-robot-1",'
                        '"work_notification_agent_id":123456}'
                    ),
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
    assert principal.enterprise_robot_code == "enterprise-robot-1"
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


def test_worker_result_card_uses_bounded_provider_acceptance_status(
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
                "target_external_subject_id": "staff-1",
                "safe_summary_json": "summary",
            }

        @staticmethod
        def decode_json(value: str) -> dict[str, str]:
            if value == "payload":
                return {
                    "status": "succeeded",
                    "statusText": "批量消息请求已受理：1 人受理，2 人未受理",
                }
            return {"operation": "批量发送钉钉机器人单聊"}

        def complete_card(self, outbox_id: str) -> None:
            self.completed.append(outbox_id)

        def fail_card(self, outbox_id: str, **_values: str) -> None:
            self.failed.append(outbox_id)

    class _CardClient:
        def __init__(self, _token_client: Any) -> None:
            pass

        @staticmethod
        def update(**values: Any) -> None:
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

    worker._dispatch_card(
        {
            "id": "card-outbox-1",
            "action_intent_id": "action-1",
            "event_kind": "RESULT_UPDATE",
            "payload_json": "payload",
        }
    )

    assert repository.completed == ["card-outbox-1"]
    assert repository.failed == []
    assert captured["card_fields"]["status"] == "succeeded"
    assert (
        captured["card_fields"]["statusText"]
        == "批量消息请求已受理：1 人受理，2 人未受理"
    )


def test_worker_async_success_text_never_claims_final_delivery() -> None:
    group = DINGTALK_TOOL_CONTRACTS[DINGTALK_SEND_MESSAGE_TO_GROUP_TOOL_IDENTIFIER]
    batch = DINGTALK_TOOL_CONTRACTS[DINGTALK_BATCH_SEND_MESSAGE_TO_USERS_TOOL_IDENTIFIER]
    notice = DINGTALK_TOOL_CONTRACTS["dingtalk_send_work_notification"]

    assert "已受理" in ExternalActionWorker._success_card_status_text(
        group,
        {"accepted": True},
    )
    assert "送达" in ExternalActionWorker._success_card_status_text(
        group,
        {"accepted": True},
    )
    assert ExternalActionWorker._success_card_status_text(
        batch,
        {
            "accepted_count": 1,
            "not_accepted_count": 2,
            "filtered_count": 1,
            "flow_controlled_count": 1,
            "invalid_count": 0,
            "fully_accepted": False,
        },
    ) == "批量消息请求已受理：1 人受理，2 人未受理"
    assert "已提交" in ExternalActionWorker._success_card_status_text(
        notice,
        {"accepted": True, "task_id": 321},
    )


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


def test_fixed_mutation_clients_use_the_ten_allowlisted_operations() -> None:
    transport = _Transport(
        {
            "id": "event/1",
            "task_id": 321,
            "result": True,
            "value": [{"id": "record/1"}],
            "processQueryKey": "request-1",
        }
    )
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
    DingTalkRobotMutationClient(token, transport=transport).send_to_group(
        arguments={
            "title": "标题",
            "text": "正文",
            "_target": {
                "open_conversation_id": "cid/1",
                "robot_code": "robot-1",
            },
        }
    )
    DingTalkRobotMutationClient(token, transport=transport).batch_send_to_users(
        arguments={
            "user_ids": ["staff-1", "staff-2"],
            "msg_param": {"title": "批量标题", "text": "批量正文"},
            "_target": {"robot_code": "robot-1", "recipient_count": 2},
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
            (
                "https://api.dingtalk.com/v1.0/todo/users/union%2F1/tasks/"
                "todo%2F1/executorStatus"
            ),
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
        ("POST", "https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend"),
        (
            "POST",
            "https://oapi.dingtalk.com/topapi/message/corpconversation/asyncsend_v2?access_token=test-access-token",
        ),
    ]
    for _method, url, _payload, headers, _timeout in transport.calls:
        if url.startswith("https://oapi.dingtalk.com/"):
            assert headers == {}
            assert "access_token=test-access-token" in url
        else:
            assert headers == {"x-acs-dingtalk-access-token": "test-access-token"}
            assert "access_token=" not in url
    assert transport.calls[7][2] == {
        "robotCode": "robot-1",
        "msgKey": "sampleMarkdown",
        "msgParam": '{"title":"标题","text":"正文"}',
        "openConversationId": "cid/1",
    }
    assert transport.calls[2][2] == {
        "executorStatusList": [{"id": "union/1", "isDone": True}]
    }
    assert transport.calls[8][2] == {
        "robotCode": "robot-1",
        "userIds": ["staff-1", "staff-2"],
        "msgKey": "sampleMarkdown",
        "msgParam": '{"title":"批量标题","text":"批量正文"}',
    }
    assert transport.calls[9][2] == {
        "agent_id": 123,
        "userid_list": "staff-1",
        "to_all_user": False,
        "msg": {
            "msgtype": "markdown",
            "markdown": {"title": "标题", "text": "正文"},
        },
    }


def test_mutation_success_responses_reject_target_or_record_drift() -> None:
    with pytest.raises(RetryableExecutionError) as calendar_error:
        DingTalkCalendarMutationClient(
            _TokenClient(), transport=_Transport({"id": "different-event"})
        ).update_for_self(
            union_id="union-1",
            arguments={"event_id": "event-1", "title": "更新"},
        )
    assert calendar_error.value.error_code == "dingtalk_response_invalid"

    with pytest.raises(RetryableExecutionError) as inserted_error:
        DingTalkAiTableMutationClient(
            _TokenClient(),
            transport=_Transport({"value": [{"id": "record-1"}, {"id": "record-2"}]}),
        ).insert_records(
            operator_id="union-1",
            arguments={
                "base_id": "base-1",
                "sheet_id": "sheet-1",
                "records": [{"fields": {"名称": "记录"}}],
            },
        )
    assert inserted_error.value.error_code == "dingtalk_response_invalid"

    with pytest.raises(RetryableExecutionError) as updated_error:
        DingTalkAiTableMutationClient(
            _TokenClient(),
            transport=_Transport({"value": [{"id": "different-record"}]}),
        ).update_records(
            operator_id="union-1",
            arguments={
                "base_id": "base-1",
                "sheet_id": "sheet-1",
                "records": [{"record_id": "record-1", "fields": {"名称": "更新"}}],
            },
        )
    assert updated_error.value.error_code == "dingtalk_response_invalid"


def test_robot_and_work_notification_results_report_acceptance_not_delivery() -> None:
    group = DingTalkRobotMutationClient(
        _TokenClient(),
        transport=_Transport({"processQueryKey": "group-request-1"}),
    ).send_to_group(
        arguments={
            "title": "标题",
            "text": "正文",
            "_target": {
                "open_conversation_id": "conversation-1",
                "robot_code": "robot-1",
            },
        }
    )
    assert group == {"message_request_id": "group-request-1", "accepted": True}
    assert "sent" not in group

    batch = DingTalkRobotMutationClient(
        _TokenClient(),
        transport=_Transport(
            {
                "processQueryKey": "batch-request-1",
                "filteredStaffIdList": ["staff-2"],
                "flowControlledStaffIdList": ["staff-3"],
                "invalidStaffIdList": ["staff-2"],
            }
        ),
    ).batch_send_to_users(
        arguments={
            "user_ids": ["staff-1", "staff-2", "staff-3"],
            "msg_param": {"title": "标题", "text": "正文"},
            "_target": {"robot_code": "robot-1", "recipient_count": 3},
        }
    )
    assert batch == {
        "message_request_id": "batch-request-1",
        "recipient_count": 3,
        "accepted_count": 1,
        "not_accepted_count": 2,
        "filtered_count": 1,
        "flow_controlled_count": 1,
        "invalid_count": 1,
        "fully_accepted": False,
        "accepted": True,
    }
    assert "staff-2" not in str(batch)
    assert "staff-3" not in str(batch)
    assert "sent" not in batch

    notice = DingTalkWorkNotificationMutationClient(
        _TokenClient(),
        transport=_Transport({"task_id": 321}),
    ).send_to_self(
        arguments={
            "title": "标题",
            "text": "正文",
            "_target": {"agent_id": 123, "staff_id": "staff-1"},
        }
    )
    assert notice == {"task_id": 321, "accepted": True}
    assert "sent" not in notice


def test_robot_user_batch_rejects_provider_recipient_drift() -> None:
    client = DingTalkRobotMutationClient(
        _TokenClient(),
        transport=_Transport(
            {
                "processQueryKey": "batch-request-1",
                "invalidStaffIdList": ["not-requested"],
            }
        ),
    )

    with pytest.raises(RetryableExecutionError) as exc_info:
        client.batch_send_to_users(
            arguments={
                "user_ids": ["staff-1"],
                "msg_param": {"title": "标题", "text": "正文"},
                "_target": {"robot_code": "robot-1", "recipient_count": 1},
            }
        )

    assert exc_info.value.error_code == "dingtalk_response_invalid"


def test_calendar_all_day_uses_official_date_objects() -> None:
    transport = _Transport({"id": "event-1"})
    principal = ResolvedDingTalkPrincipal(
        job_id="job-1",
        session_id="session-1",
        actor_user_id="user-1",
        business_application_id="application-1",
        agent_publication_id="agent-publication-1",
        application_publication_id="application-publication-1",
        source_connector_id="connector-1",
        dingtalk_enterprise_id="enterprise-1",
        external_identity_id="external-identity-1",
        target_external_subject_id="staff-1",
        target_union_id="union-1",
        primary_calendar_id="primary",
        aitable_operator_id="union-1",
        source_conversation_type="group",
        source_conversation_id="conversation-1",
        source_open_conversation_id="cid-1",
        source_robot_code="robot-1",
        enterprise_robot_code="robot-1",
        work_notification_agent_id=123,
        principal_jti="principal-jti-1",
    )
    frozen, _summary = DingTalkMutationPreparationCatalog._create_calendar_event(
        principal,
        {
            "title": "全天验收",
            "start_time": "2026-08-30T00:00:00+08:00",
            "end_time": "2026-08-31T00:00:00+08:00",
            "time_zone": "Asia/Shanghai",
            "all_day": True,
        },
    )

    DingTalkCalendarMutationClient(
        _TokenClient(), transport=transport
    ).create_for_self(union_id="union-1", arguments=frozen)

    assert transport.calls[0][2] == {
        "summary": "全天验收",
        "isAllDay": True,
        "start": {"date": "2026-08-30"},
        "end": {"date": "2026-08-31"},
    }


def test_calendar_all_day_rejects_nonexclusive_same_date_range() -> None:
    principal = ResolvedDingTalkPrincipal(
        job_id="job-1",
        session_id="session-1",
        actor_user_id="user-1",
        business_application_id="application-1",
        agent_publication_id="agent-publication-1",
        application_publication_id="application-publication-1",
        source_connector_id="connector-1",
        dingtalk_enterprise_id="enterprise-1",
        external_identity_id="external-identity-1",
        target_external_subject_id="staff-1",
        target_union_id="union-1",
        primary_calendar_id="primary",
        aitable_operator_id="union-1",
        source_conversation_type="group",
        source_conversation_id="conversation-1",
        source_open_conversation_id="cid-1",
        source_robot_code="robot-1",
        enterprise_robot_code="robot-1",
        work_notification_agent_id=123,
        principal_jti="principal-jti-1",
    )
    with pytest.raises(NonRetryableExecutionError) as caught:
        DingTalkMutationPreparationCatalog._create_calendar_event(
            principal,
            {
                "title": "全天验收",
                "start_time": "2026-08-30T09:00:00+08:00",
                "end_time": "2026-08-30T18:00:00+08:00",
                "time_zone": "Asia/Shanghai",
                "all_day": True,
            },
        )
    assert caught.value.error_code == "external_action_arguments_invalid"


def test_mutation_clients_reject_unknown_success_response_shapes() -> None:
    with pytest.raises(RetryableExecutionError) as todo_create:
        DingTalkTodoClient(
            _TokenClient(), transport=_Transport({})
        ).create_for_self(union_id="union-1", arguments={"subject": "创建"})
    assert todo_create.value.error_code == "dingtalk_response_invalid"

    with pytest.raises(RetryableExecutionError) as todo_update:
        DingTalkTodoClient(
            _TokenClient(), transport=_Transport({"result": False})
        ).update_for_self(
            union_id="union-1",
            arguments={"task_id": "task-1", "subject": "更新"},
        )
    assert todo_update.value.error_code == "dingtalk_response_invalid"

    with pytest.raises(RetryableExecutionError) as calendar_create:
        DingTalkCalendarMutationClient(
            _TokenClient(), transport=_Transport({"result": {"id": "event-1"}})
        ).create_for_self(
            union_id="union-1",
            arguments={
                "title": "日程",
                "start_time": "2026-08-30T10:00:00+08:00",
                "end_time": "2026-08-30T11:00:00+08:00",
                "time_zone": "Asia/Shanghai",
            },
        )
    assert calendar_create.value.error_code == "dingtalk_response_invalid"

    with pytest.raises(RetryableExecutionError) as robot_group:
        DingTalkRobotMutationClient(
            _TokenClient(), transport=_Transport({"processQueryKeys": ["request-1"]})
        ).send_to_group(
            arguments={
                "title": "标题",
                "text": "正文",
                "_target": {
                    "open_conversation_id": "cid-1",
                    "robot_code": "robot-1",
                },
            }
        )
    assert robot_group.value.error_code == "dingtalk_response_invalid"

    with pytest.raises(RetryableExecutionError) as work_notice:
        DingTalkWorkNotificationMutationClient(
            _TokenClient(), transport=_Transport({})
        ).send_to_self(
            arguments={
                "title": "标题",
                "text": "正文",
                "_target": {"agent_id": 123, "staff_id": "staff-1"},
            }
        )
    assert work_notice.value.error_code == "dingtalk_response_invalid"


def test_robot_user_batch_provider_rejects_target_drift_before_io() -> None:
    transport = _Transport()
    client = DingTalkRobotMutationClient(_TokenClient(), transport=transport)

    with pytest.raises(NonRetryableExecutionError) as caught:
        client.batch_send_to_users(
            arguments={
                "user_ids": ["staff-1", "staff-2"],
                "msg_param": {"title": "标题", "text": "正文"},
                "_target": {"robot_code": "robot-1", "recipient_count": 1},
            }
        )

    assert caught.value.error_code == "dingtalk_robot_user_batch_invalid"
    assert transport.calls == []

    with pytest.raises(NonRetryableExecutionError):
        client.batch_send_to_users(
            arguments={
                "user_ids": ["staff-1"],
                "msg_param": {"title": "标题", "text": "正文"},
                "_target": {"robot_code": "robot-1", "recipient_count": True},
            }
        )
    assert transport.calls == []


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
            "当前用户可访问的指定 AI 表格",
        ),
        (
            "dingtalk.robot.group_message.send",
            {
                "operation": "向当前钉钉来源群发送机器人消息",
                "target": "当前群聊",
                "title": "结果",
                "text": "已完成",
            },
            "当前群聊",
        ),
        (
            "dingtalk.robot.batch_send_message_to_users",
            {
                "operation": "批量发送钉钉机器人单聊",
                "recipient_count": 1,
                "recipient_id_suffixes": ["...taff-1"],
                "title": "结果",
                "text": "已完成",
            },
            "1 名明确收件人",
        ),
        (
            "dingtalk.robot.batch_send_message_to_users",
            {
                "operation": "批量发送钉钉机器人单聊",
                "recipient_count": 2,
                "recipient_id_suffixes": ["...taff-1", "...taff-2"],
                "title": "结果",
                "text": "已完成",
            },
            "2 名明确收件人",
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


def test_user_batch_mcp_audit_excludes_recipient_ids_message_and_target_secrets() -> None:
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
        enterprise_robot_code="enterprise-robot-secret",
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
    tool_contract = DINGTALK_TOOL_CONTRACTS[
        DINGTALK_BATCH_SEND_MESSAGE_TO_USERS_TOOL_IDENTIFIER
    ]
    normalizer = DingTalkMutationPreparationCatalog(SimpleNamespace()).normalizer(
        tool_contract.identifier
    )

    service = DingTalkMutationToolService(
        tool_contract,
        _Resolver(),  # type: ignore[arg-type]
        _Actions(),  # type: ignore[arg-type]
        audit,  # type: ignore[arg-type]
        normalizer,
    )
    service.invoke(
        claims={},
        arguments={
            "user_ids": ["staff-full-secret-alpha", "staff-full-secret-beta"],
            "msg_param": {"title": "机密标题", "text": "正文绝密 private@example.invalid"},
        },
        correlation_id="correlation-1",
        invocation_id="job-1.attempt-0",
    )
    encoded_audit = str(audit.values)
    for forbidden in (
        "机密标题",
        "正文绝密",
        "private@example.invalid",
        "staff-full-secret-alpha",
        "staff-full-secret-beta",
        "open-conversation-secret",
        "robot-secret",
        "enterprise-robot-secret",
        "staff-secret",
        "union-secret",
        "jti-secret",
    ):
        assert forbidden not in encoded_audit
