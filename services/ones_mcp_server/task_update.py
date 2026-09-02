from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from app.shared.ones_tool_contracts import (
    ONES_UPDATE_TASK_TOOL_IDENTIFIER,
    require_ones_tool_contract,
)
from services.ones_mcp_server.errors import OnesMcpError
from services.ones_mcp_server.task_update_catalog import (
    TaskUpdateField,
    TaskUpdateFieldCatalog,
)


@dataclass(frozen=True, slots=True)
class OnesTaskSnapshot:
    uuid: str
    number: int
    title: str
    issue_type_name: str
    project_uuid: str
    team_uuid: str
    server_update_stamp: str
    can_edit: bool
    can_update_watchers: bool
    available_fields: frozenset[str]
    values: dict[str, Any]
    display_values: dict[str, Any]
    allowed_entities: dict[str, dict[str, str]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CompiledTaskUpdate:
    normalized_arguments: dict[str, Any]
    provider_payload: dict[str, Any]
    changes: tuple[dict[str, str], ...]


def _denied(code: str, message: str) -> OnesMcpError:
    return OnesMcpError(message, safe_message=message, error_code=code)


def _is_defect(issue_type_name: str) -> bool:
    normalized = "".join(issue_type_name.casefold().split())
    return normalized in {"缺陷", "bug", "defect"}


def _normalized_value(field: TaskUpdateField, value: Any) -> Any:
    if value is None:
        raise _denied("ones_task_update_patch_invalid", f"{field.label}不能为 null")
    if field.value_kind in {"users", "entities", "options"}:
        if not isinstance(value, list):
            raise _denied("ones_task_update_patch_invalid", f"{field.label}必须是数组")
        return sorted(str(item) for item in value)
    if field.value_kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise _denied("ones_task_update_patch_invalid", f"{field.label}必须是数字")
        return value
    if not isinstance(value, str):
        raise _denied("ones_task_update_patch_invalid", f"{field.label}类型无效")
    if not value and not field.allow_clear:
        raise _denied("ones_task_update_clear_unsupported", f"{field.label}不支持清空")
    return value


def _entity_names(
    field: TaskUpdateField,
    value: Any,
    resolved_entities: Mapping[str, Mapping[str, str]],
) -> str:
    if value == "" or value == []:
        return "清空"
    if field.value_kind == "option":
        return field_option_name(field, str(value))
    if field.value_kind == "options":
        return "、".join(field_option_name(field, str(item)) for item in value)
    if field.value_kind in {"user", "sprint"}:
        names = resolved_entities.get(field.semantic_name, {})
        name = names.get(str(value))
        if not name:
            raise _denied(
                "ones_task_update_entity_invalid",
                f"{field.label}无法在当前缺陷范围内唯一解析",
            )
        return str(name)
    if field.value_kind in {"users", "entities"}:
        names = resolved_entities.get(field.semantic_name, {})
        resolved = [names.get(str(item)) for item in value]
        if any(not name for name in resolved):
            raise _denied(
                "ones_task_update_entity_invalid",
                f"{field.label}无法在当前缺陷范围内唯一解析",
            )
        return "、".join(sorted(str(name) for name in resolved))
    return str(value)


def field_option_name(field: TaskUpdateField, option_uuid: str) -> str:
    matches = [option["name"] for option in field.options if option["uuid"] == option_uuid]
    if len(matches) != 1:
        raise _denied(
            "ones_task_update_option_invalid",
            f"{field.label}的选项不存在或字段目录已过期",
        )
    return matches[0]


def _current_display(snapshot: OnesTaskSnapshot, field: TaskUpdateField, current: Any) -> str:
    displayed = snapshot.display_values.get(field.semantic_name)
    if displayed is None or displayed == "" or displayed == []:
        return "（空）"
    if isinstance(displayed, list):
        return "、".join(sorted(str(value) for value in displayed))
    return str(displayed if displayed is not None else current)


def _rich_text(plain_text: str) -> str:
    escaped = escape(plain_text, quote=True).replace("\n", "<br/>")
    return f"<p>{escaped}</p>"


def compile_task_update(
    arguments: dict[str, Any],
    *,
    snapshot: OnesTaskSnapshot,
    catalog: TaskUpdateFieldCatalog,
    resolved_entities: Mapping[str, Mapping[str, str]],
) -> CompiledTaskUpdate | None:
    contract = require_ones_tool_contract(ONES_UPDATE_TASK_TOOL_IDENTIFIER)
    errors = sorted(
        Draft202012Validator(contract.input_schema).iter_errors(arguments),
        key=lambda error: tuple(str(part) for part in error.path),
    )
    if errors:
        raise _denied("ones_task_update_patch_invalid", "ONES 缺陷更新参数无效")
    if str(arguments["uuid"]) != snapshot.uuid:
        raise _denied("ones_task_update_target_mismatch", "ONES 缺陷目标不匹配")
    if not _is_defect(snapshot.issue_type_name):
        raise _denied("ones_task_update_non_defect", "第一版只支持更新 ONES 缺陷")
    catalog.require_team(snapshot.team_uuid)
    if not snapshot.server_update_stamp:
        raise _denied("ones_task_update_snapshot_invalid", "ONES 缺陷更新版本不可用")
    if not snapshot.can_edit:
        raise _denied("ones_task_update_permission_denied", "当前 ONES 身份无权编辑该缺陷")
    if "watcher_uuids" in arguments and not snapshot.can_update_watchers:
        raise _denied(
            "ones_task_update_watchers_permission_denied",
            "当前 ONES 身份无权更新该缺陷的关注者",
        )

    normalized_arguments: dict[str, Any] = {"uuid": snapshot.uuid}
    provider_task: dict[str, Any] = {"uuid": snapshot.uuid}
    field_values: list[dict[str, Any]] = []
    changes: list[dict[str, str]] = []
    for semantic_name, proposed in arguments.items():
        if semantic_name == "uuid":
            continue
        field = catalog.require_field(semantic_name)
        if semantic_name not in snapshot.available_fields:
            raise _denied(
                "ones_task_update_field_not_applicable",
                f"当前缺陷布局不支持更新{field.label}",
            )
        value = _normalized_value(field, proposed)
        if field.value_kind in {"option", "options", "user", "users", "sprint", "entities"}:
            after = _entity_names(field, value, resolved_entities)
        else:
            after = "清空" if value == "" else str(value)
        current_raw = snapshot.values.get(
            semantic_name,
            [] if field.value_kind in {"users", "entities", "options"} else "",
        )
        current = (
            sorted(str(item) for item in current_raw)
            if field.value_kind in {"users", "entities", "options"}
            and isinstance(current_raw, list)
            else current_raw
        )
        if current == value:
            continue
        normalized_arguments[semantic_name] = value
        changes.append(
            {
                "field": field.label,
                "before": _current_display(snapshot, field, current),
                "after": after,
            }
        )
        if semantic_name == "title":
            provider_task["name"] = value
            provider_task["summary"] = value
        elif semantic_name == "description":
            provider_task["desc_rich"] = _rich_text(value)
            provider_task["descriptionText"] = value
        elif semantic_name == "assignee_uuid":
            provider_task["assign"] = value
        else:
            field_values.append(
                {
                    "field_uuid": field.provider_field_uuid,
                    "type": field.provider_type,
                    "value": value,
                }
            )
    if not changes:
        return None
    if field_values:
        provider_task["field_values"] = field_values
    return CompiledTaskUpdate(
        normalized_arguments=normalized_arguments,
        provider_payload={"tasks": [provider_task]},
        changes=tuple(changes),
    )
