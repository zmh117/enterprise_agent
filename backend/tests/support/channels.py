from __future__ import annotations

import base64
import hashlib
import hmac

from app.bootstrap import Container


def ensure_active_dingtalk_test_enterprise(
    runtime: Container,
    *,
    connector_id: str = "connector-dingtalk-stream-default",
    corp_id: str = "corp-test-enterprise",
    name: str = "测试钉钉企业",
) -> dict[str, object]:
    timestamp = "2026-08-03T00:00:00+00:00"
    existing = runtime.database.execute_one(
        "select * from dingtalk_enterprise where corp_id = ?",
        (corp_id,),
    )
    if existing is None:
        created = runtime.managed_channel_service.create_dingtalk_enterprise(
            name=name,
            actor_id="user_local_admin",
        )
        runtime.database.execute(
            """
            update dingtalk_enterprise
               set corp_id = ?, status = 'ACTIVE', verified_at = ?,
                   verification_event_id = 'test-fixture-verification'
             where id = ?
            """,
            (corp_id, timestamp, created["id"]),
        )
        existing = runtime.database.execute_one(
            "select * from dingtalk_enterprise where id = ?",
            (created["id"],),
        )
    assert existing is not None
    runtime.database.execute(
        """
        update integration_connector
           set dingtalk_enterprise_id = ?
         where id = ? and connector_type = 'dingtalk_enterprise_stream'
        """,
        (existing["id"], connector_id),
    )
    runtime.database.execute(
        """
        update user_external_identity
           set dingtalk_enterprise_id = ?, tenant_code = ?, connector_id = ''
         where provider = 'dingtalk'
           and dingtalk_enterprise_id is null
           and (connector_id = ? or tenant_code in ('default', 'tenant-discovery'))
        """,
        (existing["id"], existing["id"], connector_id),
    )
    return existing


def dingtalk_sign(secret: str, timestamp: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), string_to_sign, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def dingtalk_payload(
    *,
    msg_id: str = "msg-1",
    user_id: str = "local-user",
    content: str = "Why is order MO20260627001 waiting material?",
) -> dict[str, object]:
    return {
        "conversationId": "conversation-1",
        "senderStaffId": user_id,
        "msgId": msg_id,
        "text": {"content": content},
        "project_code": "default",
    }
