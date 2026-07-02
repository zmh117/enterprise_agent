from __future__ import annotations

import json
from typing import Protocol
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from app.modules.channel.domain.channel_event import ReplyRoute
from app.modules.channel.infrastructure.connector_registry import Connector
from app.modules.dingding.infrastructure.dingding_callback_client import DingTalkCallbackClient


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


class DingTalkDeliveryAdapter:
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
