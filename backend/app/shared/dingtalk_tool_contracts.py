from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, Mapping

from app.shared.mcp_server_policy import DINGTALK_MCP_SERVER_CODE, mcp_invoke_scope


DINGTALK_CREATE_TODO_TOOL_IDENTIFIER: Final = "dingtalk_create_todo"
DINGTALK_BATCH_SEND_MESSAGE_TO_USERS_TOOL_IDENTIFIER: Final = (
    "dingtalk_batch_send_message_to_users_by_robot"
)
DINGTALK_SEND_MESSAGE_TO_GROUP_TOOL_IDENTIFIER: Final = (
    "dingtalk_send_message_to_group_by_robot"
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
    "dingtalk_get_aitable_supported_search_filters",
    "dingtalk_get_aitable_supported_field_info",
    "dingtalk_get_aitable_record_values_format",
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
    "dingtalk_create_aitable_sheet",
    "dingtalk_update_aitable_sheet",
    "dingtalk_create_aitable_field",
    "dingtalk_update_aitable_field",
    "dingtalk_insert_aitable_records",
    "dingtalk_update_aitable_records",
    DINGTALK_SEND_MESSAGE_TO_GROUP_TOOL_IDENTIFIER,
    DINGTALK_BATCH_SEND_MESSAGE_TO_USERS_TOOL_IDENTIFIER,
    "dingtalk_send_work_notification",
)

DINGTALK_EXCLUDED_TOOL_IDENTIFIERS: Final = (
    "dingtalk_delete_todo",
    "dingtalk_update_todo_executor_status",
    "dingtalk_delete_calendar_event",
    "dingtalk_add_calendar_attendees",
    "dingtalk_remove_calendar_attendees",
    "dingtalk_delete_aitable_sheet",
    "dingtalk_delete_aitable_field",
    "dingtalk_delete_aitable_records",
    "dingtalk_recall_robot_message",
    "dingtalk_send_robot_message",
    "dingtalk_send_custom_robot_message",
    "dingtalk_send_ding",
    "dingtalk_recall_work_notification",
    "dingtalk_raw_api_request",
)

DINGTALK_OFFICIAL_TOOL_NAMES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "dingtalk_search_users": "searchUser",
        "dingtalk_get_user": "getUserDetailByUserId",
        "dingtalk_list_department_users": "getDepartmentUsersByDepId",
        "dingtalk_search_departments": "searchDepartment",
        "dingtalk_get_department": "getDepartmentDetail",
        "dingtalk_list_sub_departments": "listSubDepartments",
        "dingtalk_list_todos": "queryTasks",
        "dingtalk_create_todo": "createTask",
        "dingtalk_update_todo": "updateTask",
        "dingtalk_complete_todo": "updateExecutorsTaskStatus",
        "dingtalk_get_calendar_event": "getEvent",
        "dingtalk_list_calendar_events": "getCalendarView",
        "dingtalk_list_calendar_attendees": "getAttendees",
        "dingtalk_create_calendar_event": "createEvent",
        "dingtalk_update_calendar_event": "updateEvent",
        "dingtalk_search_aitables": "queryNotables",
        "dingtalk_get_aitable_supported_search_filters": "notableSupportedSearchFilters",
        "dingtalk_get_aitable_supported_field_info": "notableSupportedFieldInfo",
        "dingtalk_get_aitable_record_values_format": "notableRecordValuesFormat",
        "dingtalk_list_aitable_sheets": "getNotableAllSheets",
        "dingtalk_get_aitable_sheet": "getNotableSheet",
        "dingtalk_list_aitable_fields": "getNotableAllFields",
        "dingtalk_list_aitable_records": "listNotableRecords",
        "dingtalk_get_aitable_record": "getNotableRecord",
        "dingtalk_create_aitable_sheet": "createNotableSheet",
        "dingtalk_update_aitable_sheet": "updateNotableSheetName",
        "dingtalk_create_aitable_field": "createNotableField",
        "dingtalk_update_aitable_field": "updateNotableField",
        "dingtalk_insert_aitable_records": "insertNotableRecords",
        "dingtalk_update_aitable_records": "updateNotableRecords",
        DINGTALK_SEND_MESSAGE_TO_GROUP_TOOL_IDENTIFIER: "sendMessageToGroupByRobot",
        DINGTALK_BATCH_SEND_MESSAGE_TO_USERS_TOOL_IDENTIFIER: (
            "batchSendMessageToUsersByRobot"
        ),
        "dingtalk_send_work_notification": "sendNotice",
        "dingtalk_get_work_notification_progress": "getSendProgress",
        "dingtalk_get_work_notification_result": "getSendResult",
    }
)

