from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, Mapping

from app.shared.mcp_server_policy import DINGTALK_MCP_SERVER_CODE, mcp_invoke_scope


DINGTALK_CREATE_TODO_TOOL_IDENTIFIER: Final = "dingtalk_create_todo"
DINGTALK_BATCH_SEND_MESSAGE_TO_USERS_TOOL_IDENTIFIER: Final = (
    "dingtalk_batch_send_message_to_users_by_robot"
)
DINGTALK_CONFIRMATION_POLICY: Final = "external_action_card_v1"
DINGTALK_NO_CONFIRMATION_POLICY: Final = "none"
DINGTALK_ID_PATTERN: Final = r"^[A-Za-z0-9._:@-]+$"
DINGTALK_TIME_ZONE_PATTERN: Final = r"^[A-Za-z_]+(?:/[A-Za-z0-9_+.-]+)+$"

DINGTALK_READ_TOOL_IDENTIFIERS: Final = (
    "dingtalk_search_users",
    "dingtalk_get_user",
    "dingtalk_list_department_users",
    "dingtalk_search_departments",
    "dingtalk_get_department",
    "dingtalk_list_sub_departments",
    "dingtalk_list_todos",
    "dingtalk_get_calendar_event",
    "dingtalk_list_calendar_events",
    "dingtalk_list_calendar_attendees",
    "dingtalk_search_aitables",
    "dingtalk_list_aitable_sheets",
    "dingtalk_get_aitable_sheet",
    "dingtalk_list_aitable_fields",
    "dingtalk_list_aitable_records",
    "dingtalk_get_aitable_record",
    "dingtalk_get_work_notification_progress",
    "dingtalk_get_work_notification_result",
)

DINGTALK_MUTATION_TOOL_IDENTIFIERS: Final = (
    DINGTALK_CREATE_TODO_TOOL_IDENTIFIER,
    "dingtalk_update_todo",
    "dingtalk_complete_todo",
    "dingtalk_create_calendar_event",
    "dingtalk_update_calendar_event",
    "dingtalk_insert_aitable_records",
    "dingtalk_update_aitable_records",
    "dingtalk_send_robot_message",
    DINGTALK_BATCH_SEND_MESSAGE_TO_USERS_TOOL_IDENTIFIER,
    "dingtalk_send_work_notification",
)

DINGTALK_EXCLUDED_TOOL_IDENTIFIERS: Final = (
    "dingtalk_delete_todo",
    "dingtalk_update_todo_executor_status",
    "dingtalk_delete_calendar_event",
    "dingtalk_add_calendar_attendees",
    "dingtalk_remove_calendar_attendees",
    "dingtalk_create_aitable_sheet",
    "dingtalk_update_aitable_sheet",
    "dingtalk_delete_aitable_sheet",
    "dingtalk_create_aitable_field",
    "dingtalk_update_aitable_field",
    "dingtalk_delete_aitable_field",
    "dingtalk_delete_aitable_records",
    "dingtalk_recall_robot_message",
    "dingtalk_send_custom_robot_message",
    "dingtalk_send_ding",
    "dingtalk_recall_work_notification",
    "dingtalk_raw_api_request",
)


@dataclass(frozen=True, slots=True)
class DingTalkToolContract:
    identifier: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    effect: str
    confirmation_policy: str
    operation_code: str
    risk_level: str
    target_policy: str
    provider_profile: str

    @property
    def required_scope(self) -> str:
        return mcp_invoke_scope(DINGTALK_MCP_SERVER_CODE, self.identifier)

    @property
    def read_only(self) -> bool:
        return self.effect == "read"

    @property
    def destructive(self) -> bool:
        return self.effect == "mutation"

    @property
    def idempotent(self) -> bool:
        # Read calls are naturally idempotent. Mutation Tool calls only prepare
        # a hash-deduplicated Action Intent; they never perform the Provider write.
        return True

    @property
    def open_world(self) -> bool:
        # Read calls contact DingTalk during the Tool invocation. Mutation calls
        # only persist an intent and defer Provider I/O until card confirmation.
        return self.effect == "read"


