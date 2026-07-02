from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any

from app.modules.channel.application.channel_ingress_service import ChannelIngressService
from app.modules.channel.domain.channel_event import (
    ChannelEvent,
    ChannelSource,
    ReplyRoute,
    RoutingContext,
    safe_payload_summary,
)
from app.modules.dingding.infrastructure.dingding_callback_client import DingTalkCallbackClient
from app.shared.exceptions import PermissionDenied


@dataclass(frozen=True)
class DingTalkIncomingMessage:
    conversation_id: str
    user_id: str
    message_id: str
    content: str
    project_code: str = "default"
    source: str = "dingding"


class DingTalkMessageService:
    def __init__(
        self,
        *,
        secret: str,
        channel_ingress_service: ChannelIngressService,
        callback_client: DingTalkCallbackClient,
        default_delivery_type: str = "dingtalk_enterprise_robot",
        default_delivery_connector_id: str = "connector-dingtalk-enterprise-default",
        default_source_connector_id: str = "connector-dingtalk-enterprise-default",
        default_project_code: str = "default",
        default_environment: str = "",
        default_base: str = "",
        default_workshop: str = "",
        default_service: str = "",
        default_open_conversation_id: str = "",
        default_robot_code: str = "",
    ) -> None:
        self.secret = secret
        self.channel_ingress_service = channel_ingress_service
        self.callback_client = callback_client
        self.default_delivery_type = default_delivery_type
        self.default_delivery_connector_id = default_delivery_connector_id
        self.default_source_connector_id = default_source_connector_id
        self.default_project_code = default_project_code
        self.default_environment = default_environment
        self.default_base = default_base
        self.default_workshop = default_workshop
        self.default_service = default_service
        self.default_open_conversation_id = default_open_conversation_id
        self.default_robot_code = default_robot_code

    def verify_signature(self, *, timestamp: str, sign: str) -> bool:
        if not self.secret:
            return False
        string_to_sign = f"{timestamp}\n{self.secret}".encode("utf-8")
        digest = hmac.new(self.secret.encode("utf-8"), string_to_sign, hashlib.sha256).digest()
        expected = base64.b64encode(digest).decode("utf-8")
        return hmac.compare_digest(expected, sign)

    def parse_message(self, payload: dict[str, Any]) -> DingTalkIncomingMessage:
        text = payload.get("text", {})
        content = text.get("content") if isinstance(text, dict) else payload.get("content")
        if not content:
            content = payload.get("message", "")
        conversation_id = (
            payload.get("conversationId")
            or payload.get("conversation_id")
            or payload.get("conversationTitle")
            or "unknown-conversation"
        )
        user_id = payload.get("senderStaffId") or payload.get("senderId") or payload.get("user_id")
        message_id = payload.get("msgId") or payload.get("message_id")
        project_code = payload.get("project_code") or self.default_project_code
        if not user_id or not message_id:
            raise ValueError("DingTalk payload missing sender or message id")
        return DingTalkIncomingMessage(
            conversation_id=str(conversation_id),
            user_id=str(user_id),
            message_id=str(message_id),
            content=str(content).strip(),
            project_code=str(project_code),
        )

    def handle_webhook(
        self,
        *,
        payload: dict[str, Any],
        timestamp: str,
        sign: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        if not self.verify_signature(timestamp=timestamp, sign=sign):
            return {"accepted": False, "status": "invalid_signature"}
        message = self.parse_message(payload)
        delivery = ReplyRoute(
            type=str(payload.get("delivery_type") or self.default_delivery_type),
            connector_id=str(
                payload.get("delivery_connector_id") or self.default_delivery_connector_id
            ),
            target={
                "conversation_id": message.conversation_id,
                "open_conversation_id": self.default_open_conversation_id,
                "robot_code": self.default_robot_code,
                **_dict_value(payload.get("delivery_target")),
            },
        )
        source_connector_id = str(
            payload.get("source_connector_id") or self.default_source_connector_id
        )
        routing_payload = _dict_value(payload.get("routing"))
        event = ChannelEvent(
            source=ChannelSource(
                type=message.source,
                connector_id=source_connector_id,
                event_id=message.message_id,
                actor_id=message.user_id,
                conversation_id=message.conversation_id,
            ),
            delivery=delivery,
            routing=RoutingContext(
                project_code=str(routing_payload.get("project_code") or message.project_code),
                environment=str(routing_payload.get("environment") or self.default_environment),
                base=str(routing_payload.get("base") or self.default_base),
                workshop=str(routing_payload.get("workshop") or self.default_workshop),
                service=str(routing_payload.get("service") or self.default_service),
            ),
            message=message.content,
            raw_payload_summary=safe_payload_summary(payload),
            idempotency_key=f"dingding:{message.message_id}",
            correlation_id=correlation_id,
        )
        try:
            job = self.channel_ingress_service.accept(event)
        except PermissionDenied as exc:
            return {"accepted": False, "status": "permission_denied", "message": exc.safe_message}
        return {
            "accepted": True,
            "status": "received",
            "job_id": job.id,
            "message": "Task accepted, analysis is starting.",
        }

    def send_final_result(self, conversation_id: str, report: str) -> None:
        self.callback_client.send_markdown(
            conversation_id=conversation_id, title="Agent analysis", text=report
        )

    def safe_failure_notice(self, reason: str) -> str:
        return json.dumps({"status": "failed", "reason": reason}, ensure_ascii=False)


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
