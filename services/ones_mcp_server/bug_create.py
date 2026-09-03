from __future__ import annotations

from dataclasses import dataclass
from html import escape
import re
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from app.shared.ones_tool_contracts import ONES_CREATE_BUG_TOOL_IDENTIFIER, require_ones_tool_contract
from services.ones_mcp_server.bug_create_catalog import BugCreateFieldCatalog
from services.ones_mcp_server.errors import OnesMcpError


_HTML_TAG = re.compile(r"<\s*/?\s*[A-Za-z!][^>]*>")
_PROVENANCE_SOURCES = {
    "current_message",
    "conversation_context",
    "field_catalog",
    "ones_read",
}
_FIELD_ORDER = (
    ("project_uuid", "所属项目"),
    ("issue_type_uuid", "工作项类型"),
    ("title", "标题"),
    ("description", "描述"),
    ("environment", "环境"),
    ("assignee_uuid", "负责人"),
    ("watcher_uuids", "关注者"),
    ("defect_type_uuid", "缺陷类型"),
    ("urgency_uuid", "紧急程度"),
    ("severity_uuid", "严重程度"),
    ("discovery_difficulty_uuid", "发现难易程度"),
    ("reproduction_probability_uuid", "重现概率"),
    ("product_uuids", "所属产品"),
    ("product_module_uuids", "所属功能模块"),
    ("discovery_stage_uuid", "缺陷发现阶段"),
    ("online_defect_uuid", "是否线上缺陷"),
    ("historical_defect_uuid", "是否历史缺陷"),
    ("affected_version_uuids", "影响版本"),
)


def _invalid(code: str, message: str) -> OnesMcpError:
    return OnesMcpError(message, safe_message=message, error_code=code)


