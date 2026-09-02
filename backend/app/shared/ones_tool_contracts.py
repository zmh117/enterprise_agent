from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final


ONES_ID_PATTERN: Final = r"^[A-Za-z0-9_-]+$"
ONES_STATUS_CATEGORIES: Final = ("to_do", "in_progress", "done")
ONES_UPDATE_TASK_TOOL_IDENTIFIER: Final = "ones_update_task"
ONES_CONFIRMATION_POLICY: Final = "external_action_card_v1"


@dataclass(frozen=True, slots=True)
class OnesToolContract:
    identifier: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    effect: str = "read"
    confirmation_policy: str = "none"
    operation_code: str = ""
    risk_level: str = "low"
    target_policy: str = ""

    @property
    def read_only(self) -> bool:
        return self.effect == "read"

    @property
    def destructive(self) -> bool:
        return self.effect == "mutation"

    @property
    def idempotent(self) -> bool:
        # Mutation calls only prepare a snapshot-aware Action Intent. The
        # confirmed Provider write is executed separately by the worker.
        return self.effect == "mutation"

    @property
    def open_world(self) -> bool:
        return False


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
    *,
    effect: str = "read",
    confirmation_policy: str = "none",
    operation_code: str = "",
    risk_level: str = "low",
    target_policy: str = "",
) -> OnesToolContract:
    return OnesToolContract(
        identifier,
        description,
        input_schema,
        output_schema,
        effect,
        confirmation_policy,
        operation_code,
        risk_level,
        target_policy,
    )


def _identifier_array(*, maximum: int = 100) -> dict[str, Any]:
    return {
        "type": "array",
        "maxItems": maximum,
        "uniqueItems": True,
        "items": _identifier(),
    }


_ONES_UPDATE_TASK_INPUT = {
    "type": "object",
    "properties": {
        "uuid": _identifier(),
        "title": {"type": "string", "minLength": 1, "maxLength": 500},
        "description": {"type": "string", "maxLength": 8000},
        "assignee_uuid": _identifier(),
        "environment": {"type": "string", "maxLength": 4000},
        "labels_text": {"type": "string", "maxLength": 2000},
        "resolver_uuid": _identifier(),
        "owner_uuids": _identifier_array(),
        "watcher_uuids": _identifier_array(),
        "defect_type_uuid": _identifier(),
        "urgency_uuid": _identifier(),
        "severity_uuid": _identifier(),
        "discovery_difficulty_uuid": _identifier(),
        "reproduction_probability_uuid": _identifier(),
        "sprint_uuid": _identifier(),
        "product_uuids": _identifier_array(),
        "product_module_uuids": _identifier_array(),
        "discovery_stage_uuid": _identifier(),
        "online_defect_uuid": _identifier(),
        "historical_defect_uuid": _identifier(),
        "affected_version_mes_uuids": _identifier_array(),
        "fixed_version_mes_uuids": _identifier_array(),
        "verified_version_mes_uuids": _identifier_array(),
        "solution_text": {"type": "string", "maxLength": 8000},
        "cause_uuid": _identifier(),
        "svn_version_number": {"type": "number"},
        "handling_result_uuid": _identifier(),
        "impact_analysis": {"type": "string", "maxLength": 8000},
        "multi_version_duplicate_bug_uuid": _identifier(),
        "priority_uuid": _identifier(),
    },
    "required": ["uuid"],
    "minProperties": 2,
    "additionalProperties": False,
}

_ONES_UPDATE_TASK_OUTPUT = {
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "enum": ["confirmation_required", "no_update"],
        },
        "action_intent_id": {"type": "string", "maxLength": 128},
        "revision": {"type": "integer", "minimum": 1},
        "expires_at": {"type": "string", "format": "date-time", "maxLength": 64},
        "summary": {
            "type": "object",
            "properties": {
                "operation": {"const": "更新缺陷"},
                "target": {"type": "string", "maxLength": 700},
                "changes": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 29,
                    "items": {
                        "type": "object",
                        "properties": {
                            "field": {"type": "string", "maxLength": 100},
                            "before": {"type": "string", "maxLength": 8000},
                            "after": {"type": "string", "maxLength": 8000},
                        },
                        "required": ["field", "before", "after"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["operation", "target", "changes"],
            "additionalProperties": False,
        },
    },
    "required": ["status"],
    "additionalProperties": False,
}


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

_CUSTOM_WORK_ITEM_QUERY_INPUT = {
    **_WORK_ITEM_QUERY_INPUT,
    "properties": {
        **_WORK_ITEM_QUERY_INPUT["properties"],
        "custom_option_filters": {
            "type": "array",
            "maxItems": 8,
            "items": _object_schema(
                {
                    "field_uuid": _identifier(),
                    "option_uuids": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 20,
                        "uniqueItems": True,
                        "items": _identifier(),
                    },
                },
                required=("field_uuid", "option_uuids"),
            ),
        },
    },
    "required": ["limit", "custom_option_filters"],
}

