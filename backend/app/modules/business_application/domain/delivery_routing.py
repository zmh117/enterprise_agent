from __future__ import annotations

from typing import Any

PER_TRIGGER = "per_trigger"


def trigger_identity(trigger: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(trigger.get("trigger_type") or ""),
        str(trigger.get("connector_id") or ""),
        " ".join(str(trigger.get("routing_key") or "").strip().lower().split()),
    )


def delivery_link_errors(
    triggers: list[dict[str, Any]],
    deliveries: list[dict[str, Any]],
    *,
    require_reply: bool = False,
) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    sources = {trigger_identity(trigger): trigger for trigger in triggers}
    if len(sources) != len(triggers):
        errors.append({"field": "triggers", "message": "同一入口路由不能重复配置"})
    seen: set[tuple[str, str, str]] = set()
    active: set[tuple[str, str, str]] = set()
    for index, delivery in enumerate(deliveries):
        field = f"deliveries.{index}.config.trigger"
        source = (delivery.get("config") or {}).get("trigger")
        if not isinstance(source, dict):
            errors.append({"field": field, "message": "请在对应触发器下重新配置投递"})
            continue
        key = trigger_identity(source)
        trigger = sources.get(key)
        if trigger is None:
            errors.append({"field": field, "message": "投递关联的触发器不存在"})
            continue
        if key in seen:
            errors.append(
                {
                    "field": field,
                    "message": "每个触发器只能配置一个投递方式",
                    "reason_code": "duplicate_delivery_binding",
                }
            )
        seen.add(key)
        if delivery.get("enabled", True):
            active.add(key)
        kind = delivery.get("delivery_type")
        if key[0] in {"dingtalk_private", "dingtalk_group"}:
            if kind != "reply_original" or delivery.get("connector_id") != key[1]:
                errors.append(
                    {
                        "field": f"deliveries.{index}",
                        "message": "钉钉入口须通过相同机器人回复原会话",
                        "reason_code": "delivery_connector_mismatch"
                        if delivery.get("connector_id") != key[1]
                        else "unsupported_delivery",
                    }
                )
        elif kind not in {"dingtalk_private", "dingtalk_group", "webhook_callback"}:
            errors.append({"field": f"deliveries.{index}", "message": "Webhook 不支持回复原会话"})
        elif kind != "dingtalk_private" and not (delivery.get("config") or {}).get(
            "target_reference"
        ):
            errors.append(
                {
                    "field": f"deliveries.{index}.config.target_reference",
                    "message": "请填写投递目标",
                }
            )
    if require_reply:
        for index, trigger in enumerate(triggers):
            if (
                trigger.get("enabled", True)
                and trigger.get("trigger_type") in {"dingtalk_private", "dingtalk_group"}
                and trigger_identity(trigger) not in active
            ):
                errors.append(
                    {"field": f"triggers.{index}", "message": "钉钉入口缺少回复原会话投递"}
                )
    return errors


def deliveries_for_trigger(
    snapshot: dict[str, Any], trigger: dict[str, Any]
) -> list[dict[str, Any]]:
    """Only explicit references are eligible in a per-trigger publication."""
    key = trigger_identity(trigger)
    return [
        value
        for value in snapshot.get("deliveries") or []
        if isinstance(value, dict)
        and isinstance((value.get("config") or {}).get("trigger"), dict)
        and trigger_identity(value["config"]["trigger"]) == key
    ]
