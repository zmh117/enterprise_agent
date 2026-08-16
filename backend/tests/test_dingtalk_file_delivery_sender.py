from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from app.modules.channel.domain.channel_event import ReplyRoute
from app.modules.channel.infrastructure.connector_registry import Connector
from app.modules.delivery.infrastructure.file_delivery_sender import (
    DeliveryFileContent,
    DingTalkFileDeliverySender,
)


class _FileService:
    def get(self, delivery_id: str) -> DeliveryFileContent:
        assert delivery_id == "delivery-a"
        return DeliveryFileContent(
            display_name="result.txt",
            content=b"result\n",
            size_bytes=7,
            sha256="2e1cfa82b035c26cbd3cd0309f709f41d03c9c89ad9b60f77bc7b11d82c0a3aa",
        )


class _Registry:
    def resolve_metadata_reference(self, _connector: Connector, key: str) -> str:
        return "client-a" if key == "client_id_ref" else ""

    def metadata_value(self, _connector: Connector, _key: str) -> str:
        return ""

    def resolve_secret(self, _connector: Connector) -> str:
        return "test-secret"

    def assert_host_allowed(self, _connector: Connector, url: str) -> None:
        assert url.startswith(("https://api.dingtalk.com/", "https://oapi.dingtalk.com/"))


class _Transport:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def post_json(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        timeout_seconds: int,
    ) -> dict[str, str]:
        self.calls.append(
            {
                "url": url,
                "payload": payload,
                "headers": headers,
                "timeout_seconds": timeout_seconds,
            }
        )
        return {"code": "0"}


class _Sender(DingTalkFileDeliverySender):
    def _upload(self, **_arguments: Any) -> str:
        return "media-a"


def _connector() -> Connector:
    return Connector(
        id="connector-stream-a",
        connector_type="dingtalk_enterprise_stream",
        name="stream-a",
        base_url="",
        enabled=True,
        allow_ingress=True,
        allow_delivery=False,
        secret_ref="secret://platform/test",
        endpoint_ref="",
        host_allowlist=("api.dingtalk.com", "oapi.dingtalk.com"),
        metadata={"client_id_ref": "secret://platform/test-client-id"},
    )


@pytest.mark.parametrize(
    ("target", "endpoint_suffix", "receiver_key", "receiver_value"),
    [
        (
            {
                "conversation_type": "direct",
                "recipient_user_id": "staff-a",
                "robot_code": "",
            },
            "/v1.0/robot/oToMessages/batchSend",
            "userIds",
            ["staff-a"],
        ),
        (
            {
                "conversation_type": "group",
                "open_conversation_id": "open-conversation-a",
                "robot_code": "robot-a",
            },
            "/v1.0/robot/groupMessages/send",
            "openConversationId",
            "open-conversation-a",
        ),
    ],
)
def test_dingtalk_file_sender_routes_private_and_group_stream_results(
    target: dict[str, str],
    endpoint_suffix: str,
    receiver_key: str,
    receiver_value: object,
) -> None:
    transport = _Transport()
    sender = _Sender(
        file_service=_FileService(),  # type: ignore[arg-type]
        connector_registry=_Registry(),  # type: ignore[arg-type]
        transport=transport,
    )
    with patch(
        "app.modules.delivery.infrastructure.file_delivery_sender."
        "DingTalkAccessTokenClient"
    ) as token_client:
        token_client.return_value.access_token.return_value = "access-token"
        sender.send(
            delivery_id="delivery-a",
            connector=_connector(),
            route=ReplyRoute(
                type="dingtalk_stream_session_webhook",
                target=target,
            ),
            idempotency_key="delivery-key-a",
        )

    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert str(call["url"]).endswith(endpoint_suffix)
    payload = call["payload"]
    assert payload[receiver_key] == receiver_value
    assert payload["robotCode"] == (target.get("robot_code") or "client-a")
    assert payload["msgKey"] == "sampleFile"
    assert json.loads(str(payload["msgParam"])) == {
        "mediaId": "media-a",
        "fileName": "result.txt",
    }
