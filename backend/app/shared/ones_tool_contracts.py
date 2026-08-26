from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final


ONES_ID_PATTERN: Final = r"^[A-Za-z0-9_-]+$"
ONES_STATUS_CATEGORIES: Final = ("to_do", "in_progress", "done")


@dataclass(frozen=True, slots=True)
class OnesToolContract:
    identifier: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]


def _identifier(*, maximum: int = 128) -> dict[str, Any]:
    return {
        "type": "string",
        "minLength": 1,
        "maxLength": maximum,
        "pattern": ONES_ID_PATTERN,
    }


def _person() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "uuid": {"type": "string", "maxLength": 128},
            "name": {"type": "string", "maxLength": 200},
        },
        "required": ["uuid", "name"],
        "additionalProperties": False,
    }


def _status() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "uuid": {"type": "string", "maxLength": 128},
            "name": {"type": "string", "maxLength": 200},
            "category": {
                "type": "string",
                "enum": list(ONES_STATUS_CATEGORIES),
            },
        },
        "required": ["uuid", "name", "category"],
        "additionalProperties": False,
    }


def _list_output(
    field: str,
    item_schema: dict[str, Any],
    *,
    maximum: int,
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            field: {
                "type": "array",
                "maxItems": maximum,
                "items": item_schema,
            },
            "total": {"type": "integer", "minimum": 0},
            "returned": {"type": "integer", "minimum": 0, "maximum": maximum},
            "truncated": {"type": "boolean"},
            "next_cursor": {"type": "string", "maxLength": 512},
            "untrusted_data": {"const": True},
        },
        "required": [field, "total", "returned", "truncated", "untrusted_data"],
        "additionalProperties": False,
    }


PROJECT_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "uuid": {"type": "string", "maxLength": 128},
        "name": {"type": "string", "maxLength": 300},
        "archived": {"type": "boolean"},
        "sample": {"type": "boolean"},
        "owner": _person(),
        "status": _status(),
    },
    "required": ["uuid", "name", "archived", "sample"],
    "additionalProperties": False,
}

SPRINT_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "uuid": {"type": "string", "maxLength": 128},
        "name": {"type": "string", "maxLength": 300},
        "project_uuid": {"type": "string", "maxLength": 128},
        "project_name": {"type": "string", "maxLength": 300},
        "start_at": {"type": "string", "maxLength": 64},
        "end_at": {"type": "string", "maxLength": 64},
        "status": {"type": "string", "maxLength": 64},
        "progress": {"type": "integer", "minimum": 0, "maximum": 100},
    },
    "required": ["uuid", "name", "project_uuid", "status"],
    "additionalProperties": False,
}

ISSUE_TYPE_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "uuid": {"type": "string", "maxLength": 128},
        "scope_uuid": {"type": "string", "maxLength": 128},
        "name": {"type": "string", "maxLength": 200},
        "sub_issue_type": {"type": "boolean"},
    },
    "required": ["uuid", "scope_uuid", "name", "sub_issue_type"],
    "additionalProperties": False,
}

WORK_ITEM_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "uuid": {"type": "string", "maxLength": 128},
        "number": {"type": "integer"},
        "name": {"type": "string", "maxLength": 500},
        "project": {
            "type": "object",
            "properties": {
                "uuid": {"type": "string", "maxLength": 128},
                "name": {"type": "string", "maxLength": 300},
            },
            "required": ["uuid"],
            "additionalProperties": False,
        },
        "issue_type": {
            "type": "object",
            "properties": {
                "uuid": {"type": "string", "maxLength": 128},
                "name": {"type": "string", "maxLength": 200},
            },
            "required": ["uuid"],
            "additionalProperties": False,
        },
        "status": _status(),
        "owner": _person(),
        "assignee": _person(),
        "sprint": {
            "type": "object",
            "properties": {
                "uuid": {"type": "string", "maxLength": 128},
                "name": {"type": "string", "maxLength": 300},
            },
            "required": ["uuid", "name"],
            "additionalProperties": False,
        },
        "created_at": {"type": "string", "maxLength": 64},
        "updated_at": {"type": "string", "maxLength": 64},
        "subtask_count": {"type": "integer", "minimum": 0},
        "subtask_done_count": {"type": "integer", "minimum": 0},
    },
    "required": ["uuid", "number", "name", "project", "issue_type", "status"],
    "additionalProperties": False,
}

