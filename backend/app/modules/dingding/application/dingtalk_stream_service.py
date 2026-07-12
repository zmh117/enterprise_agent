from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.modules.audit.application.audit_service import AuditService
from app.modules.channel.application.channel_ingress_service import ChannelIngressService
from app.modules.channel.domain.channel_event import (
    ChannelAttachment,
    ChannelEvent,
    ChannelSource,
    ReplyRoute,
    RoutingContext,
    safe_payload_summary,
)
from app.shared.exceptions import NonRetryableExecutionError, PermissionDenied

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DingTalkStreamIncomingMessage:
    conversation_id: str
    user_id: str
    message_id: str
    event_id: str
    content: str
    sender_display_name: str = ""
    open_conversation_id: str = ""
    robot_code: str = ""
    session_webhook: str = ""
    session_webhook_expired_time: str = ""
    conversation_type: str = "direct"
    bot_identity: str = ""
    attachments: tuple[ChannelAttachment, ...] = ()


@dataclass(frozen=True)
class DingTalkStreamHandleResult:
    accepted: bool
    status: str
    ack_status: str
    ack_message: str
    job_id: str = ""
    reason: str = ""


class UnsupportedDingTalkStreamEvent(ValueError):
    pass


class RejectedDingTalkStreamMessage(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class DingTalkStreamMessageService:
    def __init__(
        self,
        *,
        channel_ingress_service: ChannelIngressService,
        audit_service: AuditService,
        default_source_connector_id: str = "connector-dingtalk-stream-default",
        default_delivery_type: str = "dingtalk_enterprise_robot",
        default_delivery_connector_id: str = "connector-dingtalk-enterprise-default",
        default_project_code: str = "default",
        default_environment: str = "",
        default_base: str = "",
        default_workshop: str = "",
        default_service: str = "",
        default_open_conversation_id: str = "",
        default_robot_code: str = "",
        attachments_enabled: bool = False,
        attachment_credential_ttl_seconds: int = 900,
    ) -> None:
        self.channel_ingress_service = channel_ingress_service
        self.audit_service = audit_service
        self.default_source_connector_id = default_source_connector_id
        self.default_delivery_type = default_delivery_type
        self.default_delivery_connector_id = default_delivery_connector_id
        self.default_project_code = default_project_code
        self.default_environment = default_environment
        self.default_base = default_base
        self.default_workshop = default_workshop
        self.default_service = default_service
        self.default_open_conversation_id = default_open_conversation_id
        self.default_robot_code = default_robot_code
        self.attachments_enabled = attachments_enabled
        self.attachment_credential_ttl_seconds = attachment_credential_ttl_seconds

    def handle_callback(
        self,
        *,
        payload: dict[str, Any],
        correlation_id: str,
        connector_id: str | None = None,
    ) -> DingTalkStreamHandleResult:
        source_connector_id = connector_id or self.default_source_connector_id
        self.audit_service.record(
            "dingtalk.stream.received",
            status="STARTED",
            summary="DingTalk Stream event received",
            actor_id=source_connector_id,
            payload={
                "connector_id": source_connector_id,
                "payload": safe_payload_summary(payload),
            },
        )
        logger.info(
            "DingTalk Stream event received connector_id=%s payload_keys=%s",
            source_connector_id,
            sorted(payload.keys()),
        )
        try:
            message = self.parse_message(payload)
        except UnsupportedDingTalkStreamEvent as exc:
            self.audit_service.record(
                "dingtalk.stream.ignored",
                status="SKIPPED",
                summary=str(exc),
                actor_id=source_connector_id,
                payload={"connector_id": source_connector_id},
            )
            return DingTalkStreamHandleResult(
                accepted=False,
                status="ignored",
                ack_status="OK",
                ack_message="IGNORED",
                reason=str(exc),
            )
        except RejectedDingTalkStreamMessage as exc:
            logger.info(
                "DingTalk Stream message rejected connector_id=%s reason=%s",
                source_connector_id,
                exc.reason,
            )
            self.audit_service.record(
                "dingtalk.stream.rejected",
                status="FAILED",
                summary=exc.reason,
                actor_id=source_connector_id,
                payload={
                    "connector_id": source_connector_id,
                    "payload": safe_payload_summary(payload),
                },
            )
            return DingTalkStreamHandleResult(
                accepted=False,
                status="rejected",
                ack_status="OK",
                ack_message="REJECTED",
                reason=exc.reason,
            )

        event = self.to_channel_event(
            message=message,
            payload=payload,
            source_connector_id=source_connector_id,
            correlation_id=correlation_id,
        )
        try:
            job = self.channel_ingress_service.accept(event)
        except PermissionDenied as exc:
            logger.info(
                "DingTalk Stream permission denied connector_id=%s actor_id=%s event_id=%s",
                source_connector_id,
                message.user_id,
                message.event_id,
            )
            self.audit_service.record(
                "dingtalk.stream.permission_denied",
                status="DENIED",
                summary=exc.safe_message,
                actor_id=message.user_id,
                payload={"connector_id": source_connector_id, "event_id": message.event_id},
            )
            return DingTalkStreamHandleResult(
                accepted=False,
                status="permission_denied",
                ack_status="OK",
                ack_message="PERMISSION_DENIED",
                reason=exc.safe_message,
            )
        except NonRetryableExecutionError as exc:
            logger.info(
                "DingTalk Stream message rejected connector_id=%s actor_id=%s event_id=%s reason=%s",
                source_connector_id,
                message.user_id,
                message.event_id,
                exc.safe_message,
            )
            self.audit_service.record(
                "dingtalk.stream.rejected",
                status="FAILED",
                summary=exc.safe_message,
                actor_id=message.user_id,
                payload={"connector_id": source_connector_id, "event_id": message.event_id},
            )
            return DingTalkStreamHandleResult(
                accepted=False,
                status="rejected",
                ack_status="OK",
                ack_message="REJECTED",
                reason=exc.safe_message,
            )

        self.audit_service.record(
            "dingtalk.stream.ack",
            status="SUCCEEDED",
            summary="DingTalk Stream message accepted",
            job_id=job.id,
            actor_id=message.user_id,
            payload={"connector_id": source_connector_id, "event_id": message.event_id},
        )
        logger.info(
            "DingTalk Stream message accepted connector_id=%s actor_id=%s event_id=%s job_id=%s",
            source_connector_id,
            message.user_id,
            message.event_id,
            job.id,
        )
        return DingTalkStreamHandleResult(
            accepted=True,
            status="received",
            ack_status="OK",
            ack_message="Task accepted, analysis is starting.",
            job_id=job.id,
        )

    def parse_message(self, payload: dict[str, Any]) -> DingTalkStreamIncomingMessage:
        content = (_text_content(payload) or "").strip()
        attachments = (
            _attachments(payload, credential_ttl_seconds=self.attachment_credential_ttl_seconds)
            if self.attachments_enabled
            else ()
        )
        if not content and not attachments:
            raise UnsupportedDingTalkStreamEvent("Unsupported DingTalk Stream event")

        conversation_id = _first_text(
            payload,
            "conversationId",
            "conversation_id",
            "openConversationId",
            "open_conversation_id",
            "conversationTitle",
        )
        user_id = _first_text(
            payload,
            "senderStaffId",
            "sender_staff_id",
            "senderId",
            "sender_id",
            "user_id",
            "userId",
        )
        message_id = _first_text(payload, "msgId", "msg_id", "messageId", "message_id")
        event_id = _first_text(payload, "eventId", "event_id", "event_idempotent_id")
        sender_display_name = _first_text(payload, "senderNick", "sender_nick", "senderName")
        open_conversation_id = _first_text(
            payload, "openConversationId", "open_conversation_id", "conversationId"
        )
        robot_code = _first_text(payload, "robotCode", "robot_code")
        session_webhook = _first_text(payload, "sessionWebhook", "session_webhook")
        session_webhook_expired_time = _first_text(
            payload,
            "sessionWebhookExpiredTime",
            "session_webhook_expired_time",
        )
        raw_conversation_type = _first_text(payload, "conversationType", "conversation_type")
        conversation_type = "group" if raw_conversation_type == "2" else "direct"
        bot_identity = _first_text(payload, "robotCode", "chatbotUserId", "chatbot_user_id")

        if not conversation_id:
            raise RejectedDingTalkStreamMessage("DingTalk Stream payload missing conversation id")
        if not user_id:
            raise RejectedDingTalkStreamMessage("DingTalk Stream payload missing sender id")
        if not message_id and not event_id:
            raise RejectedDingTalkStreamMessage("DingTalk Stream payload missing message id")

        message_id = message_id or event_id
        event_id = event_id or message_id
        return DingTalkStreamIncomingMessage(
            conversation_id=conversation_id,
            user_id=user_id,
            message_id=message_id,
            event_id=event_id,
            content=content,
            sender_display_name=sender_display_name,
            open_conversation_id=open_conversation_id,
            robot_code=robot_code,
            session_webhook=session_webhook,
            session_webhook_expired_time=session_webhook_expired_time,
            conversation_type=conversation_type,
            bot_identity=bot_identity,
            attachments=attachments,
        )

    def to_channel_event(
        self,
        *,
        message: DingTalkStreamIncomingMessage,
        payload: dict[str, Any],
        source_connector_id: str,
        correlation_id: str,
    ) -> ChannelEvent:
        routing_payload = _dict_value(payload.get("routing"))
        delivery_payload = _dict_value(payload.get("delivery"))
        delivery = self._reply_route(message=message, delivery_payload=delivery_payload)
        return ChannelEvent(
            source=ChannelSource(
                type="dingding_stream",
                connector_id=source_connector_id,
                event_id=message.event_id,
                actor_id=message.user_id,
                conversation_id=message.conversation_id,
                metadata={
                    "display_name": message.sender_display_name,
                    "message_id": message.message_id,
                    "open_conversation_id": message.open_conversation_id,
                    "robot_code": message.robot_code,
                    "session_webhook_expires": message.session_webhook_expired_time,
                    "conversation_type": message.conversation_type,
                    "bot_identity": message.bot_identity,
                },
            ),
            delivery=delivery,
            routing=RoutingContext(
                project_code=str(routing_payload.get("project_code") or self.default_project_code),
                environment=str(routing_payload.get("environment") or self.default_environment),
                base=str(routing_payload.get("base") or self.default_base),
                workshop=str(routing_payload.get("workshop") or self.default_workshop),
                service=str(routing_payload.get("service") or self.default_service),
            ),
            message=message.content,
            attachments=message.attachments,
            raw_payload_summary=safe_payload_summary(payload),
            idempotency_key=f"dingding_stream:{source_connector_id}:{message.event_id}",
            correlation_id=correlation_id,
        )

    def _reply_route(
        self,
        *,
        message: DingTalkStreamIncomingMessage,
        delivery_payload: dict[str, Any],
    ) -> ReplyRoute:
        delivery_target = _dict_value(delivery_payload.get("target"))
        if delivery_payload.get("type"):
            return ReplyRoute(
                type=str(delivery_payload.get("type")),
                connector_id=str(delivery_payload.get("connector_id") or ""),
                target={
                    "conversation_id": message.conversation_id,
                    "open_conversation_id": (
                        message.open_conversation_id or self.default_open_conversation_id
                    ),
                    "robot_code": message.robot_code or self.default_robot_code,
                    **delivery_target,
                },
                options=_dict_value(delivery_payload.get("options")),
            )
        if message.session_webhook:
            return ReplyRoute(
                type="dingtalk_stream_session_webhook",
                connector_id="",
                target={
                    "conversation_id": message.conversation_id,
                    "session_webhook": message.session_webhook,
                    "session_webhook_expired_time": message.session_webhook_expired_time,
                },
                options=_dict_value(delivery_payload.get("options")),
            )
        return ReplyRoute(
            type=self.default_delivery_type,
            connector_id=self.default_delivery_connector_id,
            target={
                "conversation_id": message.conversation_id,
                "open_conversation_id": (
                    message.open_conversation_id or self.default_open_conversation_id
                ),
                "robot_code": message.robot_code or self.default_robot_code,
                **delivery_target,
            },
            options=_dict_value(delivery_payload.get("options")),
        )


def _text_content(payload: dict[str, Any]) -> str | None:
    text = payload.get("text")
    if isinstance(text, dict):
        content = text.get("content") or text.get("text")
        return str(content) if content is not None else None
    if isinstance(text, str):
        return text
    for key in ("content", "message", "message_text"):
        value = payload.get(key)
        if isinstance(value, str):
            return str(value)
    return None


def _first_text(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _attachments(
    payload: dict[str, Any], *, credential_ttl_seconds: int
) -> tuple[ChannelAttachment, ...]:
    msgtype = _first_text(payload, "msgtype", "messageType").lower()
    raw_items: list[dict[str, Any]] = []
    if msgtype in {"picture", "image"}:
        raw_items = [_dict_value(payload.get("content") or payload.get("image") or payload)]
    elif msgtype in {"file", "document"}:
        raw_items = [_dict_value(payload.get("content") or payload.get("file") or payload)]
    elif msgtype == "richtext":
        rich = _dict_value(payload.get("content") or payload).get("richText") or []
        raw_items = [item for item in rich if isinstance(item, dict) and item.get("downloadCode")]
    result: list[ChannelAttachment] = []
    for index, item in enumerate(raw_items, start=1):
        download_code = str(item.get("downloadCode") or "")
        if not download_code:
            continue
        file_name = str(
            item.get("fileName")
            or item.get("filename")
            or (f"image-{index}.png" if msgtype in {"picture", "image", "richtext"} else "")
        )
        if not file_name:
            continue
        suffix = file_name.lower().rsplit(".", 1)[-1] if "." in file_name else ""
        media_type = "image" if suffix in {"jpg", "jpeg", "png", "webp"} else "document"
        result.append(
            ChannelAttachment(
                media_type=media_type,
                file_name=file_name,
                source_credential=download_code,
                declared_mime=str(item.get("contentType") or item.get("mimeType") or ""),
                declared_size=(int(item["fileSize"]) if item.get("fileSize") is not None else None),
                source_credential_expires_at=(
                    datetime.now(UTC) + timedelta(seconds=credential_ttl_seconds)
                ).isoformat(),
            )
        )
    return tuple(result)
