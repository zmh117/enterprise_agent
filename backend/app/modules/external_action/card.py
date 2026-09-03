from __future__ import annotations

from typing import Any

from app.shared.exceptions import NonRetryableExecutionError


MAX_CARD_DETAIL_CHARACTERS = 4000


def _invalid(code: str, message: str) -> NonRetryableExecutionError:
    return NonRetryableExecutionError(message, safe_message=message, error_code=code)


def render_confirmation_card(
    intent: dict[str, Any],
    summary: dict[str, Any],
) -> dict[str, str]:
    provider = str(intent.get("execution_provider_code") or "dingtalk")
    if provider == "ones":
        return _render_ones(intent, summary)
    if provider == "dingtalk":
        return _render_dingtalk(intent, summary)
    raise _invalid("external_action_card_provider_unsupported", "外部操作确认卡片类型无效")


def _render_ones(intent: dict[str, Any], summary: dict[str, Any]) -> dict[str, str]:
    if str(intent.get("operation_code") or "") == "ones.task.create":
        return _render_ones_bug_create(intent, summary)
    if (
        str(intent.get("operation_code") or "") != "ones.task.update"
        or str(intent.get("target_resource_type") or "") != "task"
        or str(summary.get("operation") or "") != "更新缺陷"
    ):
        raise _invalid("external_action_card_summary_invalid", "ONES 缺陷确认摘要无效")
    target = str(summary.get("target") or "")
    changes = summary.get("changes")
    if not target or not isinstance(changes, list) or not changes:
        raise _invalid("external_action_card_summary_invalid", "ONES 缺陷确认摘要无效")
    lines: list[str] = []
    for raw in changes:
        if not isinstance(raw, dict):
            raise _invalid("external_action_card_summary_invalid", "ONES 缺陷确认摘要无效")
        field = str(raw.get("field") or "")
        before = str(raw.get("before") or "")
        after = str(raw.get("after") or "")
        if not field or not before or not after:
            raise _invalid("external_action_card_summary_invalid", "ONES 缺陷确认摘要无效")
        lines.append(f"{field}：{before} → {after}")
    detail = "\n".join(lines)
    if len(detail) > MAX_CARD_DETAIL_CHARACTERS:
        raise _invalid(
            "external_action_card_detail_too_large",
            "本次缺陷修改内容超过确认卡片上限，请拆分后重新发起",
        )
    return {
        "providerName": "ONES",
        "operationName": "更新缺陷",
        "targetName": target[:700],
        "detailText": detail,
    }


def _render_ones_bug_create(
    intent: dict[str, Any], summary: dict[str, Any]
) -> dict[str, str]:
    if (
        str(intent.get("target_resource_type") or "") != "task"
        or str(summary.get("operation") or "") != "创建缺陷"
    ):
        raise _invalid("external_action_card_summary_invalid", "ONES 缺陷创建确认摘要无效")
    target = str(summary.get("target") or "")
    fields = summary.get("fields")
    if not target or not isinstance(fields, list) or len(fields) != 18:
        raise _invalid("external_action_card_summary_invalid", "ONES 缺陷创建确认摘要无效")
    lines: list[str] = []
    for raw in fields:
        if not isinstance(raw, dict):
            raise _invalid("external_action_card_summary_invalid", "ONES 缺陷创建确认摘要无效")
        label = str(raw.get("label") or "")
        value = str(raw.get("value") or "")
        marker = str(raw.get("marker") or "")
        if (
            not label
            or not value
            or marker not in {"", "建议值", "系统固定", "系统默认"}
            or any(ord(char) < 32 and char not in "\n\r\t" for char in label + value)
        ):
            raise _invalid("external_action_card_summary_invalid", "ONES 缺陷创建确认摘要无效")
        rendered_label = f"{label}（{marker}）" if marker else label
        lines.append(f"{rendered_label}：{value}")
    detail = "\n".join(lines)
    if len(detail) > MAX_CARD_DETAIL_CHARACTERS:
        raise _invalid(
            "external_action_card_detail_too_large",
            "本次缺陷创建内容超过确认卡片上限，请缩短描述后重新发起",
        )
    return {
        "providerName": "ONES",
        "operationName": "创建缺陷",
        "targetName": target,
        "detailText": detail,
    }


def _render_dingtalk(intent: dict[str, Any], summary: dict[str, Any]) -> dict[str, str]:
    operation_code = str(intent.get("operation_code") or "")
    targets = {
        "dingtalk.todo.create": "当前用户本人",
        "dingtalk.todo.update": "当前用户本人待办",
        "dingtalk.todo.complete": "当前用户本人待办",
        "dingtalk.calendar.event.create": "当前用户主日历",
        "dingtalk.calendar.event.update": "当前用户主日历",
        "dingtalk.aitable.sheet.create": "当前用户可访问的指定 AI 表格",
        "dingtalk.aitable.sheet.update": "当前用户可访问的指定 AI 表格数据表",
        "dingtalk.aitable.field.create": "当前用户可访问的指定 AI 表格数据表",
        "dingtalk.aitable.field.update": "当前用户可访问的指定 AI 表格字段",
        "dingtalk.aitable.record.insert": "当前用户可访问的指定 AI 表格",
        "dingtalk.aitable.record.update": "当前用户可访问的指定 AI 表格",
        "dingtalk.robot.group_message.send": str(summary.get("target") or "当前来源群"),
        "dingtalk.robot.batch_send_message_to_users": (
            f"{int(summary.get('recipient_count') or 0)} 名明确收件人"
        ),
        "dingtalk.work_notification.send": "当前用户本人",
    }
    if operation_code not in targets:
        raise _invalid("external_action_card_summary_invalid", "钉钉确认卡片操作无效")
    operation = str(summary.get("operation") or operation_code)[:100]
    return {
        "providerName": "钉钉",
        "operationName": operation,
        "targetName": targets[operation_code][:200],
        "detailText": _dingtalk_detail(operation_code, summary),
    }


