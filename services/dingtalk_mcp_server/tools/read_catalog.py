from __future__ import annotations

from datetime import datetime
from typing import Any

from app.bootstrap import Container
from app.modules.dingding.infrastructure.dingtalk_delivery_clients import DingTalkAccessTokenClient
from app.modules.mcp_audit import McpAuditCoordinator
from app.shared.dingtalk_tool_contracts import (
    DINGTALK_READ_TOOL_IDENTIFIERS,
    DINGTALK_TOOL_CONTRACTS,
)
from app.shared.exceptions import NonRetryableExecutionError
from services.dingtalk_mcp_server.auth.principal import (
    DingTalkPrincipalResolver,
    ResolvedDingTalkPrincipal,
)
from services.dingtalk_mcp_server.notable_references import (
    NOTABLE_RECORD_VALUES_FORMAT,
    NOTABLE_SUPPORTED_FIELD_INFO,
    NOTABLE_SUPPORTED_SEARCH_FILTERS,
    notable_reference,
)
from services.dingtalk_mcp_server.provider import (
    DingTalkAiTableReadClient,
    DingTalkCalendarReadClient,
    DingTalkContactsClient,
    DingTalkDepartmentClient,
    DingTalkJsonTransport,
    DingTalkTodoReadClient,
    DingTalkWorkNotificationReadClient,
)
from services.dingtalk_mcp_server.tools.read_tool import DingTalkReadToolService, ReadExecutor