def _object(
    properties: dict[str, Any],
    *,
    required: tuple[str, ...] = (),
    any_of_required: tuple[str, ...] = (),
    max_properties: int | None = None,
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = list(required)
    if any_of_required:
        schema["anyOf"] = [{"required": [name]} for name in any_of_required]
    if max_properties is not None:
        schema["maxProperties"] = max_properties
    return schema


def _identifier(*, maximum: int = 512) -> dict[str, Any]:
    return {
        "type": "string",
        "minLength": 1,
        "maxLength": maximum,
        "pattern": DINGTALK_ID_PATTERN,
    }


def _cursor() -> dict[str, Any]:
    return {"type": "string", "maxLength": 512}


def _date_time() -> dict[str, Any]:
    return {"type": "string", "format": "date-time", "maxLength": 64}


def _time_zone() -> dict[str, Any]:
    return {
        "type": "string",
        "minLength": 3,
        "maxLength": 64,
        "pattern": DINGTALK_TIME_ZONE_PATTERN,
    }


def _list_output(field: str, item: dict[str, Any], *, maximum: int) -> dict[str, Any]:
    return _object(
        {
            field: {"type": "array", "maxItems": maximum, "items": item},
            "returned": {"type": "integer", "minimum": 0, "maximum": maximum},
            "truncated": {"type": "boolean"},
            "next_cursor": _cursor(),
            "untrusted_data": {"const": True},
        },
        required=(field, "returned", "truncated", "untrusted_data"),
    )


def _item_output(field: str, item: dict[str, Any]) -> dict[str, Any]:
    return _object(
        {field: item, "untrusted_data": {"const": True}},
        required=(field, "untrusted_data"),
    )


def _confirmation_output(
    operation: str,
    summary_properties: dict[str, Any],
    *,
    summary_required: tuple[str, ...],
) -> dict[str, Any]:
    return _object(
        {
            "status": {"const": "confirmation_required"},
            "action_intent_id": _identifier(maximum=128),
            "revision": {"type": "integer", "minimum": 1},
            "expires_at": _date_time(),
            "summary": _object(
                {"operation": {"const": operation}, **summary_properties},
                required=("operation", *summary_required),
            ),
        },
        required=("status", "action_intent_id", "revision", "expires_at", "summary"),
    )


_LANGUAGE: Final[dict[str, Any]] = {"type": "string", "enum": ["zh_CN", "en_US"]}
_PAGE_SIZE_50: Final[dict[str, Any]] = {"type": "integer", "minimum": 1, "maximum": 50}
_PAGE_SIZE_100: Final[dict[str, Any]] = {"type": "integer", "minimum": 1, "maximum": 100}
_DEPARTMENT_ID: Final[dict[str, Any]] = {"type": "integer", "minimum": 1}

_USER_ITEM: Final[dict[str, Any]] = _object(
    {
        "user_id": _identifier(),
        "union_id": _identifier(),
        "name": {"type": "string", "maxLength": 200},
        "title": {"type": "string", "maxLength": 200},
        "department_ids": {"type": "array", "maxItems": 50, "items": _DEPARTMENT_ID},
        "active": {"type": "boolean"},
        "admin": {"type": "boolean"},
    },
    required=("user_id",),
)

_DEPARTMENT_ITEM: Final[dict[str, Any]] = _object(
    {
        "department_id": _DEPARTMENT_ID,
        "name": {"type": "string", "maxLength": 200},
        "parent_department_id": {"type": "integer", "minimum": 0},
        "member_count": {"type": "integer", "minimum": 0},
        "auto_add_user": {"type": "boolean"},
        "create_group": {"type": "boolean"},
    },
    required=("department_id", "name"),
)

_TODO_ITEM: Final[dict[str, Any]] = _object(
    {
        "task_id": _identifier(),
        "subject": {"type": "string", "maxLength": 200},
        "description": {"type": "string", "maxLength": 2000},
        "due_time": {"type": "string", "maxLength": 64},
        "done": {"type": "boolean"},
        "role": {"type": "string", "enum": ["executor", "creator", "participant"]},
        "created_at": {"type": "string", "maxLength": 64},
        "updated_at": {"type": "string", "maxLength": 64},
    },
    required=("task_id", "subject", "done"),
)

_CALENDAR_EVENT_ITEM: Final[dict[str, Any]] = _object(
    {
        "event_id": _identifier(),
        "title": {"type": "string", "maxLength": 500},
        "description": {"type": "string", "maxLength": 4000},
        "start_time": {"type": "string", "maxLength": 64},
        "end_time": {"type": "string", "maxLength": 64},
        "time_zone": {"type": "string", "maxLength": 64},
        "all_day": {"type": "boolean"},
        "location": {"type": "string", "maxLength": 500},
        "status": {"type": "string", "maxLength": 64},
        "attendee_count": {"type": "integer", "minimum": 0},
    },
    required=("event_id", "title", "start_time", "end_time"),
)

_ATTENDEE_ITEM: Final[dict[str, Any]] = _object(
    {
        "union_id": _identifier(),
        "name": {"type": "string", "maxLength": 200},
        "response_status": {"type": "string", "maxLength": 64},
        "optional": {"type": "boolean"},
    },
    required=("union_id",),
)

_AITABLE_ITEM: Final[dict[str, Any]] = _object(
    {
        "base_id": _identifier(),
        "name": {"type": "string", "maxLength": 300},
        "creator_user_id": _identifier(),
        "updated_at": {"type": "string", "maxLength": 64},
    },
    required=("base_id", "name"),
)

_SHEET_ITEM: Final[dict[str, Any]] = _object(
    {"sheet_id": _identifier(), "name": {"type": "string", "maxLength": 300}},
    required=("sheet_id", "name"),
)

_FIELD_ITEM: Final[dict[str, Any]] = _object(
    {
        "field_id": _identifier(),
        "name": {"type": "string", "maxLength": 300},
        "field_type": {"type": "string", "maxLength": 64},
        "primary": {"type": "boolean"},
    },
    required=("field_id", "name", "field_type"),
)

_FIELD_PRIMITIVE: Final[dict[str, Any]] = {
    "type": ["string", "number", "integer", "boolean", "null"],
    "maxLength": 2000,
}
_FIELD_VALUE: Final[dict[str, Any]] = {
    "oneOf": [
        _FIELD_PRIMITIVE,
        {"type": "array", "maxItems": 20, "items": _FIELD_PRIMITIVE},
        {
            "type": "object",
            "maxProperties": 20,
            "propertyNames": {"type": "string", "minLength": 1, "maxLength": 128},
            "additionalProperties": _FIELD_PRIMITIVE,
        },
    ]
}
_FIELDS: Final[dict[str, Any]] = {
    "type": "object",
    "minProperties": 1,
    "maxProperties": 50,
    "propertyNames": {"type": "string", "minLength": 1, "maxLength": 128},
    "additionalProperties": _FIELD_VALUE,
}
_RECORD_ITEM: Final[dict[str, Any]] = _object(
    {
        "record_id": _identifier(),
        "fields": _FIELDS,
        "created_at": {"type": "string", "maxLength": 64},
        "updated_at": {"type": "string", "maxLength": 64},
    },
    required=("record_id", "fields"),
)

_NOTICE_PROGRESS_ITEM: Final[dict[str, Any]] = _object(
    {
        "task_id": {"type": "integer", "minimum": 1},
        "status": {"type": "string", "maxLength": 64},
        "progress": {"type": "integer", "minimum": 0, "maximum": 100},
        "sent_count": {"type": "integer", "minimum": 0},
        "failed_count": {"type": "integer", "minimum": 0},
    },
    required=("task_id", "status"),
)

_NOTICE_RESULT_ITEM: Final[dict[str, Any]] = _object(
    {
        "task_id": {"type": "integer", "minimum": 1},
        "status": {"type": "string", "maxLength": 64},
        "sent_count": {"type": "integer", "minimum": 0},
        "failed_count": {"type": "integer", "minimum": 0},
        "invalid_user_ids": {"type": "array", "maxItems": 50, "items": _identifier()},
    },
    required=("task_id", "status"),
)


def _read_contract(
    identifier: str,
    description: str,
    input_schema: dict[str, Any],
    output_schema: dict[str, Any],
    *,
    operation_code: str,
    target_policy: str,
    provider_profile: str,
) -> DingTalkToolContract:
    return DingTalkToolContract(
        identifier=identifier,
        description=description,
        input_schema=input_schema,
        output_schema=output_schema,
        effect="read",
        confirmation_policy=DINGTALK_NO_CONFIRMATION_POLICY,
        operation_code=operation_code,
        risk_level="low",
        target_policy=target_policy,
        provider_profile=provider_profile,
    )


def _mutation_contract(
    identifier: str,
    description: str,
    input_schema: dict[str, Any],
    output_schema: dict[str, Any],
    *,
    operation_code: str,
    target_policy: str,
    provider_profile: str,
) -> DingTalkToolContract:
    return DingTalkToolContract(
        identifier=identifier,
        description=description,
        input_schema=input_schema,
        output_schema=output_schema,
        effect="mutation",
        confirmation_policy=DINGTALK_CONFIRMATION_POLICY,
        operation_code=operation_code,
        risk_level="medium",
        target_policy=target_policy,
        provider_profile=provider_profile,
    )


_CREATE_TODO_INPUT: Final[dict[str, Any]] = _object(
    {
        "subject": {"type": "string", "minLength": 1, "maxLength": 200},
        "description": {"type": "string", "maxLength": 2000},
        "due_time": _date_time(),
    },
    required=("subject",),
)

_CREATE_TODO_OUTPUT: Final[dict[str, Any]] = _confirmation_output(
    "创建钉钉待办",
    {
        "subject": {"type": "string", "maxLength": 200},
        "due_time": {"type": "string", "maxLength": 64},
    },
    summary_required=("subject", "due_time"),
)

_CALENDAR_MUTATION_FIELDS: Final[dict[str, Any]] = {
    "title": {"type": "string", "minLength": 1, "maxLength": 500},
    "description": {"type": "string", "maxLength": 4000},
    "start_time": _date_time(),
    "end_time": _date_time(),
    "time_zone": _time_zone(),
    "all_day": {"type": "boolean"},
    "location": {"type": "string", "maxLength": 500},
}


_contracts: dict[str, DingTalkToolContract] = {}


def _add(contract: DingTalkToolContract) -> None:
    if contract.identifier in _contracts:
        raise ValueError(f"Duplicate DingTalk MCP Tool: {contract.identifier}")
    _contracts[contract.identifier] = contract


_add(
    _read_contract(
        "dingtalk_search_users",
        (
            "在当前钉钉企业应用可见范围内按名称搜索用户，只返回工作字段白名单。"
            "搜索命中可能只包含稳定 user_id；需要核实姓名、职务或部门时，必须对本次返回的"
            "每个候选继续调用 dingtalk_get_user，不得用历史轮次的授权结果替代当前调用。"
        ),
        _object(
            {
                "query": {"type": "string", "minLength": 1, "maxLength": 100},
                "offset": {"type": "integer", "minimum": 0, "maximum": 10_000},
                "page_size": _PAGE_SIZE_50,
                "exact_match": {"type": "boolean"},
            },
            required=("query",),
        ),
        _list_output("users", _USER_ITEM, maximum=50),
        operation_code="dingtalk.contact.user.search",
        target_policy="enterprise_directory_visible_scope",
        provider_profile="dingtalk-contacts",
    )
)
_add(
    _read_contract(
        "dingtalk_get_user",
        (
            "读取当前钉钉企业应用可见范围内指定稳定 user_id 的工作信息，不返回手机号或邮箱。"
            "用于核实 dingtalk_search_users 本次返回的候选；调用时只需原样传入 user_id，"
            "language 可省略并默认使用 zh_CN。"
        ),
        _object({"user_id": _identifier(), "language": _LANGUAGE}, required=("user_id",)),
        _item_output("user", _USER_ITEM),
        operation_code="dingtalk.contact.user.get",
        target_policy="enterprise_directory_visible_scope",
        provider_profile="dingtalk-contacts",
    )
)
_add(
    _read_contract(
        "dingtalk_list_department_users",
        "列出当前钉钉企业应用可见部门中的用户 ID。",
        _object({"department_id": _DEPARTMENT_ID}, required=("department_id",)),
        _list_output("users", _USER_ITEM, maximum=50),
        operation_code="dingtalk.contact.department_users.list",
        target_policy="enterprise_directory_visible_scope",
        provider_profile="dingtalk-contacts",
    )
)
_add(
    _read_contract(
        "dingtalk_search_departments",
        "在当前钉钉企业应用可见范围内搜索部门。",
        _object(
            {
                "query": {"type": "string", "minLength": 1, "maxLength": 100},
                "offset": {"type": "integer", "minimum": 0, "maximum": 10_000},
                "page_size": _PAGE_SIZE_50,
            },
            required=("query",),
        ),
        _list_output("departments", _DEPARTMENT_ITEM, maximum=50),
        operation_code="dingtalk.department.search",
        target_policy="enterprise_directory_visible_scope",
        provider_profile="dingtalk-department",
    )
)
_add(
    _read_contract(
        "dingtalk_get_department",
        "读取当前钉钉企业应用可见范围内的部门详情。",
        _object(
            {"department_id": _DEPARTMENT_ID, "language": _LANGUAGE},
            required=("department_id",),
        ),
        _item_output("department", _DEPARTMENT_ITEM),
        operation_code="dingtalk.department.get",
        target_policy="enterprise_directory_visible_scope",
        provider_profile="dingtalk-department",
    )
)
_add(
    _read_contract(
        "dingtalk_list_sub_departments",
        "列出当前钉钉企业应用可见范围内的下一级子部门。",
        _object({"parent_department_id": _DEPARTMENT_ID, "language": _LANGUAGE}),
        _list_output("departments", _DEPARTMENT_ITEM, maximum=50),
        operation_code="dingtalk.department.children.list",
        target_policy="enterprise_directory_visible_scope",
        provider_profile="dingtalk-department",
    )
)
_add(
    _read_contract(
        "dingtalk_list_todos",
        "查询当前钉钉用户本人的有界待办列表。",
        _object(
            {
                "cursor": _cursor(),
                "is_done": {"type": "boolean"},
                "role_types": {
                    "type": "array",
                    "maxItems": 3,
                    "uniqueItems": True,
                    "items": {"type": "string", "enum": ["executor", "creator", "participant"]},
                },
            }
        ),
        _list_output("todos", _TODO_ITEM, maximum=50),
        operation_code="dingtalk.todo.list",
        target_policy="current_user_todo",
        provider_profile="dingtalk-tasks",
    )
)
_add(
    _mutation_contract(
        DINGTALK_CREATE_TODO_TOOL_IDENTIFIER,
        "为当前钉钉用户准备一个本人待办。此操作不会立即执行；必须由原用户在确认卡片中同意后才会创建。",
        _CREATE_TODO_INPUT,
        _CREATE_TODO_OUTPUT,
        operation_code="dingtalk.todo.create",
        target_policy="current_user_todo",
        provider_profile="dingtalk-tasks",
    )
)
_add(
    _mutation_contract(
        "dingtalk_update_todo",
        "准备更新当前钉钉用户本人的待办，原用户确认后才会执行。",
        _object(
            {
                "task_id": _identifier(),
                "subject": {"type": "string", "minLength": 1, "maxLength": 200},
                "description": {"type": "string", "maxLength": 2000},
                "due_time": _date_time(),
            },
            required=("task_id", "subject"),
        ),
        _confirmation_output(
            "更新钉钉待办",
            {
                "task_id": _identifier(),
                "subject": {"type": "string", "maxLength": 200},
                "due_time": {"type": "string", "maxLength": 64},
            },
            summary_required=("task_id", "subject", "due_time"),
        ),
        operation_code="dingtalk.todo.update",
        target_policy="current_user_todo",
        provider_profile="dingtalk-tasks",
    )
)
_add(
    _mutation_contract(
        "dingtalk_complete_todo",
        "准备把当前钉钉用户本人的待办标记为完成，原用户确认后才会执行。",
        _object(
            {
                "task_id": _identifier(),
                "subject": {"type": "string", "minLength": 1, "maxLength": 200},
            },
            required=("task_id", "subject"),
        ),
        _confirmation_output(
            "完成钉钉待办",
            {"task_id": _identifier(), "subject": {"type": "string", "maxLength": 200}},
            summary_required=("task_id", "subject"),
        ),
        operation_code="dingtalk.todo.complete",
        target_policy="current_user_todo",
        provider_profile="dingtalk-tasks",
    )
)
_add(
    _read_contract(
        "dingtalk_get_calendar_event",
        "读取当前钉钉用户主日历中的单个日程。",
        _object(
            {"event_id": _identifier(), "max_attendees": _PAGE_SIZE_50}, required=("event_id",)
        ),
        _item_output("event", _CALENDAR_EVENT_ITEM),
        operation_code="dingtalk.calendar.event.get",
        target_policy="current_user_primary_calendar",
        provider_profile="dingtalk-calendar",
    )
)
_add(
    _read_contract(
        "dingtalk_list_calendar_events",
        "查询当前钉钉用户主日历中不超过 31 天的日程列表。",
        _object(
            {
                "time_min": _date_time(),
                "time_max": _date_time(),
                "page_size": _PAGE_SIZE_50,
                "cursor": _cursor(),
                "max_attendees": _PAGE_SIZE_50,
            },
            required=("time_min", "time_max"),
        ),
        _list_output("events", _CALENDAR_EVENT_ITEM, maximum=50),
        operation_code="dingtalk.calendar.event.list",
        target_policy="current_user_primary_calendar",
        provider_profile="dingtalk-calendar",
    )
)
_add(
    _read_contract(
        "dingtalk_list_calendar_attendees",
        "列出当前钉钉用户主日历中某个日程的参与人。",
        _object(
            {"event_id": _identifier(), "page_size": _PAGE_SIZE_50, "cursor": _cursor()},
            required=("event_id",),
        ),
        _list_output("attendees", _ATTENDEE_ITEM, maximum=50),
        operation_code="dingtalk.calendar.attendee.list",
        target_policy="current_user_primary_calendar",
        provider_profile="dingtalk-calendar",
    )
)
_add(
    _mutation_contract(
        "dingtalk_create_calendar_event",
        "准备在当前钉钉用户主日历中创建日程，原用户确认后才会执行。",
        _object(
            _CALENDAR_MUTATION_FIELDS, required=("title", "start_time", "end_time", "time_zone")
        ),
        _confirmation_output(
            "创建钉钉日程",
            {
                "title": {"type": "string", "maxLength": 500},
                "start_time": {"type": "string", "maxLength": 64},
                "end_time": {"type": "string", "maxLength": 64},
                "time_zone": {"type": "string", "maxLength": 64},
            },
            summary_required=("title", "start_time", "end_time", "time_zone"),
        ),
        operation_code="dingtalk.calendar.event.create",
        target_policy="current_user_primary_calendar",
        provider_profile="dingtalk-calendar",
    )
)
_add(
    _mutation_contract(
        "dingtalk_update_calendar_event",
        "准备更新当前钉钉用户主日历中的日程，原用户确认后才会执行。",
        _object(
            {"event_id": _identifier(), **_CALENDAR_MUTATION_FIELDS},
            required=("event_id",),
            any_of_required=tuple(_CALENDAR_MUTATION_FIELDS),
        ),
        _confirmation_output(
            "更新钉钉日程",
            {
                "event_id": _identifier(),
                "title": {"type": "string", "maxLength": 500},
                "time_range": {"type": "string", "maxLength": 160},
            },
            summary_required=("event_id", "title", "time_range"),
        ),
        operation_code="dingtalk.calendar.event.update",
        target_policy="current_user_primary_calendar",
        provider_profile="dingtalk-calendar",
    )
)
_add(
    _read_contract(
        "dingtalk_search_aitables",
        "使用当前钉钉用户作为 operator 搜索可访问的 AI 表格。",
        _object(
            {
                "query": {"type": "string", "minLength": 1, "maxLength": 200},
                "page_size": _PAGE_SIZE_50,
                "cursor": _cursor(),
            },
            required=("query",),
        ),
        _list_output("aitables", _AITABLE_ITEM, maximum=50),
        operation_code="dingtalk.aitable.search",
        target_policy="current_user_aitable_operator",
        provider_profile="dingtalk-notable",
    )
)
_add(
    _read_contract(
        "dingtalk_list_aitable_sheets",
        "使用当前钉钉用户作为 operator 列出 AI 表格中的数据表。",
        _object({"base_id": _identifier()}, required=("base_id",)),
        _list_output("sheets", _SHEET_ITEM, maximum=50),
        operation_code="dingtalk.aitable.sheet.list",
        target_policy="current_user_aitable_operator",
        provider_profile="dingtalk-notable",
    )
)
_add(
    _read_contract(
        "dingtalk_get_aitable_sheet",
        "使用当前钉钉用户作为 operator 读取一个 AI 表格数据表。",
        _object(
            {"base_id": _identifier(), "sheet_id": _identifier()}, required=("base_id", "sheet_id")
        ),
        _item_output("sheet", _SHEET_ITEM),
        operation_code="dingtalk.aitable.sheet.get",
        target_policy="current_user_aitable_operator",
        provider_profile="dingtalk-notable",
    )
)
_add(
    _read_contract(
        "dingtalk_list_aitable_fields",
        "使用当前钉钉用户作为 operator 列出 AI 表格数据表字段。",
        _object(
            {"base_id": _identifier(), "sheet_id": _identifier()}, required=("base_id", "sheet_id")
        ),
        _list_output("fields", _FIELD_ITEM, maximum=50),
        operation_code="dingtalk.aitable.field.list",
        target_policy="current_user_aitable_operator",
        provider_profile="dingtalk-notable",
    )
)
_add(
    _read_contract(
        "dingtalk_list_aitable_records",
        "使用当前钉钉用户作为 operator 读取 AI 表格数据表中的有界记录。",
        _object(
            {
                "base_id": _identifier(),
                "sheet_id": _identifier(),
                "page_size": _PAGE_SIZE_100,
                "cursor": _cursor(),
            },
            required=("base_id", "sheet_id"),
        ),
        _list_output("records", _RECORD_ITEM, maximum=100),
        operation_code="dingtalk.aitable.record.list",
        target_policy="current_user_aitable_operator",
        provider_profile="dingtalk-notable",
    )
)
_add(
    _read_contract(
        "dingtalk_get_aitable_record",
        "使用当前钉钉用户作为 operator 读取 AI 表格中的单行记录。",
        _object(
            {"base_id": _identifier(), "sheet_id": _identifier(), "record_id": _identifier()},
            required=("base_id", "sheet_id", "record_id"),
        ),
        _item_output("record", _RECORD_ITEM),
        operation_code="dingtalk.aitable.record.get",
        target_policy="current_user_aitable_operator",
        provider_profile="dingtalk-notable",
    )
)
_add(
    _mutation_contract(
        "dingtalk_insert_aitable_records",
        "准备向当前用户可访问的 AI 表格新增有界记录，原用户确认后才会执行。",
        _object(
            {
                "base_id": _identifier(),
                "sheet_id": _identifier(),
                "records": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 20,
                    "items": _object({"fields": _FIELDS}, required=("fields",)),
                },
            },
            required=("base_id", "sheet_id", "records"),
        ),
        _confirmation_output(
            "新增钉钉 AI 表格记录",
            {
                "base_id": _identifier(),
                "sheet_id": _identifier(),
                "record_count": {"type": "integer", "minimum": 1, "maximum": 20},
                "field_names": {
                    "type": "array",
                    "maxItems": 50,
                    "items": {"type": "string", "maxLength": 128},
                },
            },
            summary_required=("base_id", "sheet_id", "record_count", "field_names"),
        ),
        operation_code="dingtalk.aitable.record.insert",
        target_policy="current_user_aitable_operator",
        provider_profile="dingtalk-notable",
    )
)
_add(
    _mutation_contract(
        "dingtalk_update_aitable_records",
        "准备更新当前用户可访问的 AI 表格记录，原用户确认后才会执行。",
        _object(
            {
                "base_id": _identifier(),
                "sheet_id": _identifier(),
                "records": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 20,
                    "items": _object(
                        {"record_id": _identifier(), "fields": _FIELDS},
                        required=("record_id", "fields"),
                    ),
                },
            },
            required=("base_id", "sheet_id", "records"),
        ),
        _confirmation_output(
            "更新钉钉 AI 表格记录",
            {
                "base_id": _identifier(),
                "sheet_id": _identifier(),
                "record_count": {"type": "integer", "minimum": 1, "maximum": 20},
                "field_names": {
                    "type": "array",
                    "maxItems": 50,
                    "items": {"type": "string", "maxLength": 128},
                },
            },
            summary_required=("base_id", "sheet_id", "record_count", "field_names"),
        ),
        operation_code="dingtalk.aitable.record.update",
        target_policy="current_user_aitable_operator",
        provider_profile="dingtalk-notable",
    )
)
_add(
    _mutation_contract(
        DINGTALK_BATCH_SEND_MESSAGE_TO_USERS_TOOL_IDENTIFIER,
        (
            "准备使用企业机器人向一个或多个明确 user_id 批量发送普通消息，原用户确认后"
            "才会执行。按姓名发送时，必须先调用 dingtalk_search_users；候选无法唯一识别"
            "时继续调用本 Job 中已授权的 dingtalk_get_user 并让用户选择。不得复用历史 Job"
            "的授权结论，也不得改用工作通知或当前来源会话消息。"
        ),
        _object(
            {
                "user_ids": {
                    "type": "array",
                    "minItems": 1,
                    "items": _identifier(),
                },
                "msg_param": _object(
                    {
                        "title": {"type": "string", "minLength": 1, "maxLength": 200},
                        "text": {"type": "string", "minLength": 1, "maxLength": 3000},
                    },
                    required=("title", "text"),
                ),
            },
            required=("user_ids", "msg_param"),
        ),
        _confirmation_output(
            "批量发送钉钉机器人单聊",
            {
                "recipient_count": {"type": "integer", "minimum": 1},
                "recipient_id_suffixes": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 4, "maxLength": 16},
                },
                "title": {"type": "string", "maxLength": 200},
                "text": {"type": "string", "maxLength": 3000},
            },
            summary_required=("recipient_count", "recipient_id_suffixes", "title", "text"),
        ),
        operation_code="dingtalk.robot.batch_send_message_to_users",
        target_policy="explicit_enterprise_user_ids",
        provider_profile="dingtalk-robot-send-message",
    )
)
_add(
    _mutation_contract(
        "dingtalk_send_robot_message",
        (
            "仅准备向当前钉钉来源群或当前私聊发起人发送机器人消息，原用户确认后"
            "才会执行。不支持按姓名或任意 user_id 定向发送；该场景必须使用当前 Job 中"
            "已授权的 dingtalk_batch_send_message_to_users_by_robot。"
        ),
        _object(
            {
                "title": {"type": "string", "minLength": 1, "maxLength": 200},
                "text": {"type": "string", "minLength": 1, "maxLength": 3000},
            },
            required=("title", "text"),
        ),
        _confirmation_output(
            "向当前钉钉来源会话发送机器人消息",
            {
                "target": {"type": "string", "maxLength": 200},
                "title": {"type": "string", "maxLength": 200},
                "text": {"type": "string", "maxLength": 3000},
            },
            summary_required=("target", "title", "text"),
        ),
        operation_code="dingtalk.robot.message.send",
        target_policy="current_source_conversation",
        provider_profile="dingtalk-robot-send-message",
    )
)
_add(
    _mutation_contract(
        "dingtalk_send_work_notification",
        "准备向当前钉钉用户本人发送工作通知，原用户确认后才会执行。",
        _object(
            {
                "title": {"type": "string", "minLength": 1, "maxLength": 200},
                "text": {"type": "string", "minLength": 1, "maxLength": 3000},
            },
            required=("title", "text"),
        ),
        _confirmation_output(
            "发送本人钉钉工作通知",
            {
                "target": {"const": "当前用户本人"},
                "title": {"type": "string", "maxLength": 200},
                "text": {"type": "string", "maxLength": 3000},
            },
            summary_required=("target", "title", "text"),
        ),
        operation_code="dingtalk.work_notification.send",
        target_policy="current_user_work_notification",
        provider_profile="dingtalk-notice",
    )
)
_add(
    _read_contract(
        "dingtalk_get_work_notification_progress",
        "查询当前用户通过平台发送的本人工作通知进度。",
        _object({"task_id": {"type": "integer", "minimum": 1}}, required=("task_id",)),
        _item_output("progress", _NOTICE_PROGRESS_ITEM),
        operation_code="dingtalk.work_notification.progress.get",
        target_policy="current_user_work_notification_history",
        provider_profile="dingtalk-notice",
    )
)
_add(
    _read_contract(
        "dingtalk_get_work_notification_result",
        "查询当前用户通过平台发送的本人工作通知结果。",
        _object({"task_id": {"type": "integer", "minimum": 1}}, required=("task_id",)),
        _item_output("result", _NOTICE_RESULT_ITEM),
        operation_code="dingtalk.work_notification.result.get",
        target_policy="current_user_work_notification_history",
        provider_profile="dingtalk-notice",
    )
)


