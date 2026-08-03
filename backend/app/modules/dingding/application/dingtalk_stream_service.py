from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from collections.abc import Callable
from typing import Any, Protocol

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
from app.modules.channel.infrastructure.connector_registry import ConnectorRegistry
from app.modules.identity.domain import ExternalIdentityDescriptor
from app.modules.identity_discovery.application import (
    DingTalkIdentityDiscoveryService,
)
from app.modules.identity_discovery.domain import PendingDingTalkIdentityObservation
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
    union_id: str = ""
    open_id: str = ""
    sender_corp_id: str = ""
    chatbot_corp_id: str = ""
    occurred_at: str = ""


@dataclass(frozen=True)
class DingTalkStreamHandleResult:
    accepted: bool
    status: str
    ack_status: str
    ack_message: str
    job_id: str = ""
    reason: str = ""
    error_code: str = ""
    discovery_observation: PendingDingTalkIdentityObservation | None = None
    rejection_message: DingTalkStreamIncomingMessage | None = None
    rejection_connector_id: str = ""


class UnsupportedDingTalkStreamEvent(ValueError):
    pass


class RejectedDingTalkStreamMessage(ValueError):
    def __init__(
        self,
        reason: str,
        *,
        message: DingTalkStreamIncomingMessage | None = None,
        error_code: str = "",
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.message = message
        self.error_code = error_code


class DingTalkStreamRejectionNotifier(Protocol):
    def notify(
        self,
        *,
        conversation_id: str,
        session_webhook: str,
        session_webhook_expires: str,
        sender_user_id: str,
        reason: str,
    ) -> bool: ...


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
        connector_registry: ConnectorRegistry | None = None,
        default_tenant_code: str = "default",
        rejection_notifier: DingTalkStreamRejectionNotifier | None = None,
        identity_discovery_service: DingTalkIdentityDiscoveryService | None = None,
        enterprise_connector_resolver: Callable[[str], dict[str, Any]] | None = None,
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
        self.connector_registry = connector_registry
        self.default_tenant_code = default_tenant_code
        self.rejection_notifier = rejection_notifier
        self.identity_discovery_service = identity_discovery_service
        self.enterprise_connector_resolver = enterprise_connector_resolver

    def handle_callback(
        self,
        *,
        payload: dict[str, Any],
        correlation_id: str,
        connector_id: str | None = None,
        defer_rejection_notification: bool = False,
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
            if not defer_rejection_notification and exc.message is not None:
                self._notify_rejection(
                    message=exc.message,
                    reason=exc.reason,
                    connector_id=source_connector_id,
                )
            return DingTalkStreamHandleResult(
                accepted=False,
                status="rejected",
                ack_status="OK",
                ack_message="REJECTED",
                reason=exc.reason,
                error_code=exc.error_code or "dingtalk_stream_message_rejected",
                rejection_message=(
                    exc.message if defer_rejection_notification else None
                ),
                rejection_connector_id=(
                    source_connector_id
                    if defer_rejection_notification and exc.message is not None
                    else ""
                ),
            )

        event: ChannelEvent | None = None
        try:
            event = self.to_channel_event(
                message=message,
                payload=payload,
                source_connector_id=source_connector_id,
                correlation_id=correlation_id,
            )
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
            if not defer_rejection_notification:
                self._notify_rejection(
                    message=message,
                    reason=exc.safe_message,
                    connector_id=source_connector_id,
                )
            observation = (
                self.identity_discovery_service.build_pending_observation(
                    event=event,
                    message_kind=payload.get("msgtype")
                    or payload.get("messageType"),
                    occurred_at=payload.get("createAt")
                    or payload.get("create_at"),
                )
                if event is not None
                and self.identity_discovery_service is not None
                and self.identity_discovery_service.is_discoverable_rejection(
                    exc.error_code
                )
                else None
            )
            return DingTalkStreamHandleResult(
                accepted=False,
                status="permission_denied",
                ack_status="OK",
                ack_message="PERMISSION_DENIED",
                reason=exc.safe_message,
                error_code=exc.error_code or "permission_denied",
                discovery_observation=observation,
                rejection_message=message if defer_rejection_notification else None,
                rejection_connector_id=(
                    source_connector_id if defer_rejection_notification else ""
                ),
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
                payload={
                    "connector_id": source_connector_id,
                    "event_id": message.event_id,
                    "correlation_id": correlation_id,
                    "reason_code": exc.error_code or "non_retryable_execution_error",
                },
            )
            if not defer_rejection_notification:
                self._notify_rejection(
                    message=message,
                    reason=exc.safe_message,
                    connector_id=source_connector_id,
                )
            return DingTalkStreamHandleResult(
                accepted=False,
                status="rejected",
                ack_status="OK",
                ack_message="REJECTED",
                reason=exc.safe_message,
                error_code=exc.error_code or "non_retryable_execution_error",
                rejection_message=message if defer_rejection_notification else None,
                rejection_connector_id=(
                    source_connector_id if defer_rejection_notification else ""
                ),
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
            ack_message="任务已受理，正在开始分析",
            job_id=job.id,
        )

    def notify_deferred_rejection(self, result: DingTalkStreamHandleResult) -> None:
        if result.rejection_message is None:
            return
        self._notify_rejection(
            message=result.rejection_message,
            reason=result.reason,
            connector_id=result.rejection_connector_id,
        )

    def _notify_rejection(
        self,
        *,
        message: DingTalkStreamIncomingMessage,
        reason: str,
        connector_id: str,
    ) -> None:
        if self.rejection_notifier is None:
            return
        try:
            delivered = self.rejection_notifier.notify(
                conversation_id=message.conversation_id,
                session_webhook=message.session_webhook,
                session_webhook_expires=message.session_webhook_expired_time,
                sender_user_id=(message.user_id if message.conversation_type == "group" else ""),
                reason=reason,
            )
        except Exception as exc:
            self.audit_service.record(
                "dingtalk.stream.rejection_delivery_failed",
                status="FAILED",
                summary=str(getattr(exc, "safe_message", "钉钉拒绝通知投递失败")),
                actor_id=message.user_id,
                payload={
                    "connector_id": connector_id,
                    "event_id": message.event_id,
                },
            )
            return
        self.audit_service.record(
            "dingtalk.stream.rejection_delivered"
            if delivered
            else "dingtalk.stream.rejection_delivery_unavailable",
            status="SUCCEEDED" if delivered else "SKIPPED",
            summary=(
                "DingTalk rejection delivered to original session"
                if delivered
                else "DingTalk session webhook is unavailable"
            ),
            actor_id=message.user_id,
            payload={
                "connector_id": connector_id,
                "event_id": message.event_id,
            },
        )

    def parse_message(self, payload: dict[str, Any]) -> DingTalkStreamIncomingMessage:
        content = (_text_content(payload) or "").strip()
        attachments = (
            _attachments(payload, credential_ttl_seconds=self.attachment_credential_ttl_seconds)
            if self.attachments_enabled
            else ()
        )
        rich_text_without_supported_content = (
            not content
            and not attachments
            and _first_text(payload, "msgtype", "messageType").lower() == "richtext"
        )
        if not content and not attachments and not rich_text_without_supported_content:
            raise UnsupportedDingTalkStreamEvent("Unsupported DingTalk Stream event")

        conversation_id = _first_text(
            payload,
            "conversationId",
            "conversation_id",
            "openConversationId",
            "open_conversation_id",
            "conversationTitle",
        )
        staff_id = _first_text(
            payload,
            "senderStaffId",
            "sender_staff_id",
        )
        sender_id = _first_text(
            payload,
            "senderId",
            "sender_id",
            "user_id",
            "userId",
        )
        user_id = staff_id or sender_id
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
        union_id = _first_text(payload, "senderUnionId", "unionId", "union_id")
        open_id = _first_text(payload, "senderOpenId", "openId", "open_id", "senderId")
        sender_corp_id = _first_text(payload, "senderCorpId", "sender_corp_id")
        chatbot_corp_id = _first_text(payload, "chatbotCorpId", "chatbot_corp_id")
        occurred_at = _first_text(payload, "createAt", "create_at", "timestamp")

        if not conversation_id:
            raise RejectedDingTalkStreamMessage("DingTalk Stream payload missing conversation id")
        if not user_id:
            raise RejectedDingTalkStreamMessage("DingTalk Stream payload missing sender id")
        if not message_id and not event_id:
            raise RejectedDingTalkStreamMessage("DingTalk Stream payload missing message id")

        message_id = message_id or event_id
        event_id = event_id or message_id
        message = DingTalkStreamIncomingMessage(
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
            union_id=union_id,
            open_id=open_id,
            sender_corp_id=sender_corp_id,
            chatbot_corp_id=chatbot_corp_id,
            occurred_at=occurred_at,
        )
        if rich_text_without_supported_content:
            raise RejectedDingTalkStreamMessage(
                "暂时无法读取这条钉钉富文本消息，请改用纯文本后重试",
                message=message,
                error_code="unsupported_rich_text_content",
            )
        return message

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
        tenant_code = self.default_tenant_code
        dingtalk_enterprise_id = ""
        connector_bot_identity = ""
        if self.connector_registry is not None:
            connector = self.connector_registry.require_dingtalk_stream_ingress(source_connector_id)
            connector_bot_identity = self.connector_registry.metadata_value(
                connector, "default_robot_code"
            )
        if self.enterprise_connector_resolver is not None:
            governed = self.enterprise_connector_resolver(source_connector_id)
            dingtalk_enterprise_id = str(
                governed.get("dingtalk_enterprise_id") or ""
            )
            if (
                not dingtalk_enterprise_id
                or str(governed.get("dingtalk_enterprise_status") or "") != "ACTIVE"
            ):
                raise PermissionDenied(
                    "DingTalk enterprise is not active",
                    safe_message="钉钉企业尚未完成验证或已停用",
                    error_code="dingtalk_enterprise_unavailable",
                )
            expected_corp_id = str(
                governed.get("dingtalk_enterprise_corp_id") or ""
            )
            if (
                not message.sender_corp_id
                or not message.chatbot_corp_id
                or message.sender_corp_id != message.chatbot_corp_id
                or message.sender_corp_id != expected_corp_id
            ):
                raise PermissionDenied(
                    "DingTalk Corp ID does not match governed enterprise",
                    safe_message="消息所属钉钉企业与应用连接不一致",
                    error_code="dingtalk_corp_id_mismatch",
                )
            tenant_code = dingtalk_enterprise_id
        else:
            dingtalk_enterprise_id = tenant_code
        bot_identity = (
            message.bot_identity
            or message.robot_code
            or connector_bot_identity
            or self.default_robot_code
        )
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
                    "bot_identity": bot_identity,
                    "source_ingress_event_id": str(
                        payload.get("_source_ingress_event_id") or ""
                    ),
                    "received_at": str(payload.get("_received_at") or ""),
                    "occurred_at": message.occurred_at,
                },
                external_identity=ExternalIdentityDescriptor(
                    provider="dingtalk",
                    tenant_code=tenant_code,
                    external_subject_id=message.user_id,
                    connector_id=source_connector_id,
                    union_id=message.union_id,
                    open_id=message.open_id,
                    display_name=message.sender_display_name,
                    dingtalk_enterprise_id=dingtalk_enterprise_id,
                    source_ingress_event_id=str(
                        payload.get("_source_ingress_event_id") or ""
                    ),
                    occurred_at=message.occurred_at,
                    received_at=str(payload.get("_received_at") or ""),
                ),
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
        mention_target = _reply_mention_target(message)
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
                    **mention_target,
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
                    **mention_target,
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
                **mention_target,
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

    content = payload.get("content")
    if isinstance(content, dict):
        rich_text = content.get("richText") or content.get("richtext")
        if isinstance(rich_text, list):
            fragments: list[str] = []
            for item in rich_text:
                if isinstance(item, str):
                    fragments.append(item)
                    continue
                if not isinstance(item, dict):
                    continue
                fragment = item.get("text") or item.get("content")
                if isinstance(fragment, str):
                    fragments.append(fragment)
            return "".join(fragments)
        nested_text = content.get("content") or content.get("text")
        if isinstance(nested_text, str):
            return nested_text

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


def _reply_mention_target(message: DingTalkStreamIncomingMessage) -> dict[str, list[str]]:
    if message.conversation_type != "group":
        return {}
    return {"at_user_ids": [message.user_id]}


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
