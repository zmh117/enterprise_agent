"""Bounded, publication-owned DingTalk result recipients."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.modules.channel.domain.channel_event import ReplyRoute
from app.shared.exceptions import NonRetryableExecutionError

RECIPIENTS_ROUTE = "dingtalk_recipients"
ROBOT_MESSAGE_ROUTE = "dingtalk_robot_message"
MAX_RECIPIENTS = 20


def normalized_recipients(delivery: dict[str, Any]) -> list[dict[str, str]]:
    target = delivery.get("target") or {}
    rows = target.get("recipients") if isinstance(target, dict) else None
    if (
        delivery.get("connector_id")
        or delivery.get("options")
        or not isinstance(target, dict)
        or set(target) != {"recipients"}
        or not isinstance(rows, list)
        or not 1 <= len(rows) <= MAX_RECIPIENTS
    ):
        raise _invalid("必须配置 1–20 个接收人，不能同时配置其他投递选项")
    values: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        field = f"delivery.target.recipients.{index}"
        if not isinstance(row, dict) or set(row) - {"connector_id", "kind", "target_id", "label"}:
            raise _invalid("接收人包含不支持的字段", field)
        if any(
            not isinstance(row.get(k, ""), str)
            for k in ("connector_id", "kind", "target_id", "label")
        ):
            raise _invalid("接收人字段必须是字符串", field)
        value = {
            k: str(row.get(k, "")).strip() for k in ("connector_id", "kind", "target_id", "label")
        }
        if (
            not value["connector_id"]
            or len(value["connector_id"]) > 200
            or value["kind"] not in {"group", "user"}
            or not value["target_id"]
            or len(value["target_id"]) > 256
            or len(value["label"]) > 80
            or "://" in value["target_id"]
            or any(c.isspace() or ord(c) < 32 for c in value["target_id"])
        ):
            raise _invalid("请选择机器人、群或用户，并填写有效目标 ID（不能使用 URL）", field)
        key = recipient_key(value)
        if key in seen:
            raise _invalid("同一机器人下的接收人不能重复", field)
        seen.add(key)
        values.append(value)
    return values


def recipient_key(value: dict[str, str]) -> str:
    identity = [value["connector_id"], value["kind"], value["target_id"]]
    return hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()


def result_routes(payload: dict[str, Any]) -> list[tuple[str, ReplyRoute]]:
    if payload.get("type") != RECIPIENTS_ROUTE:
        return [("", ReplyRoute.from_dict(payload))]
    return [
        (
            recipient_key(row),
            ReplyRoute(
                type=ROBOT_MESSAGE_ROUTE,
                connector_id=row["connector_id"],
                target={"kind": row["kind"], "target_id": row["target_id"]},
            ),
        )
        for row in normalized_recipients(payload)
    ]


def _invalid(message: str, field: str = "delivery.target.recipients") -> NonRetryableExecutionError:
    return NonRetryableExecutionError(
        "Invalid result recipients",
        safe_message=message,
        error_code="validation_failed",
        field_errors=[{"field": field, "message": message}],
    )