def _stable_unique(values: list[object]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw)
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _plain_text(value: object, *, label: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise _invalid("ones_bug_create_arguments_invalid", f"{label}必须是文本")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise _invalid("ones_bug_create_arguments_invalid", f"{label}不能为空或超过长度限制")
    if _HTML_TAG.search(normalized):
        raise _invalid("ones_bug_create_html_rejected", f"{label}只接受纯文本，不接受 HTML")
    if any(ord(char) < 32 and char not in "\n\r\t" for char in normalized):
        raise _invalid("ones_bug_create_arguments_invalid", f"{label}包含无效控制字符")
    return normalized


def _rich_text(value: str) -> str:
    return f"<p>{escape(value, quote=True).replace(chr(10), '<br/>')}</p>"


def validate_bug_create_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    contract = require_ones_tool_contract(ONES_CREATE_BUG_TOOL_IDENTIFIER)
    errors = sorted(
        Draft202012Validator(contract.input_schema).iter_errors(arguments),
        key=lambda error: tuple(str(part) for part in error.path),
    )
    if errors:
        raise _invalid("ones_bug_create_arguments_invalid", "ONES 缺陷创建参数不完整或无效")
    normalized = dict(arguments)
    normalized["title"] = _plain_text(arguments["title"], label="标题", maximum=500)
    normalized["description"] = _plain_text(
        arguments["description"], label="描述", maximum=8000
    )
    normalized["environment"] = _plain_text(
        arguments["environment"], label="环境", maximum=4000
    )
    if "待补充" in normalized["description"]:
        raise _invalid(
            "ones_bug_create_draft_incomplete",
            "缺陷描述仍包含“待补充”，请完善后再生成确认卡",
        )
    for field in (
        "product_uuids",
        "product_module_uuids",
        "affected_version_uuids",
    ):
        normalized[field] = _stable_unique(list(arguments[field]))
        if not normalized[field]:
            raise _invalid("ones_bug_create_arguments_invalid", f"{field}不能为空")
    normalized["watcher_uuids"] = _stable_unique(list(arguments.get("watcher_uuids") or []))
    provenance = arguments.get("field_provenance") or []
    fields = [str(item["field"]) for item in provenance]
    if len(fields) != len(set(fields)):
        raise _invalid(
            "ones_bug_create_provenance_invalid",
            "同一缺陷字段只能声明一个建议来源",
        )
    if any(str(item["source"]) not in _PROVENANCE_SOURCES for item in provenance):
        raise _invalid("ones_bug_create_provenance_invalid", "缺陷字段建议来源无效")
    normalized["field_provenance"] = [
        {"field": str(item["field"]), "source": str(item["source"])} for item in provenance
    ]
    normalized.pop("supersedes_intent_id", None)
    return normalized


@dataclass(frozen=True, slots=True)
class CompiledBugCreate:
    normalized_arguments: dict[str, Any]
    provider_payload: dict[str, Any]
    summary: dict[str, Any]


def compile_bug_create(
    arguments: dict[str, Any],
    *,
    catalog: BugCreateFieldCatalog,
    team_uuid: str,
    task_uuid: str,
    current_user_uuid: str,
    display_values: Mapping[str, Mapping[str, str]],
) -> CompiledBugCreate:
    normalized = validate_bug_create_arguments(arguments)
    catalog.require_team(team_uuid)
    watchers = _stable_unique([current_user_uuid, *normalized["watcher_uuids"]])
    normalized["watcher_uuids"] = watchers

    static_option_fields = (
        "defect_type_uuid",
        "urgency_uuid",
        "severity_uuid",
        "discovery_difficulty_uuid",
        "reproduction_probability_uuid",
        "discovery_stage_uuid",
        "online_defect_uuid",
        "historical_defect_uuid",
    )
    option_names = {
        field: catalog.option_name(field, str(normalized[field]))
        for field in static_option_fields
    }
    def names(kind: str, values: list[str]) -> list[str]:
        available = display_values.get(kind, {})
        resolved = [str(available.get(value) or "") for value in values]
        if any(not value for value in resolved):
            raise _invalid(
                "ones_bug_create_reference_invalid",
                "缺陷中的项目、人员、产品、模块或版本已失效",
            )
        return resolved

    project_name = names("project_uuid", [str(normalized["project_uuid"])])[0]
    user_uuids = _stable_unique([str(normalized["assignee_uuid"]), *watchers])
    user_names = dict(zip(user_uuids, names("user_uuids", user_uuids), strict=True))
    product_names = names("product_uuids", normalized["product_uuids"])
    module_names = names("product_module_uuids", normalized["product_module_uuids"])
    affected_names = names(
        "affected_version_uuids", normalized["affected_version_uuids"]
    )

    field_values: list[dict[str, Any]] = []
    for semantic_name in (
        "environment",
        "assignee_uuid",
        "defect_type_uuid",
        "urgency_uuid",
        "severity_uuid",
        "discovery_difficulty_uuid",
        "reproduction_probability_uuid",
        "product_uuids",
        "product_module_uuids",
        "discovery_stage_uuid",
        "online_defect_uuid",
        "historical_defect_uuid",
        "affected_version_uuids",
        "title",
        "description",
    ):
        field = catalog.require_field(semantic_name)
        value: Any = normalized[semantic_name]
        if semantic_name == "description":
            value = _rich_text(str(value))
        field_values.append(
            {
                "field_uuid": field.provider_field_uuid,
                "type": field.provider_type,
                "value": value,
            }
        )
    provider_task = {
        "uuid": task_uuid,
        "summary": normalized["title"],
        "assign": normalized["assignee_uuid"],
        "parent_uuid": "",
        "issue_type_uuid": catalog.fixed_issue_type_uuid,
        "project_uuid": normalized["project_uuid"],
        "watchers": watchers,
        "field_values": field_values,
        "add_manhours": [],
    }

    provenance = {
        str(item["field"]): str(item["source"]) for item in normalized["field_provenance"]
    }
    display: dict[str, str] = {
        "project_uuid": project_name,
        "issue_type_uuid": "缺陷",
        "title": str(normalized["title"]),
        "description": str(normalized["description"]),
        "environment": str(normalized["environment"]),
        "assignee_uuid": user_names[str(normalized["assignee_uuid"])],
        "watcher_uuids": "、".join(user_names[value] for value in watchers),
        **option_names,
        "product_uuids": "、".join(product_names),
        "product_module_uuids": "、".join(module_names),
        "affected_version_uuids": "、".join(affected_names),
    }
    summary_fields: list[dict[str, str]] = []
    for semantic_name, label in _FIELD_ORDER:
        if semantic_name == "issue_type_uuid":
            marker = "系统固定"
        elif semantic_name == "watcher_uuids":
            marker = "系统默认"
        elif semantic_name in provenance:
            marker = "建议值"
        else:
            marker = ""
        summary_fields.append(
            {"label": label, "value": display[semantic_name], "marker": marker}
        )
    return CompiledBugCreate(
        normalized_arguments=normalized,
        provider_payload={"tasks": [provider_task]},
        summary={"operation": "创建缺陷", "target": normalized["title"], "fields": summary_fields},
    )


def compiled_bug_matches_readback(
    compiled: CompiledBugCreate,
    readback: Mapping[str, Any],
) -> bool:
    tasks = compiled.provider_payload.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 1:
        return False
    expected = tasks[0]
    if not isinstance(expected, dict):
        return False
    return all(readback.get(key) == expected.get(key) for key in expected)