DINGTALK_OFFICIAL_PROFILE_TOOL_CLASSIFICATION: Final[
    Mapping[str, Mapping[str, tuple[str, ...]]]
] = MappingProxyType(
    {
        "dingtalk-contacts": MappingProxyType(
            {
                "registered": (
                    "searchUser",
                    "getUserDetailByUserId",
                    "getDepartmentUsersByDepId",
                ),
                "excluded": (
                    "getUserIdByMobile",
                    "getUserIdByUnionId",
                ),
                "resource": ("currentDateTime",),
            }
        ),
        "dingtalk-department": MappingProxyType(
            {
                "registered": (
                    "getDepartmentDetail",
                    "searchDepartment",
                    "listSubDepartments",
                ),
                "excluded": (
                    "listSubDepartmentIds",
                    "getDepartmentParents",
                    "getUserDepartmentParents",
                ),
                "resource": (),
            }
        ),
        "dingtalk-notable": MappingProxyType(
            {
                "registered": (
                    "notableSupportedSearchFilters",
                    "notableSupportedFieldInfo",
                    "notableRecordValuesFormat",
                    "queryNotables",
                    "getNotableSheet",
                    "getNotableAllSheets",
                    "listNotableRecords",
                    "getNotableRecord",
                    "insertNotableRecords",
                    "updateNotableRecords",
                    "getNotableAllFields",
                    "updateNotableSheetName",
                    "createNotableSheet",
                    "createNotableField",
                    "updateNotableField",
                ),
                "excluded": (
                    "deleteNotableSheet",
                    "deleteNotableRecords",
                    "deleteNotableField",
                ),
                "resource": (),
            }
        ),
        "dingtalk-calendar": MappingProxyType(
            {
                "registered": (
                    "createEvent",
                    "updateEvent",
                    "getEvent",
                    "getAttendees",
                    "getCalendarView",
                ),
                "excluded": ("deleteEvent", "addAttendee", "removeAttendee"),
                "resource": (),
            }
        ),
        "dingtalk-tasks": MappingProxyType(
            {
                "registered": (
                    "queryTasks",
                    "createTask",
                    "updateTask",
                    "updateExecutorsTaskStatus",
                ),
                "excluded": ("deleteTask",),
                "resource": (),
            }
        ),
        "dingtalk-robot-send-message": MappingProxyType(
            {
                "registered": (
                    "sendMessageToGroupByRobot",
                    "batchSendMessageToUsersByRobot",
                ),
                "excluded": (
                    "recallGroupMessageByRobot",
                    "batchRecallToUsersMessageByRobot",
                    "sendMessageToGroupByCustomRobot",
                ),
                "resource": (),
            }
        ),
        "dingtalk-notice": MappingProxyType(
            {
                "registered": ("sendNotice", "getSendResult", "getSendProgress"),
                "excluded": ("recallNotice",),
                "resource": (),
            }
        ),
    }
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
        return str(mcp_invoke_scope(DINGTALK_MCP_SERVER_CODE, self.identifier))

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
        # Fixed official reference Tools read bundled content only.
        return self.effect == "read" and self.target_policy != "static_official_reference"

    @property
    def requires_target_union_id(self) -> bool:
        # Directory reads use the application-visible enterprise scope, bundled
        # notable references perform no Provider I/O, and work-notification
        # history is anchored by the current actor/enterprise/Connector Intent.
        # None of those Provider contracts accepts the actor's unionId. Unknown
        # and future target policies remain fail-closed by requiring it.
        return self.target_policy not in {
            "enterprise_directory_visible_scope",
            "static_official_reference",
            "current_user_work_notification_history",
        }


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
        "name": {"type": "string", "minLength": 1, "maxLength": 200},
        "job_number": {"type": "string", "maxLength": 200},
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
        "name": {"type": "string", "minLength": 1, "maxLength": 200},
        "parent_department_id": {"type": "integer", "minimum": 0},
        "member_count": {"type": "integer", "minimum": 0},
        "auto_add_user": {"type": "boolean"},
        "create_group": {"type": "boolean"},
    },
    required=("department_id", "name"),
)

_DEPARTMENT_SEARCH_ITEM: Final[dict[str, Any]] = _object(
    {"department_id": _DEPARTMENT_ID},
    required=("department_id",),
)