class DingTalkReadExecutorCatalog:
    def __init__(
        self,
        runtime: Container,
        *,
        transport: DingTalkJsonTransport | None = None,
    ) -> None:
        self.runtime = runtime
        self.transport = transport
        self._executors: dict[str, ReadExecutor] = {
            "dingtalk_search_users": self._search_users,
            "dingtalk_get_user": self._get_user,
            "dingtalk_list_department_users": self._list_department_users,
            "dingtalk_search_departments": self._search_departments,
            "dingtalk_get_department": self._get_department,
            "dingtalk_list_sub_departments": self._list_sub_departments,
            "dingtalk_list_todos": self._list_todos,
            "dingtalk_get_calendar_event": self._get_calendar_event,
            "dingtalk_list_calendar_events": self._list_calendar_events,
            "dingtalk_list_calendar_attendees": self._list_calendar_attendees,
            "dingtalk_search_aitables": self._search_aitables,
            "dingtalk_get_aitable_supported_search_filters": (
                self._get_aitable_supported_search_filters
            ),
            "dingtalk_get_aitable_supported_field_info": (
                self._get_aitable_supported_field_info
            ),
            "dingtalk_get_aitable_record_values_format": (
                self._get_aitable_record_values_format
            ),
            "dingtalk_list_aitable_sheets": self._list_aitable_sheets,
            "dingtalk_get_aitable_sheet": self._get_aitable_sheet,
            "dingtalk_list_aitable_fields": self._list_aitable_fields,
            "dingtalk_list_aitable_records": self._list_aitable_records,
            "dingtalk_get_aitable_record": self._get_aitable_record,
            "dingtalk_get_work_notification_progress": self._get_notice_progress,
            "dingtalk_get_work_notification_result": self._get_notice_result,
        }
        if set(self._executors) != set(DINGTALK_READ_TOOL_IDENTIFIERS):
            raise ValueError("DingTalk read executor catalog is incomplete")

    def require(self, identifier: str) -> ReadExecutor:
        try:
            return self._executors[identifier]
        except KeyError as exc:
            raise ValueError(f"Unknown DingTalk read executor: {identifier}") from exc

    def token_client(self, principal: ResolvedDingTalkPrincipal) -> DingTalkAccessTokenClient:
        connector = self.runtime.connector_registry.require_dingtalk_stream_ingress(
            principal.source_connector_id
        )
        client_id = self.runtime.connector_registry.metadata_value(connector, "client_id")
        client_secret = self.runtime.connector_registry.resolve_secret(connector)
        if not client_id or not client_secret:
            raise NonRetryableExecutionError(
                "DingTalk Connector credentials are unavailable",
                safe_message="钉钉应用凭据不可用",
                error_code="dingtalk_connector_credentials_unavailable",
            )
        return DingTalkAccessTokenClient(
            client_id=client_id,
            client_secret=client_secret,
            timeout_seconds=5,
        )

    def _search_users(
        self, principal: ResolvedDingTalkPrincipal, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        return DingTalkContactsClient(
            self.token_client(principal), transport=self.transport
        ).search_users(
            query=str(arguments["query"]),
            offset=int(arguments.get("offset", 0)),
            page_size=int(arguments.get("page_size", 20)),
            exact_match=bool(arguments.get("exact_match", False)),
        )

    def _get_user(
        self, principal: ResolvedDingTalkPrincipal, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        return DingTalkContactsClient(
            self.token_client(principal), transport=self.transport
        ).get_user(
            user_id=str(arguments["user_id"]),
            language=str(arguments.get("language") or "zh_CN"),
        )

    def _list_department_users(
        self, principal: ResolvedDingTalkPrincipal, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        return DingTalkContactsClient(
            self.token_client(principal), transport=self.transport
        ).list_department_users(department_id=int(arguments["department_id"]))

    def _search_departments(
        self, principal: ResolvedDingTalkPrincipal, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        return DingTalkDepartmentClient(
            self.token_client(principal), transport=self.transport
        ).search(
            query=str(arguments["query"]),
            offset=int(arguments.get("offset", 0)),
            page_size=int(arguments.get("page_size", 20)),
        )

    def _get_department(
        self, principal: ResolvedDingTalkPrincipal, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        return DingTalkDepartmentClient(self.token_client(principal), transport=self.transport).get(
            department_id=int(arguments["department_id"]),
            language=str(arguments.get("language") or "zh_CN"),
        )

    def _list_sub_departments(
        self, principal: ResolvedDingTalkPrincipal, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        return DingTalkDepartmentClient(
            self.token_client(principal), transport=self.transport
        ).list_sub_departments(
            parent_department_id=int(arguments.get("parent_department_id", 1)),
            language=str(arguments.get("language") or "zh_CN"),
        )

    def _list_todos(
        self, principal: ResolvedDingTalkPrincipal, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        return DingTalkTodoReadClient(
            self.token_client(principal), transport=self.transport
        ).list_for_self(
            union_id=principal.target_union_id,
            cursor=str(arguments.get("cursor") or ""),
            is_done=(bool(arguments["is_done"]) if "is_done" in arguments else None),
            role_types=[str(value) for value in arguments.get("role_types") or []],
        )

    def _get_calendar_event(
        self, principal: ResolvedDingTalkPrincipal, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        return DingTalkCalendarReadClient(
            self.token_client(principal), transport=self.transport
        ).get_event(
            union_id=principal.target_union_id,
            event_id=str(arguments["event_id"]),
            max_attendees=int(arguments.get("max_attendees", 20)),
        )

    def _list_calendar_events(
        self, principal: ResolvedDingTalkPrincipal, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        time_min = datetime.fromisoformat(str(arguments["time_min"]).replace("Z", "+00:00"))
        time_max = datetime.fromisoformat(str(arguments["time_max"]).replace("Z", "+00:00"))
        if time_max <= time_min or (time_max - time_min).total_seconds() > 31 * 24 * 60 * 60:
            raise NonRetryableExecutionError(
                "DingTalk calendar range exceeds the fixed boundary",
                safe_message="日程查询时间范围必须为正且不超过 31 天",
                error_code="dingtalk_calendar_range_invalid",
            )
        return DingTalkCalendarReadClient(
            self.token_client(principal), transport=self.transport
        ).list_events(
            union_id=principal.target_union_id,
            time_min=str(arguments["time_min"]),
            time_max=str(arguments["time_max"]),
            page_size=int(arguments.get("page_size", 20)),
            cursor=str(arguments.get("cursor") or ""),
            max_attendees=int(arguments.get("max_attendees", 20)),
        )

    def _list_calendar_attendees(
        self, principal: ResolvedDingTalkPrincipal, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        return DingTalkCalendarReadClient(
            self.token_client(principal), transport=self.transport
        ).list_attendees(
            union_id=principal.target_union_id,
            event_id=str(arguments["event_id"]),
            page_size=int(arguments.get("page_size", 20)),
            cursor=str(arguments.get("cursor") or ""),
        )

    def _search_aitables(
        self, principal: ResolvedDingTalkPrincipal, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        return DingTalkAiTableReadClient(
            self.token_client(principal), transport=self.transport
        ).search(
            operator_id=principal.aitable_operator_id,
            query=str(arguments["query"]),
            page_size=int(arguments.get("page_size", 20)),
            cursor=str(arguments.get("cursor") or ""),
        )

    def _list_aitable_sheets(
        self, principal: ResolvedDingTalkPrincipal, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        return DingTalkAiTableReadClient(
            self.token_client(principal), transport=self.transport
        ).list_sheets(
            operator_id=principal.aitable_operator_id,
            base_id=str(arguments["base_id"]),
        )

    def _get_aitable_sheet(
        self, principal: ResolvedDingTalkPrincipal, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        return DingTalkAiTableReadClient(
            self.token_client(principal), transport=self.transport
        ).get_sheet(
            operator_id=principal.aitable_operator_id,
            base_id=str(arguments["base_id"]),
            sheet_id=str(arguments["sheet_id"]),
        )

    def _list_aitable_fields(
        self, principal: ResolvedDingTalkPrincipal, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        return DingTalkAiTableReadClient(
            self.token_client(principal), transport=self.transport
        ).list_fields(
            operator_id=principal.aitable_operator_id,
            base_id=str(arguments["base_id"]),
            sheet_id=str(arguments["sheet_id"]),
        )

    def _list_aitable_records(
        self, principal: ResolvedDingTalkPrincipal, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        return DingTalkAiTableReadClient(
            self.token_client(principal), transport=self.transport
        ).list_records(
            operator_id=principal.aitable_operator_id,
            base_id=str(arguments["base_id"]),
            sheet_id=str(arguments["sheet_id"]),
            page_size=int(arguments.get("page_size", 100)),
            cursor=str(arguments.get("cursor") or ""),
        )

    def _get_aitable_record(
        self, principal: ResolvedDingTalkPrincipal, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        return DingTalkAiTableReadClient(
            self.token_client(principal), transport=self.transport
        ).get_record(
            operator_id=principal.aitable_operator_id,
            base_id=str(arguments["base_id"]),
            sheet_id=str(arguments["sheet_id"]),
            record_id=str(arguments["record_id"]),
        )

    @staticmethod
    def _get_aitable_supported_search_filters(
        principal: ResolvedDingTalkPrincipal,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        del principal, arguments
        return notable_reference(NOTABLE_SUPPORTED_SEARCH_FILTERS)

    @staticmethod
    def _get_aitable_supported_field_info(
        principal: ResolvedDingTalkPrincipal,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        del principal, arguments
        return notable_reference(NOTABLE_SUPPORTED_FIELD_INFO)

    @staticmethod
    def _get_aitable_record_values_format(
        principal: ResolvedDingTalkPrincipal,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        del principal, arguments
        return notable_reference(NOTABLE_RECORD_VALUES_FORMAT)

    def _require_notice_task(
        self,
        principal: ResolvedDingTalkPrincipal,
        task_id: int,
    ) -> int:
        if principal.work_notification_agent_id is None:
            raise NonRetryableExecutionError(
                "DingTalk work notification Agent ID is unavailable",
                safe_message="当前钉钉应用未配置工作通知 Agent ID",
                error_code="dingtalk_work_notification_not_ready",
            )
        owned = self.runtime.database.execute_one(
            """
            select id from external_action_intent
             where actor_user_id = ? and dingtalk_enterprise_id = ?
               and source_connector_id = ?
               and tool_identifier = 'dingtalk_send_work_notification'
               and status = 'SUCCEEDED' and provider_request_id = ?
             limit 1
            """,
            (
                principal.actor_user_id,
                principal.dingtalk_enterprise_id,
                principal.source_connector_id,
                str(task_id),
            ),
        )
        if owned is None:
            raise NonRetryableExecutionError(
                "DingTalk work notification task is not available to current actor",
                safe_message="工作通知任务不可用",
                error_code="dingtalk_work_notification_task_unavailable",
            )
        return principal.work_notification_agent_id

    def _get_notice_progress(
        self, principal: ResolvedDingTalkPrincipal, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        task_id = int(arguments["task_id"])
        agent_id = self._require_notice_task(principal, task_id)
        return DingTalkWorkNotificationReadClient(
            self.token_client(principal), transport=self.transport
        ).get_progress(agent_id=agent_id, task_id=task_id)

    def _get_notice_result(
        self, principal: ResolvedDingTalkPrincipal, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        task_id = int(arguments["task_id"])
        agent_id = self._require_notice_task(principal, task_id)
        return DingTalkWorkNotificationReadClient(
            self.token_client(principal), transport=self.transport
        ).get_result(agent_id=agent_id, task_id=task_id)


def build_read_tools(
    runtime: Container,
    resolver: DingTalkPrincipalResolver,
    audit: McpAuditCoordinator,
    *,
    transport: DingTalkJsonTransport | None = None,
) -> tuple[DingTalkReadToolService, ...]:
    executors = DingTalkReadExecutorCatalog(runtime, transport=transport)
    return tuple(
        DingTalkReadToolService(
            DINGTALK_TOOL_CONTRACTS[identifier],
            resolver,
            audit,
            executors.require(identifier),
        )
        for identifier in DINGTALK_READ_TOOL_IDENTIFIERS
    )
