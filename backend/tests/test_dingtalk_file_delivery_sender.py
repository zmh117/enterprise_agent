from __future__ import annotations

import base64
import hashlib
import json
from typing import Any
from unittest.mock import patch

import pytest

from app.modules.channel.domain.channel_event import ReplyRoute
from app.modules.channel.infrastructure.connector_registry import Connector
from app.modules.delivery.infrastructure.file_delivery_sender import (
    DeliveryFileContent,
    DingTalkFileDeliverySender,
    FileServiceDeliveryClient,
)
from app.shared.exceptions import RetryableExecutionError


class _FileService:
    def get(self, delivery_id: str) -> DeliveryFileContent:
        assert delivery_id == "delivery-a"
        return DeliveryFileContent(
            display_name="result.txt",
            content=b"result\n",
            size_bytes=7,
            sha256="2e1cfa82b035c26cbd3cd0309f709f41d03c9c89ad9b60f77bc7b11d82c0a3aa",
            format_code="TXT",
            media_type="text/plain",
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


class _TokenProvider:
    def access_token(self) -> str:
        return "bounded-test-token"


class _FileResponse:
    def __init__(self, *, name: str, content: bytes, format_code: str, media_type: str) -> None:
        self.content = content
        self.headers = {
            "X-File-Size": str(len(content)),
            "X-File-SHA256": hashlib.sha256(content).hexdigest(),
            "X-File-Name-B64": base64.urlsafe_b64encode(name.encode()).decode(),
            "X-File-Format": format_code,
            "Content-Type": media_type,
        }

    def __enter__(self) -> _FileResponse:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return self.content


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
        "app.modules.delivery.infrastructure.file_delivery_sender.DingTalkAccessTokenClient"
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


@pytest.mark.parametrize(
    ("name", "content", "format_code", "media_type"),
    [
        ("result.txt", b"text\n", "TXT", "text/plain"),
        ("service.log", b"log\n", "LOG", "text/plain"),
        ("report.md", b"# report\n", "MARKDOWN", "text/markdown"),
    ],
)
def test_file_service_delivery_client_preserves_exact_text_format_metadata(
    name: str,
    content: bytes,
    format_code: str,
    media_type: str,
) -> None:
    client = FileServiceDeliveryClient(
        base_url="http://file-service:8000",
        allowed_hosts=("file-service",),
        token_provider=_TokenProvider(),  # type: ignore[arg-type]
    )
    response = _FileResponse(
        name=name,
        content=content,
        format_code=format_code,
        media_type=media_type,
    )
    with patch(
        "app.modules.delivery.infrastructure.file_delivery_sender.urllib.request.urlopen",
        return_value=response,
    ):
        result = client.get("delivery-a")

    assert result.display_name == name
    assert result.content == content
    assert result.format_code == format_code
    assert result.media_type == media_type


def test_file_service_delivery_client_rejects_format_extension_mime_drift() -> None:
    client = FileServiceDeliveryClient(
        base_url="http://file-service:8000",
        allowed_hosts=("file-service",),
        token_provider=_TokenProvider(),  # type: ignore[arg-type]
    )
    response = _FileResponse(
        name="service.log",
        content=b"log\n",
        format_code="LOG",
        media_type="application/octet-stream",
    )
    with patch(
        "app.modules.delivery.infrastructure.file_delivery_sender.urllib.request.urlopen",
        return_value=response,
    ):
        with pytest.raises(RetryableExecutionError) as caught:
            client.get("delivery-a")
    assert caught.value.error_code == "file_delivery_integrity_mismatch"