_TODO_ITEM: Final[dict[str, Any]] = _object(
    {
        "task_id": _identifier(),
        "subject": {"type": "string", "minLength": 1, "maxLength": 200},
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
        "title": {"type": "string", "minLength": 1, "maxLength": 500},
        "description": {"type": "string", "maxLength": 4000},
        "start_time": {"type": "string", "minLength": 1, "maxLength": 64},
        "end_time": {"type": "string", "minLength": 1, "maxLength": 64},
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
        "name": {"type": "string", "minLength": 1, "maxLength": 300},
        "creator_user_id": _identifier(),
        "updated_at": {"type": "string", "maxLength": 64},
    },
    required=("base_id", "name"),
)

_SHEET_ITEM: Final[dict[str, Any]] = _object(
    {
        "sheet_id": _identifier(),
        "name": {"type": "string", "minLength": 1, "maxLength": 300},
    },
    required=("sheet_id", "name"),
)

_FIELD_ITEM: Final[dict[str, Any]] = _object(
    {
        "field_id": _identifier(),
        "name": {"type": "string", "minLength": 1, "maxLength": 300},
        "field_type": {"type": "string", "minLength": 1, "maxLength": 64},
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
        {
            "type": "array",
            "maxItems": 20,
            "items": {
                "oneOf": [
                    _FIELD_PRIMITIVE,
                    {
                        "type": "object",
                        "maxProperties": 20,
                        "propertyNames": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 128,
                        },
                        "additionalProperties": _FIELD_PRIMITIVE,
                    },
                ]
            },
        },
        {
            "type": "object",
            "maxProperties": 20,
            "propertyNames": {"type": "string", "minLength": 1, "maxLength": 128},
            "additionalProperties": {
                "oneOf": [
                    _FIELD_PRIMITIVE,
                    {"type": "array", "maxItems": 20, "items": _FIELD_PRIMITIVE},
                ]
            },
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
_READ_FIELDS: Final[dict[str, Any]] = {
    "type": "object",
    "maxProperties": 50,
    "propertyNames": {"type": "string", "minLength": 1, "maxLength": 128},
    "additionalProperties": _FIELD_VALUE,
}
_FIELD_PROPERTY_SCALAR: Final[dict[str, Any]] = {
    "type": ["string", "number", "integer", "boolean", "null"],
    "maxLength": 1000,
}
_FIELD_PROPERTY_OBJECT: Final[dict[str, Any]] = {
    "type": "object",
    "maxProperties": 20,
    "propertyNames": {"type": "string", "minLength": 1, "maxLength": 128},
    "additionalProperties": _FIELD_PROPERTY_SCALAR,
}
_FIELD_PROPERTY_VALUE: Final[dict[str, Any]] = {
    "oneOf": [
        _FIELD_PROPERTY_SCALAR,
        {
            "type": "array",
            "maxItems": 50,
            "items": {"oneOf": [_FIELD_PROPERTY_SCALAR, _FIELD_PROPERTY_OBJECT]},
        },
        {
            "type": "object",
            "maxProperties": 20,
            "propertyNames": {"type": "string", "minLength": 1, "maxLength": 128},
            "additionalProperties": {
                "oneOf": [
                    _FIELD_PROPERTY_SCALAR,
                    {"type": "array", "maxItems": 50, "items": _FIELD_PROPERTY_SCALAR},
                ]
            },
        },
    ]
}
_FIELD_PROPERTY: Final[dict[str, Any]] = {
    "type": "object",
    "maxProperties": 20,
    "propertyNames": {"type": "string", "minLength": 1, "maxLength": 128},
    "additionalProperties": _FIELD_PROPERTY_VALUE,
}
_AITABLE_FIELD_TYPE: Final[dict[str, Any]] = {
    "type": "string",
    "enum": [
        "text",
        "number",
        "singleSelect",
        "multipleSelect",
        "date",
        "user",
        "department",
        "attachment",
        "unidirectionalLink",
        "bidirectionalLink",
        "url",
    ],
}
_FIELD_DEFINITION: Final[dict[str, Any]] = _object(
    {
        "name": {"type": "string", "minLength": 1, "maxLength": 300},
        "type": _AITABLE_FIELD_TYPE,
        "property": _FIELD_PROPERTY,
    },
    required=("name", "type"),
)
_AITABLE_REFERENCE_OUTPUT: Final[dict[str, Any]] = _object(
    {
        "content": {"type": "string", "minLength": 1, "maxLength": 16_000},
        "source_version": {"const": "dingtalk-mcp@1.1.21"},
        "trusted_reference": {"const": True},
    },
    required=("content", "source_version", "trusted_reference"),
)
_RECORD_ITEM: Final[dict[str, Any]] = _object(
    {
        "record_id": _identifier(),
        "fields": _READ_FIELDS,
        "created_at": {"type": "string", "maxLength": 64},
        "updated_at": {"type": "string", "maxLength": 64},
    },
    required=("record_id", "fields"),
)

_NOTICE_PROGRESS_ITEM: Final[dict[str, Any]] = _object(
    {
        "task_id": {"type": "integer", "minimum": 1},
        "status": {"type": "integer", "enum": [0, 1, 2]},
        "progress_percent": {"type": "integer", "minimum": 0, "maximum": 100},
    },
    required=("task_id", "status", "progress_percent"),
)

_NOTICE_RESULT_ITEM: Final[dict[str, Any]] = _object(
    {
        "task_id": {"type": "integer", "minimum": 1},
        "invalid_user_ids": {"type": "array", "maxItems": 50, "items": _identifier()},
        "invalid_user_count": {"type": "integer", "minimum": 0},
        "forbidden_user_ids": {"type": "array", "maxItems": 50, "items": _identifier()},
        "forbidden_user_count": {"type": "integer", "minimum": 0},
        "failed_user_ids": {"type": "array", "maxItems": 50, "items": _identifier()},
        "failed_user_count": {"type": "integer", "minimum": 0},
        "read_user_ids": {"type": "array", "maxItems": 50, "items": _identifier()},
        "read_user_count": {"type": "integer", "minimum": 0},
        "unread_user_ids": {"type": "array", "maxItems": 50, "items": _identifier()},
        "unread_user_count": {"type": "integer", "minimum": 0},
        "invalid_department_ids": {
            "type": "array",
            "maxItems": 50,
            "items": _DEPARTMENT_ID,
        },
        "invalid_department_count": {"type": "integer", "minimum": 0},
        "truncated": {"type": "boolean"},
    },
    required=(
        "task_id",
        "invalid_user_ids",
        "invalid_user_count",
        "forbidden_user_ids",
        "forbidden_user_count",
        "failed_user_ids",
        "failed_user_count",
        "read_user_ids",
        "read_user_count",
        "unread_user_ids",
        "unread_user_count",
        "invalid_department_ids",
        "invalid_department_count",
        "truncated",
    ),
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
    "all_day": {
        "type": "boolean",
        "description": "全天日程为 true 时，start_time 与 end_time 的日期部分分别作为开始日期和排他结束日期，结束日期必须晚于开始日期。",
    },
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
            "官方功能：根据用户姓名、姓名拼音或英文名称搜索钉钉通讯录用户的 user_id。"
            "平台治理：仅查询当前企业"
            "应用可见范围并返回工作字段白名单。搜索命中可能只包含稳定 user_id；需要核实"
            "姓名、职务或部门时，必须对本次返回的"
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
            "官方功能：根据 user_id 查询钉钉通讯录用户信息，用于获取 user_id、union_id、"
            "姓名和工号等详细信息。平台治理：使用最新批量用户查询接口执行单用户查询，"
            "仅返回当前企业应用可见范围内的工作字段白名单，不返回手机号、头像或邮箱。"
            "用于核实 dingtalk_search_users 本次返回的候选；调用时只需原样传入 user_id，"
            "不得传入手机号、union_id 或历史候选。"
        ),
        _object({"user_id": _identifier()}, required=("user_id",)),
        _item_output("user", _USER_ITEM),
        operation_code="dingtalk.contact.user.get",
        target_policy="enterprise_directory_visible_scope",
        provider_profile="dingtalk-contacts",
    )
)
_add(
    _read_contract(
        "dingtalk_list_department_users",
        "官方功能：获取指定部门下所有成员的 user_id。平台治理：仅限当前企业应用可见部门并返回有界结果。",
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
        "官方功能：根据部门名称或拼音搜索部门 ID。平台治理：仅限当前企业应用可见范围并返回有界结果。",
        _object(
            {
                "query": {"type": "string", "minLength": 1, "maxLength": 100},
                "offset": {"type": "integer", "minimum": 0, "maximum": 10_000},
                "page_size": _PAGE_SIZE_50,
            },
            required=("query",),
        ),
        _list_output("departments", _DEPARTMENT_SEARCH_ITEM, maximum=50),
        operation_code="dingtalk.department.search",
        target_policy="enterprise_directory_visible_scope",
        provider_profile="dingtalk-department",
    )
)
_add(
    _read_contract(
        "dingtalk_get_department",
        (
            "官方功能：获取指定部门的详细信息，包括部门名称、父部门、管理员和权限设置等。"
            "平台治理：仅返回当前企业应用可见范围内的部门 ID、名称、父部门、成员数量和"
            "自动入群设置白名单，不向模型返回管理员或权限设置。"
        ),
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
        "官方功能：获取指定部门的下一级子部门基础信息。平台治理：仅限当前企业应用可见范围并返回有界结果。",
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
        "官方功能：查询钉钉待办/任务列表。平台治理：主体由当前 Job 服务端解析，仅返回当前用户本人的有界列表。",
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
        (
            "官方功能：创建钉钉待办。平台治理：只为当前 Job 服务端解析的用户本人准备"
            "待办；当前 Tool 支持标题、描述和截止时间，不接受任意执行人或参与人，原用户"
            "在确认卡片同意后才会创建。"
        ),
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
        (
            "官方功能：更新钉钉待办。平台治理：只更新当前用户本人的待办；当前 Tool 只"
            "更新标题、描述和截止时间，不修改执行人、参与人或完成状态；完成待办应使用"
            " dingtalk_complete_todo，原用户确认后才会执行。"
        ),
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
        (
            "官方功能：更新执行人的待办完成状态。平台治理：只把当前用户本人作为执行人的"
            "指定待办标记为完成，不支持替其他执行人更新或重新打开已完成待办，原用户确认"
            "后才会执行。"
        ),
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
        (
            "官方功能：查询单个钉钉日程的详细信息。平台治理：只读取当前用户主日历中的"
            "指定日程，并仅返回日程字段白名单：ID、标题、描述、起止时间、全天状态和地点；"
            "参与者应另行调用 dingtalk_list_calendar_attendees。"
        ),
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
        (
            "官方功能：查询钉钉日程视图，按时间范围获取日程列表。平台治理：只查询当前用户"
            "主日历，时间范围不超过 31 天并返回有界的日程字段白名单；需要完整参与者列表时"
            "应对明确 event_id 调用 dingtalk_list_calendar_attendees。"
        ),
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
        "官方功能：获取钉钉日程参与者列表。平台治理：只读取当前用户主日历中的指定日程并返回有界结果。",
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
        (
            "官方功能：创建一个新的钉钉日程，官方能力支持设置时间、地点、参与者、提醒和"
            "重复规则等。平台治理：当前 Tool 只允许在当前用户主日历中设置标题、描述、"
            "起止时间、时区、全天状态和地点；不支持参与者、提醒或重复规则，原用户确认后"
            "才会执行。"
        ),
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
        (
            "官方功能：修改已存在的钉钉日程。平台治理：只更新当前用户主日历中的日程；"
            "当前 Tool 只支持标题、描述、起止时间、时区、全天状态和地点，不修改参与者、"
            "提醒或重复规则，原用户确认后才会执行。"
        ),
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
        (
            "官方功能：根据名称查询 AI 表格/多维表。平台治理：operator 由当前 Job 服务端"
            "解析；当前 Tool 只接受名称关键词，不接受模型指定创建者过滤条件，仅返回当前"
            "用户可访问的有界结果。"
        ),
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
        "dingtalk_get_aitable_supported_search_filters",
        "官方功能：返回 AI 表格/多维表支持的搜索过滤条件。平台治理：返回固定官方"
        " dingtalk-mcp@1.1.21 本地参考，不访问外部 Provider，也不接受模型参数。",
        _object({}),
        _AITABLE_REFERENCE_OUTPUT,
        operation_code="dingtalk.aitable.reference.search_filters.get",
        target_policy="static_official_reference",
        provider_profile="dingtalk-notable",
    )
)
_add(
    _read_contract(
        "dingtalk_get_aitable_supported_field_info",
        "官方功能：返回 AI 表格/多维表支持的字段类型和额外属性。平台治理：返回固定官方"
        " dingtalk-mcp@1.1.21 本地参考，不访问外部 Provider，也不接受模型参数。",
        _object({}),
        _AITABLE_REFERENCE_OUTPUT,
        operation_code="dingtalk.aitable.reference.field_info.get",
        target_policy="static_official_reference",
        provider_profile="dingtalk-notable",
    )
)
_add(
    _read_contract(
        "dingtalk_get_aitable_record_values_format",
        "官方功能：返回 AI 表格/多维表记录值格式。平台治理：返回固定官方"
        " dingtalk-mcp@1.1.21 本地参考，不访问外部 Provider，也不接受模型参数。",
        _object({}),
        _AITABLE_REFERENCE_OUTPUT,
        operation_code="dingtalk.aitable.reference.record_values_format.get",
        target_policy="static_official_reference",
        provider_profile="dingtalk-notable",
    )
)
_add(
    _read_contract(
        "dingtalk_list_aitable_sheets",
        "官方功能：获取 AI 表格/多维表的所有数据表。平台治理：仅接受明确 base_id，"
        "Provider 使用企业应用 Access Token，并由服务端注入当前 Job operator，按官方"
        " notable v1 契约返回有界结果。",
        _object({"base_id": _identifier()}, required=("base_id",)),
        _list_output("sheets", _SHEET_ITEM, maximum=50),
        operation_code="dingtalk.aitable.sheet.list",
        target_policy="explicit_aitable_resource_for_current_operator",
        provider_profile="dingtalk-notable",
    )
)
_add(
    _read_contract(
        "dingtalk_get_aitable_sheet",
        "官方功能：获取 AI 表格/多维表中单个数据表的 ID 和名称。平台治理：仅接受明确"
        " base_id 和 sheet_id；Provider 使用企业应用 Access Token，并由服务端注入当前"
        " Job operator，按官方 notable v1 契约访问。",
        _object(
            {"base_id": _identifier(), "sheet_id": _identifier()}, required=("base_id", "sheet_id")
        ),
        _item_output("sheet", _SHEET_ITEM),
        operation_code="dingtalk.aitable.sheet.get",
        target_policy="explicit_aitable_resource_for_current_operator",
        provider_profile="dingtalk-notable",
    )
)
_add(
    _read_contract(
        "dingtalk_list_aitable_fields",
        "官方功能：获取 AI 表格/多维表中指定数据表的所有字段。平台治理：仅接受明确"
        " base_id 和 sheet_id；Provider 使用企业应用 Access Token，并由服务端注入当前"
        " Job operator，按官方 notable v1 契约返回有界结果。",
        _object(
            {"base_id": _identifier(), "sheet_id": _identifier()}, required=("base_id", "sheet_id")
        ),
        _list_output("fields", _FIELD_ITEM, maximum=50),
        operation_code="dingtalk.aitable.field.list",
        target_policy="explicit_aitable_resource_for_current_operator",
        provider_profile="dingtalk-notable",
    )
)
_add(
    _read_contract(
        "dingtalk_list_aitable_records",
        "官方功能：获取 AI 表格/多维表中指定数据表的多行记录。平台治理：仅接受明确"
        " base_id 和 sheet_id；Provider 使用企业应用 Access Token，并由服务端注入当前"
        " Job operator，使用官方 notable v1 分页接口返回有界结果；当前 Tool 不接受字段"
        "过滤条件。",
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
        target_policy="explicit_aitable_resource_for_current_operator",
        provider_profile="dingtalk-notable",
    )
)
_add(
    _read_contract(
        "dingtalk_get_aitable_record",
        "官方功能：获取 AI 表格/多维表中指定数据表的单行记录。平台治理：仅接受明确"
        " base_id、sheet_id 和 record_id；Provider 使用企业应用 Access Token，并由服务端"
        "注入当前 Job operator，按官方 notable v1 契约访问。",
        _object(
            {"base_id": _identifier(), "sheet_id": _identifier(), "record_id": _identifier()},
            required=("base_id", "sheet_id", "record_id"),
        ),
        _item_output("record", _RECORD_ITEM),
        operation_code="dingtalk.aitable.record.get",
        target_policy="explicit_aitable_resource_for_current_operator",
        provider_profile="dingtalk-notable",
    )
)
_add(
    _mutation_contract(
        "dingtalk_create_aitable_sheet",
        "官方功能：在 AI 表格/多维表中创建数据表，可同时创建字段。平台治理：仅接受明确"
        " base_id、名称和有界字段定义；Provider 使用企业应用 Access Token，并由服务端"
        "注入当前 Job operator，原用户确认后才执行，不支持删除。",
        _object(
            {
                "base_id": _identifier(),
                "name": {"type": "string", "minLength": 1, "maxLength": 300},
                "fields": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 50,
                    "items": _FIELD_DEFINITION,
                },
            },
            required=("base_id", "name"),
        ),
        _confirmation_output(
            "创建钉钉 AI 表格数据表",
            {
                "base_id": _identifier(),
                "name": {"type": "string", "maxLength": 300},
                "field_names": {
                    "type": "array",
                    "maxItems": 50,
                    "items": {"type": "string", "maxLength": 300},
                },
            },
            summary_required=("base_id", "name", "field_names"),
        ),
        operation_code="dingtalk.aitable.sheet.create",
        target_policy="explicit_aitable_resource_for_current_operator",
        provider_profile="dingtalk-notable",
    )
)
_add(
    _mutation_contract(
        "dingtalk_update_aitable_sheet",
        "官方功能：更新 AI 表格/多维表中单个数据表的名称。平台治理：仅接受明确 base_id、"
        "sheet_id 和新名称；Provider 使用企业应用 Access Token，并由服务端注入当前 Job"
        " operator，原用户确认后才执行，不支持删除。",
        _object(
            {
                "base_id": _identifier(),
                "sheet_id": _identifier(),
                "name": {"type": "string", "minLength": 1, "maxLength": 300},
            },
            required=("base_id", "sheet_id", "name"),
        ),
        _confirmation_output(
            "更新钉钉 AI 表格数据表名称",
            {
                "base_id": _identifier(),
                "sheet_id": _identifier(),
                "name": {"type": "string", "maxLength": 300},
            },
            summary_required=("base_id", "sheet_id", "name"),
        ),
        operation_code="dingtalk.aitable.sheet.update",
        target_policy="explicit_aitable_resource_for_current_operator",
        provider_profile="dingtalk-notable",
    )
)
_add(
    _mutation_contract(
        "dingtalk_create_aitable_field",
        "官方功能：在 AI 表格/多维表指定数据表中创建字段。平台治理：仅接受明确 base_id、"
        "sheet_id、字段名、官方字段类型和有界属性；Provider 使用企业应用 Access Token，"
        "并由服务端注入当前 Job operator，原用户确认后才执行，不支持删除。",
        _object(
            {
                "base_id": _identifier(),
                "sheet_id": _identifier(),
                "name": {"type": "string", "minLength": 1, "maxLength": 300},
                "type": _AITABLE_FIELD_TYPE,
                "property": _FIELD_PROPERTY,
            },
            required=("base_id", "sheet_id", "name", "type"),
        ),
        _confirmation_output(
            "创建钉钉 AI 表格字段",
            {
                "base_id": _identifier(),
                "sheet_id": _identifier(),
                "name": {"type": "string", "maxLength": 300},
                "field_type": _AITABLE_FIELD_TYPE,
            },
            summary_required=("base_id", "sheet_id", "name", "field_type"),
        ),
        operation_code="dingtalk.aitable.field.create",
        target_policy="explicit_aitable_resource_for_current_operator",
        provider_profile="dingtalk-notable",
    )
)
_add(
    _mutation_contract(
        "dingtalk_update_aitable_field",
        "官方功能：更新 AI 表格/多维表指定数据表中的字段。平台治理：仅接受明确 base_id、"
        "sheet_id、field_id、新名称和可选有界属性；Provider 使用企业应用 Access Token，"
        "并由服务端注入当前 Job operator，原用户确认后才执行，不支持删除。",
        _object(
            {
                "base_id": _identifier(),
                "sheet_id": _identifier(),
                "field_id": _identifier(),
                "name": {"type": "string", "minLength": 1, "maxLength": 300},
                "property": _FIELD_PROPERTY,
            },
            required=("base_id", "sheet_id", "field_id", "name"),
        ),
        _confirmation_output(
            "更新钉钉 AI 表格字段",
            {
                "base_id": _identifier(),
                "sheet_id": _identifier(),
                "field_id": _identifier(),
                "name": {"type": "string", "maxLength": 300},
            },
            summary_required=("base_id", "sheet_id", "field_id", "name"),
        ),
        operation_code="dingtalk.aitable.field.update",
        target_policy="explicit_aitable_resource_for_current_operator",
        provider_profile="dingtalk-notable",
    )
)
_add(
    _mutation_contract(
        "dingtalk_insert_aitable_records",
        "官方功能：在 AI 表格/多维表的指定数据表中新增行记录。平台治理：仅接受明确"
        " base_id 和 sheet_id；Provider 使用企业应用 Access Token，并由服务端注入当前"
        " Job operator 预检，且有界记录由原用户确认后才会写入。",
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
        target_policy="explicit_aitable_resource_for_current_operator",
        provider_profile="dingtalk-notable",
    )
)
_add(
    _mutation_contract(
        "dingtalk_update_aitable_records",
        "官方功能：更新 AI 表格/多维表指定数据表中的多行记录。平台治理：仅接受明确"
        " base_id 和 sheet_id；Provider 使用企业应用 Access Token，并由服务端注入当前"
        " Job operator 预检，且有界记录由原用户确认后才会写入。",
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
        target_policy="explicit_aitable_resource_for_current_operator",
        provider_profile="dingtalk-notable",
    )
)
_add(
    _mutation_contract(
        DINGTALK_BATCH_SEND_MESSAGE_TO_USERS_TOOL_IDENTIFIER,
        (
            "官方功能：使用企业机器人向一个或多个个人用户发送普通消息，适用于一对一单聊，"
            "不能用于群聊。平台治理：当前 Tool 只发送由标题和正文组成的 markdown 普通消息，"
            "仅接受明确 user_id，原用户确认后才会执行。按姓名发送时必须先调用"
            " dingtalk_search_users，并对本次候选调用本 Job 已授权的 dingtalk_get_user"
            " 核实；请求"
            "明确要求全部匹配者时，把全部已核实 user_id 放入同一批，单数目标仍有多个候选时"
            "必须让用户选择。不得复用历史 Job 的授权结论，也不得改用工作通知或当前来源会话"
            "消息。Provider 返回的"
            " processQueryKey 只表示发送请求已受理；最终送达必须以钉钉事实为准。"
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
        DINGTALK_SEND_MESSAGE_TO_GROUP_TOOL_IDENTIFIER,
        (
            "官方功能：使用企业机器人向群聊发送普通消息（非 DING、非待办）。"
            "平台治理：当前 Tool 只发送由标题和正文组成的 markdown 普通消息，且只允许当前"
            " Job 的受信钉钉来源群，由服务端解析群会话和机器人 Code；私聊或按 user_id"
            "发送必须使用"
            " dingtalk_batch_send_message_to_users_by_robot。原用户确认后才会执行；Provider"
            " 返回的 processQueryKey 只表示发送请求已受理，不能宣称消息已最终送达。"
        ),
        _object(
            {
                "title": {"type": "string", "minLength": 1, "maxLength": 200},
                "text": {"type": "string", "minLength": 1, "maxLength": 3000},
            },
            required=("title", "text"),
        ),
        _confirmation_output(
            "向当前钉钉来源群发送机器人消息",
            {
                "target": {"type": "string", "maxLength": 200},
                "title": {"type": "string", "maxLength": 200},
                "text": {"type": "string", "maxLength": 3000},
            },
            summary_required=("target", "title", "text"),
        ),
        operation_code="dingtalk.robot.group_message.send",
        target_policy="current_source_group",
        provider_profile="dingtalk-robot-send-message",
    )
)
_add(
    _mutation_contract(
        "dingtalk_send_work_notification",
        (
            "官方功能：发送钉钉工作通知消息，支持 markdown 消息类型。平台治理：当前版本只向当前用户本人发送"
            " markdown 工作通知，原用户确认后才会执行；返回 task_id 只表示异步发送任务"
            "已提交，最终结果应调用发送进度和发送结果 Tool 查询。"
        ),
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
        "官方功能：获取工作通知消息的发送进度，实时查询消息发送进度。平台治理：只查询当前用户通过平台发送给本人的工作通知。",
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
        "官方功能：获取工作通知消息的发送结果，查询消息发送状态和统计信息。平台治理：只查询当前用户通过平台发送给本人的工作通知。",
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
    if set(selected) != expected or len(selected) != 35:
        raise ValueError("DingTalk MCP Tool catalog must contain the governed official profiles")
    if set(selected) != set(DINGTALK_OFFICIAL_TOOL_NAMES):
        raise ValueError("DingTalk MCP Tool catalog must map every Tool to one official capability")
    if len(set(DINGTALK_OFFICIAL_TOOL_NAMES.values())) != len(DINGTALK_OFFICIAL_TOOL_NAMES):
        raise ValueError("DingTalk official Tool mapping must be one-to-one")
    classified_registered: set[str] = set()
    classified_all: set[str] = set()
    for profile, categories in DINGTALK_OFFICIAL_PROFILE_TOOL_CLASSIFICATION.items():
        if set(categories) != {"registered", "excluded", "resource"}:
            raise ValueError(f"DingTalk official profile classification is invalid: {profile}")
        for category, names in categories.items():
            if len(set(names)) != len(names) or classified_all.intersection(names):
                raise ValueError("DingTalk official Tool classification contains duplicates")
            classified_all.update(names)
            if category == "registered":
                classified_registered.update(names)
    if classified_registered != set(DINGTALK_OFFICIAL_TOOL_NAMES.values()):
        raise ValueError("DingTalk registered Tool mapping does not match official profiles")
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
