"""Resolve and recheck application-owned DingTalk recipients without exposing addresses."""

from __future__ import annotations

from typing import Any

from app.shared.database import Database
from app.shared.exceptions import NonRetryableExecutionError


def bound_recipients(database: Database, connector_id: str) -> list[dict[str, str]]:
    rows = database.execute(
        """select u.id as user_id, u.display_name, u.username,
                  i.id as external_identity_id, i.external_subject_id, i.dingtalk_enterprise_id
             from integration_connector c
             join dingtalk_enterprise e on e.id=c.dingtalk_enterprise_id
             join user_external_identity i on i.dingtalk_enterprise_id=e.id
             join app_user u on u.id=i.user_id
            where c.id=? and c.enabled=1 and c.deleted=0
              and c.connector_type='dingtalk_enterprise_stream' and e.status='ACTIVE'
              and i.provider='dingtalk' and i.status='enabled'
              and u.status='enabled' and u.account_type='human'
            order by u.display_name, u.id""",
        (connector_id,),
    )
    return [
        {
            "connector_id": connector_id,
            "kind": "user",
            "target_id": str(row["external_subject_id"]),
            "label": str(row["display_name"] or row["username"]),
            "user_id": str(row["user_id"]),
            "external_identity_id": str(row["external_identity_id"]),
            "enterprise_id": str(row["dingtalk_enterprise_id"]),
        }
        for row in rows
    ]


def freeze_recipients(
    database: Database, connector_id: str, user_ids: list[str]
) -> list[dict[str, str]]:
    candidates = {row["user_id"]: row for row in bound_recipients(database, connector_id)}
    if any(user_id not in candidates for user_id in user_ids):
        raise NonRetryableExecutionError(
            "DingTalk recipient unavailable",
            safe_message="目标人员须启用并绑定机器人所属企业的钉钉身份",
            error_code="dingtalk_recipient_unavailable",
        )
    return [candidates[user_id] for user_id in user_ids]


def require_bound_recipient(database: Database, connector_id: str, target: dict[str, Any]) -> None:
    fields = ("user_id", "external_identity_id", "enterprise_id", "target_id")
    if not all(target.get(key) for key in fields) or not any(
        all(row[key] == target[key] for key in fields)
        for row in bound_recipients(database, connector_id)
    ):
        raise NonRetryableExecutionError(
            "Frozen DingTalk binding is no longer active",
            safe_message="目标人员的钉钉绑定已变更或停用，请更新应用投递配置",
            error_code="dingtalk_recipient_unavailable",
        )
