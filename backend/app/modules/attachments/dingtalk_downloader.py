from __future__ import annotations

from urllib.request import Request, urlopen

from app.modules.dingding.infrastructure.dingtalk_delivery_clients import (
    DingTalkAccessTokenClient,
    JsonPostTransport,
    UrllibJsonPostTransport,
)
from app.shared.exceptions import RetryableExecutionError


class DingTalkMediaDownloader:
    def __init__(
        self,
        *,
        token_client: DingTalkAccessTokenClient,
        robot_code: str,
        transport: JsonPostTransport | None = None,
        download_api_url: str = "https://api.dingtalk.com/v1.0/robot/messageFiles/download",
        timeout_seconds: int = 30,
    ) -> None:
        self.token_client = token_client
        self.robot_code = robot_code
        self.transport = transport or UrllibJsonPostTransport()
        self.download_api_url = download_api_url
        self.timeout_seconds = timeout_seconds

    def download(self, *, download_code: str, max_bytes: int) -> bytes:
        response = self.transport.post_json(
            self.download_api_url,
            {"robotCode": self.robot_code, "downloadCode": download_code},
            {"x-acs-dingtalk-access-token": self.token_client.access_token()},
            self.timeout_seconds,
        )
        download_url = str(response.get("downloadUrl") or "")
        if not download_url:
            raise RetryableExecutionError(
                "DingTalk media response did not include download URL",
                safe_message="DingTalk media download is temporarily unavailable",
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
                safe_message="DingTalk media download failed",
            ) from exc
        return b"".join(chunks)