DINGTALK_TOOL_CONTRACTS: Final[Mapping[str, DingTalkToolContract]] = MappingProxyType(
    dict(sorted(_contracts.items()))
)


def validate_dingtalk_tool_contracts(
    contracts: Mapping[str, DingTalkToolContract] | None = None,
) -> None:
    selected = DINGTALK_TOOL_CONTRACTS if contracts is None else contracts
    expected = set(DINGTALK_READ_TOOL_IDENTIFIERS) | set(DINGTALK_MUTATION_TOOL_IDENTIFIERS)
    if set(selected) != expected or len(selected) != 28:
        raise ValueError(
            "DingTalk MCP Tool catalog must contain Phase 2 plus the official user batch send Tool"
        )
    operations: set[str] = set()
    for identifier, contract in selected.items():
        if identifier != contract.identifier:
            raise ValueError("DingTalk MCP Tool identifier is inconsistent")
        if contract.effect not in {"read", "mutation"}:
            raise ValueError("DingTalk MCP Tool effect is invalid")
        expected_policy = (
            DINGTALK_NO_CONFIRMATION_POLICY
            if contract.effect == "read"
            else DINGTALK_CONFIRMATION_POLICY
        )
        if contract.confirmation_policy != expected_policy:
            raise ValueError("DingTalk MCP Tool confirmation policy is invalid")
        if contract.risk_level not in {"low", "medium", "high"}:
            raise ValueError("DingTalk MCP Tool risk level is invalid")
        if not contract.operation_code or contract.operation_code in operations:
            raise ValueError("DingTalk MCP Tool operation code is missing or duplicated")
        if not contract.target_policy or not contract.provider_profile:
            raise ValueError("DingTalk MCP Tool execution metadata is incomplete")
        if contract.input_schema.get("additionalProperties") is not False:
            raise ValueError("DingTalk MCP Tool input schema must be closed")
        if identifier in DINGTALK_EXCLUDED_TOOL_IDENTIFIERS:
            raise ValueError("Excluded DingTalk MCP Tool is registered")
        operations.add(contract.operation_code)


def require_dingtalk_tool_contract(identifier: str) -> DingTalkToolContract:
    try:
        return DINGTALK_TOOL_CONTRACTS[identifier]
    except KeyError as exc:
        raise KeyError(f"Unknown DingTalk MCP Tool: {identifier}") from exc


validate_dingtalk_tool_contracts()
