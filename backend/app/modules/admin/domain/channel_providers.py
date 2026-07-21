from __future__ import annotations

from typing import Any


CHANNEL_PROVIDERS: tuple[dict[str, Any], ...] = (
    {
        "code": "dingtalk_enterprise_stream",
        "name": "DingTalk Stream",
        "available": True,
        "directions": ["ingress"],
        "required": ["secret_ref", "metadata.client_id_ref", "metadata.tenant_code"],
    },
    {
        "code": "dingtalk_callback",
        "name": "DingTalk Callback",
        "available": True,
        "directions": ["ingress"],
        "required": ["secret_ref", "host_allowlist"],
    },
    {
        "code": "dingtalk_enterprise_robot",
        "name": "DingTalk Enterprise Delivery",
        "available": True,
        "directions": ["delivery"],
        "required": ["secret_ref", "metadata.client_id_ref", "host_allowlist"],
    },
    {
        "code": "dingtalk_webhook_robot",
        "name": "DingTalk Webhook Delivery",
        "available": True,
        "directions": ["delivery"],
        "required": ["secret_ref", "endpoint_ref", "host_allowlist"],
    },
    {
        "code": "email",
        "name": "Email",
        "available": False,
        "directions": ["delivery"],
        "required": [],
    },
    {
        "code": "wecom",
        "name": "WeCom",
        "available": False,
        "directions": ["ingress", "delivery"],
        "required": [],
    },
)
