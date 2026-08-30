from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.bootstrap import Container
from app.modules.external_action.domain import normalize_todo_arguments
from app.modules.external_action.service import ExternalActionService
from app.modules.mcp_audit import McpAuditCoordinator
from app.shared.dingtalk_tool_contracts import (
    DINGTALK_MUTATION_TOOL_IDENTIFIERS,
    DINGTALK_TOOL_CONTRACTS,
)
from app.shared.exceptions import NonRetryableExecutionError
from app.shared.tool_contract import canonical_json
from services.dingtalk_mcp_server.auth.principal import (
    DingTalkPrincipalResolver,
    ResolvedDingTalkPrincipal,
)
from services.dingtalk_mcp_server.provider import DingTalkAiTableReadClient, DingTalkJsonTransport
from services.dingtalk_mcp_server.tools.mutation_tool import (
    DingTalkMutationToolService,
    MutationNormalizer,
    MutationPreflight,
)
from services.dingtalk_mcp_server.tools.read_catalog import DingTalkReadExecutorCatalog


class DingTalkMutationPreparationCatalog:
    def __init__(
        self,
        runtime: Container,
        *,
        transport: DingTalkJsonTransport | None = None,
    ) -> None:
        self.runtime = runtime
        self.transport = transport
        self.read_executors = DingTalkReadExecutorCatalog(runtime, transport=transport)
        self._normalizers: dict[str, MutationNormalizer] = {
            "dingtalk_create_todo": self._create_todo,
            "dingtalk_update_todo": self._update_todo,
            "dingtalk_complete_todo": self._complete_todo,
            "dingtalk_create_calendar_event": self._create_calendar_event,
            "dingtalk_update_calendar_event": self._update_calendar_event,
            "dingtalk_insert_aitable_records": self._insert_aitable_records,
            "dingtalk_update_aitable_records": self._update_aitable_records,
            "dingtalk_send_robot_message": self._send_robot_message,
            "dingtalk_send_work_notification": self._send_work_notification,
        }
        self._preflights: dict[str, MutationPreflight] = {
            "dingtalk_insert_aitable_records": self._preflight_aitable,
            "dingtalk_update_aitable_records": self._preflight_aitable,
        }
        if set(self._normalizers) != set(DINGTALK_MUTATION_TOOL_IDENTIFIERS):
            raise ValueError("DingTalk mutation preparation catalog is incomplete")

    def normalizer(self, identifier: str) -> MutationNormalizer:
        try:
            return self._normalizers[identifier]
        except KeyError as exc:
            raise ValueError(f"Unknown DingTalk mutation normalizer: {identifier}") from exc

    def preflight(self, identifier: str) -> MutationPreflight | None:
        return self._preflights.get(identifier)

    @staticmethod
    def _create_todo(
        principal: ResolvedDingTalkPrincipal,
        arguments: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        del principal
        normalized = normalize_todo_arguments(arguments)
        frozen = normalized.as_dict()
        return frozen, {
            "operation": "创建钉钉待办",
            "subject": normalized.subject,
            "due_time": normalized.due_time,
        }

    @staticmethod
    def _update_todo(
        principal: ResolvedDingTalkPrincipal,
        arguments: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        del principal
        task_id = str(arguments["task_id"]).strip()
        normalized = normalize_todo_arguments(
            {
                "subject": arguments["subject"],
                "description": arguments.get("description", ""),
                **({"due_time": arguments["due_time"]} if arguments.get("due_time") else {}),
            }
        )
        frozen = {"task_id": task_id, **normalized.as_dict()}
        return frozen, {
            "operation": "更新钉钉待办",
            "task_id": task_id,
            "subject": normalized.subject,
            "due_time": normalized.due_time,
        }

    @staticmethod
    def _complete_todo(
        principal: ResolvedDingTalkPrincipal,
        arguments: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        del principal
        task_id = str(arguments["task_id"]).strip()
        subject = " ".join(str(arguments["subject"]).strip().split())
        return {"task_id": task_id, "subject": subject, "done": True}, {
            "operation": "完成钉钉待办",
            "task_id": task_id,
            "subject": subject,
        }

    @staticmethod
    def _create_calendar_event(
        principal: ResolvedDingTalkPrincipal,
        arguments: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        values = _calendar_values(arguments, require_time_range=True)
        frozen = {
            **values,
            "_target": {
                "union_id": principal.target_union_id,
                "calendar_id": principal.primary_calendar_id,
            },
        }
        return frozen, {
            "operation": "创建钉钉日程",
            "title": str(values["title"]),
            "start_time": str(values["start_time"]),
            "end_time": str(values["end_time"]),
            "time_zone": str(values["time_zone"]),
        }

    @staticmethod
    def _update_calendar_event(
        principal: ResolvedDingTalkPrincipal,
        arguments: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        event_id = str(arguments["event_id"]).strip()
        values = _calendar_values(arguments, require_time_range=False)
        frozen = {
            "event_id": event_id,
            **values,
            "_target": {
                "union_id": principal.target_union_id,
                "calendar_id": principal.primary_calendar_id,
            },
        }
        start = str(values.get("start_time") or "")
        end = str(values.get("end_time") or "")
        return frozen, {
            "operation": "更新钉钉日程",
            "event_id": event_id,
            "title": str(values.get("title") or "标题不变"),
            "time_range": f"{start} - {end}" if start and end else "时间不变",
        }

    @staticmethod
    def _insert_aitable_records(
        principal: ResolvedDingTalkPrincipal,
        arguments: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        frozen = _frozen_aitable_arguments(principal, arguments)
        return frozen, _aitable_summary("新增钉钉 AI 表格记录", frozen)

    @staticmethod
    def _update_aitable_records(
        principal: ResolvedDingTalkPrincipal,
        arguments: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        frozen = _frozen_aitable_arguments(principal, arguments)
        return frozen, _aitable_summary("更新钉钉 AI 表格记录", frozen)

    @staticmethod
    def _send_robot_message(
        principal: ResolvedDingTalkPrincipal,
        arguments: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if not principal.source_robot_code:
            raise _not_ready("当前来源 Connector 未配置企业机器人 Code")
        if principal.source_conversation_type == "group":
            if not principal.source_open_conversation_id:
                raise _not_ready("当前来源群缺少 openConversationId")
            target = {
                "conversation_type": "group",
                "open_conversation_id": principal.source_open_conversation_id,
                "robot_code": principal.source_robot_code,
            }
            target_name = "当前群聊"
        else:
            target = {
                "conversation_type": "direct",
                "staff_id": principal.target_external_subject_id,
                "robot_code": principal.source_robot_code,
            }
            target_name = "当前用户本人"
        title = str(arguments["title"]).strip()
        text = str(arguments["text"]).strip()
        return {"title": title, "text": text, "_target": target}, {
            "operation": "发送钉钉机器人消息",
            "target": target_name,
            "title": title,
            "text": text,
        }

    @staticmethod
    def _send_work_notification(
        principal: ResolvedDingTalkPrincipal,
        arguments: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if principal.work_notification_agent_id is None:
            raise _not_ready("当前来源 Connector 未配置工作通知 Agent ID")
        title = str(arguments["title"]).strip()
        text = str(arguments["text"]).strip()
        return {
            "title": title,
            "text": text,
            "_target": {
                "agent_id": principal.work_notification_agent_id,
                "staff_id": principal.target_external_subject_id,
            },
        }, {
            "operation": "发送本人钉钉工作通知",
            "target": "当前用户本人",
            "title": title,
            "text": text,
        }

    def _preflight_aitable(
        self,
        principal: ResolvedDingTalkPrincipal,
        arguments: dict[str, Any],
    ) -> None:
        target = arguments.get("_target")
        if not isinstance(target, dict):
            raise _not_ready("AI 表格目标事实缺失")
        DingTalkAiTableReadClient(
            self.read_executors.token_client(principal),
            transport=self.transport,
        ).get_sheet(
            operator_id=str(target["operator_id"]),
            base_id=str(arguments["base_id"]),
            sheet_id=str(arguments["sheet_id"]),
        )


def _calendar_values(
    arguments: dict[str, Any],
    *,
    require_time_range: bool,
) -> dict[str, Any]:
    values = {
        key: (str(value).strip() if isinstance(value, str) else value)
        for key, value in arguments.items()
        if key != "event_id"
    }
    start = str(values.get("start_time") or "")
    end = str(values.get("end_time") or "")
    time_zone = str(values.get("time_zone") or "")
    if require_time_range and not (start and end and time_zone):
        raise _invalid("日程起止时间和时区不能为空")
    if bool(start) != bool(end):
        raise _invalid("日程开始和结束时间必须同时提供")
    if (start or end) and not time_zone:
        raise _invalid("修改日程时间时必须提供时区")
    if time_zone:
        try:
            ZoneInfo(time_zone)
        except ZoneInfoNotFoundError as exc:
            raise _invalid("日程时区无效") from exc
    if start and end:
        parsed_start = datetime.fromisoformat(start.replace("Z", "+00:00"))
        parsed_end = datetime.fromisoformat(end.replace("Z", "+00:00"))
        if parsed_start.tzinfo is None or parsed_end.tzinfo is None or parsed_end <= parsed_start:
            raise _invalid("日程结束时间必须晚于开始时间且都包含时区")
        values["start_time"] = parsed_start.isoformat()
        values["end_time"] = parsed_end.isoformat()
    return values


def _frozen_aitable_arguments(
    principal: ResolvedDingTalkPrincipal,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    # Canonical JSON round-trip removes caller-owned mutable references while
    # preserving the already schema-bounded record values.
    parsed = json.loads(canonical_json(arguments))
    if not isinstance(parsed, dict):
        raise _invalid("AI 表格参数必须为对象")
    copied: dict[str, Any] = dict(parsed)
    copied["_target"] = {"operator_id": principal.aitable_operator_id}
    return copied


def _aitable_summary(operation: str, frozen: dict[str, Any]) -> dict[str, Any]:
    field_names = sorted(
        {
            str(field)[:128]
            for record in frozen.get("records") or []
            if isinstance(record, dict)
            for field in (record.get("fields") or {})
        }
    )[:50]
    return {
        "operation": operation,
        "base_id": str(frozen["base_id"]),
        "sheet_id": str(frozen["sheet_id"]),
        "record_count": len(frozen.get("records") or []),
        "field_names": field_names,
    }


def _invalid(message: str) -> NonRetryableExecutionError:
    return NonRetryableExecutionError(
        message,
        safe_message=message,
        error_code="external_action_arguments_invalid",
    )


def _not_ready(message: str) -> NonRetryableExecutionError:
    return NonRetryableExecutionError(
        message,
        safe_message=message,
        error_code="dingtalk_mutation_not_ready",
    )


def build_mutation_tools(
    runtime: Container,
    resolver: DingTalkPrincipalResolver,
    external_actions: ExternalActionService,
    audit: McpAuditCoordinator,
    *,
    transport: DingTalkJsonTransport | None = None,
) -> tuple[DingTalkMutationToolService, ...]:
    preparations = DingTalkMutationPreparationCatalog(runtime, transport=transport)
    return tuple(
        DingTalkMutationToolService(
            DINGTALK_TOOL_CONTRACTS[identifier],
            resolver,
            external_actions,
            audit,
            preparations.normalizer(identifier),
            preflight=preparations.preflight(identifier),
        )
        for identifier in DINGTALK_MUTATION_TOOL_IDENTIFIERS
    )