TESTCASE_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "uuid": {"type": "string", "maxLength": 128},
        "name": {"type": "string", "maxLength": 500},
        "path": {"type": "string", "maxLength": 1000},
        "library_uuid": {"type": "string", "maxLength": 128},
        "module_uuid": {"type": "string", "maxLength": 128},
        "assignee": _person(),
        "created_at": {"type": "string", "maxLength": 64},
    },
    "required": ["uuid"],
    "additionalProperties": False,
}


def _object_schema(
    properties: dict[str, Any],
    *,
    required: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


def _contract(
    identifier: str,
    description: str,
    input_schema: dict[str, Any],
    output_schema: dict[str, Any],
) -> OnesToolContract:
    return OnesToolContract(identifier, description, input_schema, output_schema)


_LEGACY_WORK_ITEM_INPUT = _object_schema(
    {
        "keyword": {"type": "string", "minLength": 1, "maxLength": 200},
        "issue_type": {"type": "string", "enum": ["demand", "task", "defect"]},
        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
    },
    required=("keyword", "issue_type", "limit"),
)

_LEGACY_WORK_ITEM_OUTPUT = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "maxItems": 50,
            "items": _object_schema(
                {
                    "number": {"type": "integer"},
                    "name": {"type": "string", "maxLength": 500},
                    "type": {"type": "string", "enum": ["demand", "task", "defect"]},
                },
                required=("number", "name", "type"),
            ),
        },
        "total": {"type": "integer", "minimum": 0},
        "truncated": {"type": "boolean"},
        "untrusted_data": {"const": True},
    },
    "required": ["items", "total", "truncated", "untrusted_data"],
    "additionalProperties": False,
}

_PROJECT_ROLE_OUTPUT = {
    "type": "object",
    "properties": {
        "roles": {
            "type": "array",
            "maxItems": 100,
            "items": _object_schema(
                {
                    "role_uuid": {"type": "string", "maxLength": 128},
                    "role_name": {"type": "string", "maxLength": 200},
                    "members": {
                        "type": "array",
                        "maxItems": 500,
                        "items": _person(),
                    },
                },
                required=("role_uuid", "role_name", "members"),
            ),
        },
        "untrusted_data": {"const": True},
    },
    "required": ["roles", "untrusted_data"],
    "additionalProperties": False,
}

_WORK_ITEM_QUERY_INPUT = _object_schema(
    {
        "keyword": {"type": "string", "maxLength": 200},
        "project_uuid": _identifier(),
        "sprint_uuid": _identifier(),
        "issue_type_uuids": {
            "type": "array",
            "maxItems": 20,
            "uniqueItems": True,
            "items": _identifier(),
        },
        "status_uuids": {
            "type": "array",
            "maxItems": 20,
            "uniqueItems": True,
            "items": _identifier(),
        },
        "status_categories": {
            "type": "array",
            "maxItems": 3,
            "uniqueItems": True,
            "items": {"type": "string", "enum": list(ONES_STATUS_CATEGORIES)},
        },
        "assignee_uuids": {
            "type": "array",
            "maxItems": 20,
            "uniqueItems": True,
            "items": _identifier(),
        },
        "created_from": {"type": "string", "format": "date-time", "maxLength": 64},
        "created_to": {"type": "string", "format": "date-time", "maxLength": 64},
        "limit": {"type": "integer", "minimum": 1, "maximum": 100},
    },
    required=("limit",),
)

