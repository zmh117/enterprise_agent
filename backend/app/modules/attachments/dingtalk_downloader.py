from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable
from urllib.request import Request, urlopen

from app.modules.dingding.infrastructure.dingtalk_delivery_clients import (
    DingTalkAccessTokenClient,
    JsonPostTransport,
    UrllibJsonPostTransport,
)
from app.shared.database import assert_external_io_allowed
from app.shared.exceptions import NonRetryableExecutionError, RetryableExecutionError


DingTalkMediaCredentialResolver = Callable[[str], tuple[str, str, str]]
DingTalkTokenClientFactory = Callable[[str, str], DingTalkAccessTokenClient]


class DingTalkMediaDownloader:
    def __init__(
        self,
        *,
        token_client: DingTalkAccessTokenClient | None = None,
        robot_code: str = "",
        credential_resolver: DingTalkMediaCredentialResolver | None = None,
        token_client_factory: DingTalkTokenClientFactory | None = None,
        transport: JsonPostTransport | None = None,
        download_api_url: str = "https://api.dingtalk.com/v1.0/robot/messageFiles/download",
        timeout_seconds: int = 30,
    ) -> None:
        self.token_client = token_client
        self.robot_code = robot_code
        self.credential_resolver = credential_resolver
        self.token_client_factory = token_client_factory or (
            lambda client_id, client_secret: DingTalkAccessTokenClient(
                client_id=client_id,
                client_secret=client_secret,
                timeout_seconds=timeout_seconds,
            )
        )
        self.transport = transport or UrllibJsonPostTransport()
        self.download_api_url = download_api_url
        self.timeout_seconds = timeout_seconds
        self._client_cache: dict[str, tuple[str, DingTalkAccessTokenClient]] = {}
        self._client_lock = threading.Lock()

    def download(
        self,
        *,
        download_code: str,
        max_bytes: int,
        connector_id: str = "",
        robot_code: str = "",
    ) -> bytes:
        assert_external_io_allowed("dingtalk.media_download")
        token_client, connector_robot_code = self._connector_client(connector_id)
        effective_robot_code = robot_code or connector_robot_code or self.robot_code
        if not effective_robot_code:
            raise NonRetryableExecutionError(
                "DingTalk media download robot identity is unavailable",
                safe_message="钉钉附件缺少机器人身份",
                error_code="dingtalk_media_robot_identity_missing",
            )
        response = self.transport.post_json(
            self.download_api_url,
            {"robotCode": effective_robot_code, "downloadCode": download_code},
            {"x-acs-dingtalk-access-token": token_client.access_token()},
            self.timeout_seconds,
        )
        download_url = str(response.get("downloadUrl") or "")
        if not download_url:
            raise RetryableExecutionError(
                "DingTalk media response did not include download URL",
                safe_message="钉钉媒体文件下载暂时不可用",
            )
        request = Request(download_url, headers={"user-agent": "enterprise-agent/1.0"})
        try:
            with urlopen(request, timeout=self.timeout_seconds) as stream:
                chunks: list[bytes] = []
                total = 0
                while True:
                    chunk = stream.read(min(64 * 1024, max_bytes + 1 - total))
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError("file_size_exceeded")
                    chunks.append(chunk)
        except ValueError:
            raise
        except Exception as exc:
            raise RetryableExecutionError(
                "DingTalk media download failed",
                safe_message="钉钉媒体文件下载失败",
            ) from exc
        return b"".join(chunks)

    def _connector_client(
        self,
        connector_id: str,
    ) -> tuple[DingTalkAccessTokenClient, str]:
        if self.credential_resolver is None:
            if self.token_client is None:
                raise NonRetryableExecutionError(
                    "DingTalk media credentials are unavailable",
                    safe_message="钉钉附件下载凭据不可用",
                    error_code="dingtalk_media_credentials_unavailable",
                )
            return self.token_client, ""
        if not connector_id:
            raise NonRetryableExecutionError(
                "DingTalk media source connector is unavailable",
                safe_message="钉钉附件缺少来源连接器",
                error_code="dingtalk_media_connector_missing",
            )
        client_id, client_secret, connector_robot_code = self.credential_resolver(connector_id)
        if not client_id or not client_secret:
            raise NonRetryableExecutionError(
                "DingTalk media connector credentials are unavailable",
                safe_message="钉钉附件来源连接器凭据不可用",
                error_code="dingtalk_media_credentials_unavailable",
            )
        fingerprint = hashlib.sha256(
            client_id.encode("utf-8") + b"\0" + client_secret.encode("utf-8")
        ).hexdigest()
        with self._client_lock:
            cached = self._client_cache.get(connector_id)
            if cached is None or cached[0] != fingerprint:
                cached = (
                    fingerprint,
                    self.token_client_factory(client_id, client_secret),
                )
                self._client_cache[connector_id] = cached
        return cached[1], connector_robot_code
