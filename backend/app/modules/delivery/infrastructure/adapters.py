from __future__ import annotations

import json
from typing import Protocol
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from app.modules.channel.domain.channel_event import ReplyRoute
from app.modules.channel.infrastructure.connector_registry import Connector, ConnectorRegistry
from app.modules.dingding.infrastructure.dingding_callback_client import DingTalkCallbackClient
from app.modules.dingding.infrastructure.dingtalk_delivery_clients import (
    DingTalkAccessTokenClient,
    DingTalkEnterpriseMessageClient,
    DingTalkWebhookRobotClient,
    JsonPostTransport,
)


class DeliveryAdapter(Protocol):
    def send(
        self, *, connector: Connector | None, route: ReplyRoute, title: str, text: str
    ) -> None:
        pass


class NoneDeliveryAdapter:
    def send(
        self, *, connector: Connector | None, route: ReplyRoute, title: str, text: str
    ) -> None:
        return


class DingTalkConversationDeliveryAdapter:
    def __init__(
        self, *, fallback_callback_url: str = "", host_allowlist: tuple[str, ...] = ()
    ) -> None:
        self.fallback_callback_url = fallback_callback_url
        self.host_allowlist = host_allowlist
        self.sent_messages: list[dict[str, str]] = []

    def send(
        self, *, connector: Connector | None, route: ReplyRoute, title: str, text: str
    ) -> None:
        callback_url = (
            connector.base_url if connector and connector.base_url else self.fallback_callback_url
        )
        host_allowlist = connector.host_allowlist if connector else self.host_allowlist
        conversation_id = str(
            route.target.get("conversation_id") or route.target.get("webhook_id") or ""
        )
        client = DingTalkCallbackClient(callback_url=callback_url, host_allowlist=host_allowlist)
        client.send_markdown(conversation_id=conversation_id, title=title, text=text)
        self.sent_messages.extend(client.sent_messages)


class DingTalkEnterpriseAppDeliveryAdapter:
    def __init__(
        self,
        *,
        connector_registry: ConnectorRegistry,
        transport: JsonPostTransport | None = None,
        timeout_seconds: int = 5,
    ) -> None:
        self.connector_registry = connector_registry
        self.transport = transport
        self.timeout_seconds = timeout_seconds
        self.sent_messages: list[dict[str, str]] = []
        self._token_clients: dict[str, DingTalkAccessTokenClient] = {}

    def send(
        self, *, connector: Connector | None, route: ReplyRoute, title: str, text: str
    ) -> None:
        if connector is None:
            raise ValueError("DingTalk enterprise connector is required")
        client_id = self.connector_registry.resolve_metadata_reference(connector, "client_id_ref")
        client_id = client_id or self.connector_registry.metadata_value(connector, "client_id")
        client_secret = self.connector_registry.resolve_secret(connector)
        token_url = (
            self.connector_registry.resolve_metadata_reference(connector, "token_url_ref")
            or self.connector_registry.metadata_value(connector, "token_url")
            or "https://api.dingtalk.com/v1.0/oauth2/accessToken"
        )
        send_url = (
            self.connector_registry.resolve_metadata_reference(connector, "send_url_ref")
            or self.connector_registry.metadata_value(connector, "send_url")
            or "https://api.dingtalk.com/v1.0/robot/groupMessages/send"
        )
        token_client = self._token_client(
            connector_id=connector.id,
            client_id=client_id,
            client_secret=client_secret,
            token_url=token_url,
        )
        message_client = DingTalkEnterpriseMessageClient(
            token_client=token_client,
            transport=self.transport,
            send_url=send_url,
            timeout_seconds=self.timeout_seconds,
        )
        open_conversation_id = str(
            route.target.get("open_conversation_id")
            or route.target.get("conversation_id")
            or self.connector_registry.metadata_value(connector, "default_open_conversation_id")
        )
        robot_code = str(
            route.target.get("robot_code")
            or self.connector_registry.metadata_value(connector, "default_robot_code")
        )
        message_client.send_markdown(
            open_conversation_id=open_conversation_id,
            robot_code=robot_code,
            title=title,
            text=text,
        )
        self.sent_messages.extend(
            {
                "title": item["title"],
                "open_conversation_id": item["open_conversation_id"],
                "robot_code": item["robot_code"],
            }
            for item in message_client.sent_messages
        )

    def _token_client(
        self, *, connector_id: str, client_id: str, client_secret: str, token_url: str
    ) -> DingTalkAccessTokenClient:
        cached = self._token_clients.get(connector_id)
        if cached is not None:
            return cached
        client = DingTalkAccessTokenClient(
            client_id=client_id,
            client_secret=client_secret,
            transport=self.transport,
            token_url=token_url,
            timeout_seconds=self.timeout_seconds,
        )
        self._token_clients[connector_id] = client
        return client


class DingTalkWebhookRobotDeliveryAdapter:
    def __init__(
        self,
        *,
        connector_registry: ConnectorRegistry,
        transport: JsonPostTransport | None = None,
        timeout_seconds: int = 5,
    ) -> None:
        self.connector_registry = connector_registry
        self.transport = transport
        self.timeout_seconds = timeout_seconds
        self.sent_messages: list[dict[str, str]] = []

    def send(
        self, *, connector: Connector | None, route: ReplyRoute, title: str, text: str
    ) -> None:
        if connector is None:
            raise ValueError("DingTalk webhook robot connector is required")
        webhook_url = self.connector_registry.endpoint_url(connector)
        self.connector_registry.assert_host_allowed(connector, webhook_url)
        client = DingTalkWebhookRobotClient(
            webhook_url=webhook_url,
            secret=self.connector_registry.resolve_secret(connector),
            transport=self.transport,
            timeout_seconds=self.timeout_seconds,
        )
        at_mobiles = _string_list(route.target.get("at_mobiles"))
        at_user_ids = _string_list(route.target.get("at_user_ids"))
        is_at_all = _bool_value(route.target.get("is_at_all"))
        client.send_markdown(
            title=title,
            text=text,
            at_mobiles=at_mobiles,
            at_user_ids=at_user_ids,
            is_at_all=is_at_all,
        )
        self.sent_messages.extend(
            {"title": str(item["title"]), "route_type": route.type} for item in client.sent_messages
        )


class HttpDeliveryAdapter:
    def __init__(self, *, timeout_seconds: int = 5) -> None:
        self.timeout_seconds = timeout_seconds
        self.sent_messages: list[dict[str, str]] = []

    def send(
        self, *, connector: Connector | None, route: ReplyRoute, title: str, text: str
    ) -> None:
        url = connector.base_url if connector else ""
        if not url:
            self.sent_messages.append({"title": title, "text": text, "route_type": route.type})
            return
        payload = {"title": title, "text": text, "target": route.target}
        self.sent_messages.append({"title": title, "text": text, "route_type": route.type})
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"content-type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            response.read()


def host_from_url(url: str) -> str:
    return urlparse(url).hostname or ""


def _string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str) and value:
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def _bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return False
