from __future__ import annotations

import base64
import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from app.modules.channel.domain.channel_event import ReplyRoute
from app.modules.channel.infrastructure.connector_registry import Connector, ConnectorRegistry
from app.modules.dingding.infrastructure.dingtalk_delivery_clients import (
    DingTalkAccessTokenClient,
    JsonPostTransport,
    UrllibJsonPostTransport,
)
from app.modules.identity.application.service_principal import AccessTokenProvider
from app.shared.exceptions import NonRetryableExecutionError, RetryableExecutionError


@dataclass(frozen=True)
class DeliveryFileContent:
    display_name: str
    content: bytes
    size_bytes: int
    sha256: str
    format_code: str
    media_type: str


class FileDeliverySender(Protocol):
    def send(
        self,
        *,
        delivery_id: str,
        connector: Connector | None,
        route: ReplyRoute,
        idempotency_key: str,
    ) -> None: ...


class FileServiceDeliveryClient:
    def __init__(
        self,
        *,
        base_url: str,
        allowed_hosts: tuple[str, ...],
        token_provider: AccessTokenProvider,
        timeout_seconds: int = 30,
    ) -> None:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.hostname not in allowed_hosts
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("File Service Delivery endpoint is invalid")
        self.base_url = base_url.rstrip("/")
        self.token_provider = token_provider
        self.timeout_seconds = timeout_seconds

    def get(self, delivery_id: str) -> DeliveryFileContent:
        token = self.token_provider.access_token()
        if not token or len(token.encode()) > 8192:
            raise NonRetryableExecutionError(
                "Delivery Worker Principal token is unavailable",
                safe_message="文件交付身份凭证不可用",
                error_code="file_delivery_principal_unavailable",
            )
        request = urllib.request.Request(
            f"{self.base_url}/internal/v1/file-deliveries/{urllib.parse.quote(delivery_id, safe='')}/content",
            headers={"Authorization": f"Bearer {token}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                size_bytes = int(response.headers["X-File-Size"])
                sha256 = str(response.headers["X-File-SHA256"])
                encoded_name = str(response.headers["X-File-Name-B64"])
                format_code = str(response.headers["X-File-Format"])
                media_type = str(response.headers["Content-Type"]).split(";", 1)[0].lower()
                display_name = base64.b64decode(
                    encoded_name.encode("ascii"), altchars=b"-_", validate=True
                ).decode("utf-8")
                if not 0 <= size_bytes <= 15 * 1024 * 1024:
                    raise ValueError("File delivery size is invalid")
                content = response.read(size_bytes + 1)
        except urllib.error.HTTPError as exc:
            if 400 <= exc.code < 500:
                raise NonRetryableExecutionError(
                    "File Service rejected Delivery read",
                    safe_message="文件交付版本不可用",
                    error_code="file_delivery_read_denied",
                ) from exc
            raise RetryableExecutionError(
                "File Service Delivery read failed",
                safe_message="文件交付服务暂时不可用",
                error_code="file_service_unavailable",
            ) from exc
        except (OSError, TimeoutError, KeyError, ValueError, UnicodeError) as exc:
            raise RetryableExecutionError(
                "File Service Delivery read failed",
                safe_message="文件交付服务暂时不可用",
                error_code="file_service_unavailable",
            ) from exc
        expected = {
            "TXT": (".txt", "text/plain"),
            "LOG": (".log", "text/plain"),
            "MARKDOWN": (".md", "text/markdown"),
        }.get(format_code)
        if (
            len(content) != size_bytes
            or hashlib.sha256(content).hexdigest() != sha256
            or expected is None
            or not display_name.lower().endswith(expected[0])
            or media_type != expected[1]
        ):
            raise RetryableExecutionError(
                "File Delivery content receipt mismatch",
                safe_message="文件交付内容校验失败",
                error_code="file_delivery_integrity_mismatch",
            )
        return DeliveryFileContent(
            display_name,
            content,
            size_bytes,
            sha256,
            format_code,
            media_type,
        )


class DingTalkFileDeliverySender:
    """Upload one immutable version as a new DingTalk media/file message."""

    def __init__(
        self,
        *,
        file_service: FileServiceDeliveryClient,
        connector_registry: ConnectorRegistry,
        transport: JsonPostTransport | None = None,
        timeout_seconds: int = 30,
    ) -> None:
        self.file_service = file_service
        self.connector_registry = connector_registry
        self.transport = transport or UrllibJsonPostTransport()
        self.timeout_seconds = timeout_seconds

    def send(
        self,
        *,
        delivery_id: str,
        connector: Connector | None,
        route: ReplyRoute,
        idempotency_key: str,
    ) -> None:
        if connector is None or not route.type.startswith("dingtalk"):
            raise NonRetryableExecutionError(
                "DingTalk File Delivery requires a governed connector",
                safe_message="当前回复路由不支持文件交付",
                error_code="file_delivery_route_unsupported",
            )
        content = self.file_service.get(delivery_id)
        if any(character in content.display_name for character in ("\r", "\n", '"')):
            raise NonRetryableExecutionError(
                "DingTalk File Delivery name is unsafe",
                safe_message="文件交付名称无效",
                error_code="file_delivery_name_invalid",
            )
        client_id = self.connector_registry.resolve_metadata_reference(
            connector, "client_id_ref"
        ) or self.connector_registry.metadata_value(connector, "client_id")
        client_secret = self.connector_registry.resolve_secret(connector)
        token_url = (
            self.connector_registry.resolve_metadata_reference(connector, "token_url_ref")
            or self.connector_registry.metadata_value(connector, "token_url")
            or "https://api.dingtalk.com/v1.0/oauth2/accessToken"
        )
        upload_url = (
            self.connector_registry.resolve_metadata_reference(connector, "file_upload_url_ref")
            or self.connector_registry.metadata_value(connector, "file_upload_url")
            or "https://oapi.dingtalk.com/media/upload"
        )
        conversation_type = str(route.target.get("conversation_type") or "")
        if conversation_type not in {"direct", "group"}:
            raise NonRetryableExecutionError(
                "DingTalk File Delivery conversation type is missing",
                safe_message="钉钉文件交付会话类型无效",
                error_code="file_delivery_target_invalid",
            )
        if conversation_type == "direct":
            send_url = (
                self.connector_registry.resolve_metadata_reference(connector, "direct_send_url_ref")
                or self.connector_registry.metadata_value(connector, "direct_send_url")
                or "https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend"
            )
        else:
            send_url = (
                self.connector_registry.resolve_metadata_reference(connector, "send_url_ref")
                or self.connector_registry.metadata_value(connector, "send_url")
                or "https://api.dingtalk.com/v1.0/robot/groupMessages/send"
            )
        self.connector_registry.assert_host_allowed(connector, upload_url)
        self.connector_registry.assert_host_allowed(connector, send_url)
        token_client = DingTalkAccessTokenClient(
            client_id=client_id,
            client_secret=client_secret,
            token_url=token_url,
            timeout_seconds=self.timeout_seconds,
        )
        token = token_client.access_token()
        media_id = self._upload(
            upload_url=upload_url,
            access_token=token,
            content=content,
            idempotency_key=idempotency_key,
        )
        open_conversation_id = str(
            route.target.get("open_conversation_id")
            or route.target.get("conversation_id")
            or self.connector_registry.metadata_value(connector, "default_open_conversation_id")
        )
        robot_code = str(
            route.target.get("robot_code")
            or self.connector_registry.metadata_value(connector, "default_robot_code")
            or client_id
        )
        recipient_user_id = str(route.target.get("recipient_user_id") or "")
        if (
            not robot_code
            or (conversation_type == "group" and not open_conversation_id)
            or (conversation_type == "direct" and not recipient_user_id)
        ):
            raise NonRetryableExecutionError(
                "DingTalk File Delivery target is incomplete",
                safe_message="钉钉文件交付目标未配置",
                error_code="file_delivery_target_invalid",
            )
        payload: dict[str, object] = {
            "robotCode": robot_code,
            "msgKey": "sampleFile",
            "msgParam": json.dumps(
                {"mediaId": media_id, "fileName": content.display_name},
                ensure_ascii=False,
            ),
        }
        if conversation_type == "group":
            payload["openConversationId"] = open_conversation_id
        else:
            payload["userIds"] = [recipient_user_id]
        response = self.transport.post_json(
            send_url,
            payload,
            {
                "x-acs-dingtalk-access-token": token,
                "x-acs-dingtalk-request-id": idempotency_key,
            },
            self.timeout_seconds,
        )
        if str(response.get("code") or "") not in {"", "0"}:
            raise RetryableExecutionError(
                "DingTalk File Delivery failed",
                safe_message="钉钉文件交付失败",
                error_code="dingtalk_file_delivery_failed",
            )

    def _upload(
        self,
        *,
        upload_url: str,
        access_token: str,
        content: DeliveryFileContent,
        idempotency_key: str,
    ) -> str:
        boundary = f"enterprise-agent-{uuid.uuid4().hex}"
        disposition = (
            f'Content-Disposition: form-data; name="media"; filename="{content.display_name}"'
        )
        body = (
            (
                f"--{boundary}\r\n{disposition}\r\nContent-Type: {content.media_type}\r\n\r\n"
            ).encode()
            + content.content
            + f"\r\n--{boundary}--\r\n".encode()
        )
        separator = "&" if "?" in upload_url else "?"
        endpoint = f"{upload_url}{separator}" + urllib.parse.urlencode(
            {"access_token": access_token, "type": "file"}
        )
        request = urllib.request.Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "X-Idempotency-Key": idempotency_key,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read(64 * 1024 + 1))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RetryableExecutionError(
                "DingTalk File upload failed",
                safe_message="钉钉文件上传失败",
                error_code="dingtalk_file_upload_failed",
            ) from exc
        media_id = str(payload.get("media_id") or payload.get("mediaId") or "")
        if not media_id:
            raise RetryableExecutionError(
                "DingTalk File upload response is invalid",
                safe_message="钉钉文件上传响应无效",
                error_code="dingtalk_file_upload_invalid",
            )
        return media_id