def _dingtalk_detail(operation_code: str, summary: dict[str, Any]) -> str:
    if operation_code == "dingtalk.todo.create":
        lines = [
            f"待办：{str(summary.get('subject') or '')[:200]}",
            f"截止：{str(summary.get('due_time') or '未设置')[:64]}",
        ]
    elif operation_code == "dingtalk.todo.update":
        lines = [
            f"待办 ID：{str(summary.get('task_id') or '')[:512]}",
            f"标题：{str(summary.get('subject') or '')[:200]}",
            f"截止：{str(summary.get('due_time') or '未设置')[:64]}",
        ]
    elif operation_code == "dingtalk.todo.complete":
        lines = [
            f"待办 ID：{str(summary.get('task_id') or '')[:512]}",
            f"标题：{str(summary.get('subject') or '')[:200]}",
        ]
    elif operation_code == "dingtalk.calendar.event.create":
        lines = [
            f"日程：{str(summary.get('title') or '')[:500]}",
            f"开始：{str(summary.get('start_time') or '')[:64]}",
            f"结束：{str(summary.get('end_time') or '')[:64]}",
            f"时区：{str(summary.get('time_zone') or '')[:64]}",
        ]
    elif operation_code == "dingtalk.calendar.event.update":
        lines = [
            f"日程 ID：{str(summary.get('event_id') or '')[:512]}",
            f"标题：{str(summary.get('title') or '')[:500]}",
            f"时间：{str(summary.get('time_range') or '')[:160]}",
        ]
    elif operation_code == "dingtalk.aitable.sheet.create":
        fields = summary.get("field_names")
        names = fields if isinstance(fields, list) else []
        lines = [
            f"Base ID：{str(summary.get('base_id') or '')[:512]}",
            f"数据表名称：{str(summary.get('name') or '')[:300]}",
            "初始字段：" + "、".join(str(item)[:300] for item in names[:50]),
        ]
    elif operation_code == "dingtalk.aitable.sheet.update":
        lines = [
            f"Base ID：{str(summary.get('base_id') or '')[:512]}",
            f"Sheet ID：{str(summary.get('sheet_id') or '')[:512]}",
            f"新名称：{str(summary.get('name') or '')[:300]}",
        ]
    elif operation_code in {"dingtalk.aitable.field.create", "dingtalk.aitable.field.update"}:
        lines = [
            f"Base ID：{str(summary.get('base_id') or '')[:512]}",
            f"Sheet ID：{str(summary.get('sheet_id') or '')[:512]}",
        ]
        if operation_code.endswith(".create"):
            lines.extend(
                [
                    f"字段名称：{str(summary.get('name') or '')[:300]}",
                    f"字段类型：{str(summary.get('field_type') or '')[:64]}",
                ]
            )
        else:
            lines.extend(
                [
                    f"Field ID：{str(summary.get('field_id') or '')[:512]}",
                    f"新名称：{str(summary.get('name') or '')[:300]}",
                ]
            )
    elif operation_code in {
        "dingtalk.aitable.record.insert",
        "dingtalk.aitable.record.update",
    }:
        fields = summary.get("field_names")
        names = fields if isinstance(fields, list) else []
        lines = [
            f"Base ID：{str(summary.get('base_id') or '')[:512]}",
            f"Sheet ID：{str(summary.get('sheet_id') or '')[:512]}",
            f"记录数：{int(summary.get('record_count') or 0)}",
            "字段：" + "、".join(str(item)[:128] for item in names[:50]),
        ]
    elif operation_code == "dingtalk.robot.batch_send_message_to_users":
        suffixes = summary.get("recipient_id_suffixes")
        values = suffixes if isinstance(suffixes, list) else []
        lines = [
            f"收件人数：{int(summary.get('recipient_count') or 0)}",
            "收件人 ID 尾号：" + "、".join(str(item)[:16] for item in values),
            f"标题：{str(summary.get('title') or '')[:200]}",
            f"正文：{str(summary.get('text') or '')[:3000]}",
        ]
    elif operation_code in {
        "dingtalk.robot.group_message.send",
        "dingtalk.work_notification.send",
    }:
        lines = [
            f"标题：{str(summary.get('title') or '')[:200]}",
            f"正文：{str(summary.get('text') or '')[:3000]}",
        ]
    else:
        raise _invalid("external_action_card_summary_invalid", "钉钉确认卡片操作无效")
    return "\n".join(lines)[:MAX_CARD_DETAIL_CHARACTERS]