_TESTCASE_DETAIL_OUTPUT = {
    "type": "object",
    "properties": {
        "test_case": TESTCASE_SCHEMA,
        "description": {"type": "string", "maxLength": 4000},
        "condition": {"type": "string", "maxLength": 2000},
        "steps": {
            "type": "array",
            "maxItems": 100,
            "items": _object_schema(
                {
                    "index": {"type": "integer", "minimum": 0},
                    "description": {"type": "string", "maxLength": 2000},
                    "expected_result": {"type": "string", "maxLength": 2000},
                },
                required=("index", "description", "expected_result"),
            ),
        },
        "untrusted_data": {"const": True},
    },
    "required": ["test_case", "steps", "untrusted_data"],
    "additionalProperties": False,
}


ONES_TOOL_CONTRACTS: Final[dict[str, OnesToolContract]] = {
    contract.identifier: contract
    for contract in (
        _contract(
            "ones_work_item_search",
            "按关键词和稳定类型查询当前用户默认 Team 的 ONES 工作项；仅用于兼容已有发布，复杂筛选请使用 ones_query_work_items。",
            _LEGACY_WORK_ITEM_INPUT,
            _LEGACY_WORK_ITEM_OUTPUT,
        ),
        _contract(
            "ones_list_project_role_members",
            "查询当前用户默认 Team 中指定项目的角色及成员姓名；只接受 project_uuid。",
            _object_schema({"project_uuid": _identifier(maximum=64)}, required=("project_uuid",)),
            _PROJECT_ROLE_OUTPUT,
        ),
        _contract(
            "ones_search_projects",
            "按名称关键词查询当前用户默认 Team 中可见的 ONES 项目，返回项目 UUID、名称和状态。",
            _object_schema(
                {
                    "keyword": {"type": "string", "maxLength": 200},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                },
                required=("keyword", "limit"),
            ),
            _list_output("projects", PROJECT_SCHEMA, maximum=100),
        ),
        _contract(
            "ones_list_project_sprints",
            "查询当前用户默认 Team 中指定项目的迭代列表；只接受 project_uuid 和有界 limit。",
            _object_schema(
                {
                    "project_uuid": _identifier(),
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                },
                required=("project_uuid", "limit"),
            ),
            _list_output("sprints", SPRINT_SCHEMA, maximum=100),
        ),
        _contract(
            "ones_list_issue_types",
            "查询指定 ONES 项目可用的工作项类型，供后续工作项查询使用；不猜测租户类型 UUID。",
            _object_schema(
                {
                    "project_uuid": _identifier(),
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                },
                required=("project_uuid", "limit"),
            ),
            _list_output("issue_types", ISSUE_TYPE_SCHEMA, maximum=100),
        ),
        _contract(
            "ones_query_work_items",
            "按项目、迭代、类型、状态、处理人、创建时间或关键词组合查询当前默认 Team 的工作项；所有筛选均为业务参数。",
            _WORK_ITEM_QUERY_INPUT,
            _list_output("items", WORK_ITEM_SCHEMA, maximum=100),
        ),
        _contract(
            "ones_get_work_item_detail",
            "查询一个明确 ONES 工作项 UUID 的有界详情和关联摘要。",
            _object_schema({"work_item_uuid": _identifier()}, required=("work_item_uuid",)),
            {
                "type": "object",
                "properties": {
                    "work_item": WORK_ITEM_SCHEMA,
                    "description": {"type": "string", "maxLength": 4000},
                    "related_items": {
                        "type": "array",
                        "maxItems": 100,
                        "items": WORK_ITEM_SCHEMA,
                    },
                    "untrusted_data": {"const": True},
                },
                "required": ["work_item", "related_items", "untrusted_data"],
                "additionalProperties": False,
            },
        ),
        _contract(
            "ones_list_work_item_messages",
            "查询一个明确 ONES 工作项的有界时间线消息；只返回安全纯文本和必要参与者信息。",
            _object_schema(
                {
                    "work_item_uuid": _identifier(),
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                },
                required=("work_item_uuid", "limit"),
            ),
            _list_output(
                "messages",
                _object_schema(
                    {
                        "uuid": {"type": "string", "maxLength": 128},
                        "type": {"type": "string", "maxLength": 80},
                        "sent_at": {"type": "string", "maxLength": 64},
                        "from": _person(),
                        "to": _person(),
                        "text": {"type": "string", "maxLength": 2000},
                    },
                    required=("uuid", "type", "sent_at", "text"),
                ),
                maximum=100,
            ),
        ),
        _contract(
            "ones_search_team_users",
            "按关键词查询当前用户默认 Team 中的人员；可选 project_uuid 只用于固定人员搜索筛选。",
            _object_schema(
                {
                    "keyword": {"type": "string", "maxLength": 200},
                    "project_uuid": _identifier(),
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                },
                required=("keyword", "limit"),
            ),
            _list_output("users", _person(), maximum=100),
        ),
        _contract(
            "ones_list_testcase_libraries",
            "查询当前用户默认 Team 的 ONES 测试用例库列表。",
            _object_schema(
                {"limit": {"type": "integer", "minimum": 1, "maximum": 100}},
                required=("limit",),
            ),
            _list_output(
                "libraries",
                _object_schema(
                    {
                        "uuid": {"type": "string", "maxLength": 128},
                        "name": {"type": "string", "maxLength": 300},
                        "case_count": {"type": "integer", "minimum": 0},
                        "sample": {"type": "boolean"},
                    },
                    required=("uuid", "name", "case_count", "sample"),
                ),
                maximum=100,
            ),
        ),
        _contract(
            "ones_list_testcase_modules",
            "查询一个明确测试用例库中的模块路径。",
            _object_schema(
                {
                    "library_uuid": _identifier(),
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                },
                required=("library_uuid", "limit"),
            ),
            _list_output(
                "modules",
                _object_schema(
                    {
                        "uuid": {"type": "string", "maxLength": 128},
                        "name": {"type": "string", "maxLength": 300},
                        "path": {"type": "string", "maxLength": 1000},
                        "parent_uuid": {"type": "string", "maxLength": 128},
                        "case_count": {"type": "integer", "minimum": 0},
                    },
                    required=("uuid", "name", "path", "case_count"),
                ),
                maximum=200,
            ),
        ),
        _contract(
            "ones_list_test_plans",
            "查询当前用户默认 Team 的 ONES 测试计划列表。",
            _object_schema(
                {"limit": {"type": "integer", "minimum": 1, "maximum": 100}},
                required=("limit",),
            ),
            _list_output(
                "plans",
                _object_schema(
                    {
                        "uuid": {"type": "string", "maxLength": 128},
                        "name": {"type": "string", "maxLength": 300},
                        "owner": _person(),
                        "status": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "maxLength": 200},
                                "category": {
                                    "type": "string",
                                    "enum": list(ONES_STATUS_CATEGORIES),
                                },
                            },
                            "required": ["name", "category"],
                            "additionalProperties": False,
                        },
                        "sample": {"type": "boolean"},
                    },
                    required=("uuid", "name", "sample"),
                ),
                maximum=100,
            ),
        ),
        _contract(
            "ones_query_test_cases",
            "按测试库模块或测试计划查询用例 UUID；module 模式必须同时提供 library_uuid。",
            _object_schema(
                {
                    "source": {"type": "string", "enum": ["module", "plan"]},
                    "source_uuid": _identifier(),
                    "library_uuid": _identifier(),
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                },
                required=("source", "source_uuid", "limit"),
            ),
            _list_output("test_cases", TESTCASE_SCHEMA, maximum=200),
        ),
        _contract(
            "ones_get_test_case_detail",
            "查询一个明确 ONES 测试用例 UUID 的详情和有界步骤。",
            _object_schema({"test_case_uuid": _identifier()}, required=("test_case_uuid",)),
            _TESTCASE_DETAIL_OUTPUT,
        ),
    )
}


def require_ones_tool_contract(identifier: str) -> OnesToolContract:
    try:
        return ONES_TOOL_CONTRACTS[identifier]
    except KeyError as exc:
        raise KeyError(f"Unknown ONES Tool contract: {identifier}") from exc