_QUERY_CONDITION_OUTPUT = {
    "type": "object",
    "properties": {
        "matches": {
            "type": "array",
            "maxItems": 20,
            "items": {
                "oneOf": [
                    _object_schema(
                        {
                            "condition_type": {"const": "status"},
                            "uuid": _identifier(),
                            "name": {"type": "string", "maxLength": 300},
                            "category": {
                                "type": "string",
                                "enum": list(ONES_STATUS_CATEGORIES),
                            },
                        },
                        required=("condition_type", "uuid", "name", "category"),
                    ),
                    _object_schema(
                        {
                            "condition_type": {"const": "custom_option"},
                            "field_uuid": _identifier(),
                            "field_name": {"type": "string", "maxLength": 300},
                            "option_uuid": _identifier(),
                            "option_name": {"type": "string", "maxLength": 300},
                        },
                        required=(
                            "condition_type",
                            "field_uuid",
                            "field_name",
                            "option_uuid",
                            "option_name",
                        ),
                    ),
                ]
            },
        },
        "total": {"type": "integer", "minimum": 0},
        "returned": {"type": "integer", "minimum": 0, "maximum": 20},
        "truncated": {"type": "boolean"},
        "dictionary_version": {"type": "string", "maxLength": 80},
        "captured_at": {"type": "string", "format": "date", "maxLength": 10},
        "untrusted_data": {"const": True},
    },
    "required": [
        "matches",
        "total",
        "returned",
        "truncated",
        "dictionary_version",
        "captured_at",
        "untrusted_data",
    ],
    "additionalProperties": False,
}

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
            "ones_query_work_items_with_custom_options",
            "按项目、迭代、类型、状态、处理人、自定义选项、创建时间或关键词组合查询当前默认 Team 的工作项；自定义字段和值必须来自受管条件字典。",
            _CUSTOM_WORK_ITEM_QUERY_INPUT,
            _list_output("items", WORK_ITEM_SCHEMA, maximum=100),
        ),
        _contract(
            "ones_resolve_query_conditions",
            "按中文或显示名解析当前 Team 受管快照中的状态或自定义选项候选；项目、迭代、类型和人员必须使用实时查询 Tool。",
            _object_schema(
                {
                    "condition_type": {
                        "type": "string",
                        "enum": ["status", "custom_option"],
                    },
                    "keyword": {"type": "string", "minLength": 1, "maxLength": 200},
                    "field_keyword": {"type": "string", "maxLength": 200},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                required=("condition_type", "keyword", "limit"),
            ),
            _QUERY_CONDITION_OUTPUT,
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
            "ones_get_users_by_uuids",
            "按明确 UUID 批量查询当前用户默认 Team 中的人员安全摘要；只返回 UUID 和姓名。",
            _object_schema(
                {
                    "user_uuids": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 100,
                        "uniqueItems": True,
                        "items": _identifier(),
                    }
                },
                required=("user_uuids",),
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
        _contract(
            ONES_UPDATE_TASK_TOOL_IDENTIFIER,
            "更新一个明确 UUID 的现有 ONES 缺陷；只接受语义化 Patch，仅钉钉来源可用，调用后私发确认卡片，用户逐次确认后才执行写入。",
            _ONES_UPDATE_TASK_INPUT,
            _ONES_UPDATE_TASK_OUTPUT,
            effect="mutation",
            confirmation_policy=ONES_CONFIRMATION_POLICY,
            operation_code="ones.task.update",
            risk_level="high",
            target_policy="single_existing_defect",
        ),
    )
}


def require_ones_tool_contract(identifier: str) -> OnesToolContract:
    try:
        return ONES_TOOL_CONTRACTS[identifier]
    except KeyError as exc:
        raise KeyError(f"Unknown ONES Tool contract: {identifier}") from exc
