from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

from app.shared.exceptions import NonRetryableExecutionError, RetryableExecutionError


class JsonPostTransport(Protocol):
    def post_json(
        self, url: str, payload: dict[str, Any], headers: dict[str, str], timeout_seconds: int
    ) -> dict[str, Any]:
        pass


class UrllibJsonPostTransport:
    def post_json(
        self, url: str, payload: dict[str, Any], headers: dict[str, str], timeout_seconds: int
    ) -> dict[str, Any]:
        request = Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"content-type": "application/json", **headers},
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            safe_status = getattr(exc, "code", "unknown")
            raise RetryableExecutionError(
                f"DingTalk HTTP request failed with status {safe_status}",
                safe_message=f"DingTalk HTTP request failed with status {safe_status}",
            ) from exc
        except URLError as exc:
            raise RetryableExecutionError(
                "DingTalk HTTP request failed",
                safe_message="DingTalk HTTP request failed",
            ) from exc
        if not body:
            return {}
        try:
            value = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RetryableExecutionError(
                "DingTalk response is not valid JSON",
                safe_message="DingTalk response is not valid JSON",
            ) from exc
        if not isinstance(value, dict):
            raise RetryableExecutionError(
                "DingTalk response JSON is not an object",
                safe_message="DingTalk response JSON is not an object",
            )
        return value


@dataclass(frozen=True)
class DingTalkAccessToken:
    value: str
    expires_at: float


class DingTalkAccessTokenClient:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        transport: JsonPostTransport | None = None,
        token_url: str = "https://api.dingtalk.com/v1.0/oauth2/accessToken",
        timeout_seconds: int = 5,
        refresh_margin_seconds: int = 60,
        clock: Any = time.time,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.transport = transport or UrllibJsonPostTransport()
        self.token_url = token_url
        self.timeout_seconds = timeout_seconds
        self.refresh_margin_seconds = refresh_margin_seconds
        self.clock = clock
        self._cached_token: DingTalkAccessToken | None = None

    def access_token(self) -> str:
        if not self.client_id or not self.client_secret:
            raise NonRetryableExecutionError(
                "DingTalk enterprise App credentials are not configured",
                safe_message="DingTalk enterprise App credentials are not configured",
            )
        now = float(self.clock())
        if self._cached_token and self._cached_token.expires_at - self.refresh_margin_seconds > now:
            return self._cached_token.value
        response = self.transport.post_json(
            self.token_url,
            {"appKey": self.client_id, "appSecret": self.client_secret},
            {},
            self.timeout_seconds,
        )
        token = str(response.get("accessToken") or response.get("access_token") or "")
        expires_in = int(response.get("expireIn") or response.get("expiresIn") or 7200)
        if not token:
            raise NonRetryableExecutionError(
                "DingTalk access token response did not include a token",
                safe_message="DingTalk access token response did not include a token",
            )
        self._cached_token = DingTalkAccessToken(value=token, expires_at=now + expires_in)
        return token


class DingTalkEnterpriseMessageClient:
    def __init__(
        self,
        *,
        token_client: DingTalkAccessTokenClient,
        transport: JsonPostTransport | None = None,
        send_url: str = "https://api.dingtalk.com/v1.0/robot/groupMessages/send",
        timeout_seconds: int = 5,
    ) -> None:
        self.token_client = token_client
        self.transport = transport or UrllibJsonPostTransport()
        self.send_url = send_url
        self.timeout_seconds = timeout_seconds
        self.sent_messages: list[dict[str, Any]] = []

    def send_markdown(
        self, *, open_conversation_id: str, robot_code: str, title: str, text: str
    ) -> None:
        if not open_conversation_id or not robot_code:
            raise NonRetryableExecutionError(
                "DingTalk enterprise delivery target is not configured",
                safe_message="DingTalk enterprise delivery target is not configured",
            )
        payload = {
            "robotCode": robot_code,
            "openConversationId": open_conversation_id,
            "msgKey": "sampleMarkdown",
            "msgParam": json.dumps({"title": title, "text": text}, ensure_ascii=False),
        }
        self.sent_messages.append(
            {"open_conversation_id": open_conversation_id, "robot_code": robot_code, "title": title}
        )
        response = self.transport.post_json(
            self.send_url,
            payload,
            {"x-acs-dingtalk-access-token": self.token_client.access_token()},
            self.timeout_seconds,
        )
        _raise_for_dingtalk_error(response, default_safe_message="DingTalk enterprise send failed")


class DingTalkWebhookRobotClient:
    def __init__(
        self,
        *,
        webhook_url: str,
        secret: str = "",
        transport: JsonPostTransport | None = None,
        timeout_seconds: int = 5,
        clock: Any = time.time,
    ) -> None:
        self.webhook_url = webhook_url
        self.secret = secret
        self.transport = transport or UrllibJsonPostTransport()
        self.timeout_seconds = timeout_seconds
        self.clock = clock
        self.sent_messages: list[dict[str, Any]] = []

    def send_markdown(
        self,
        *,
        title: str,
        text: str,
        at_mobiles: list[str] | None = None,
        at_user_ids: list[str] | None = None,
        is_at_all: bool = False,
    ) -> None:
        if not self.webhook_url:
            raise NonRetryableExecutionError(
                "DingTalk webhook robot URL is not configured",
                safe_message="DingTalk webhook robot URL is not configured",
            )
        payload = {
            "msgtype": "markdown",
            "markdown": {"title": title, "text": text},
            "at": {
                "atMobiles": at_mobiles or [],
                "atUserIds": at_user_ids or [],
                "isAtAll": is_at_all,
            },
        }
        self.sent_messages.append({"title": title, "chars": len(text), "is_at_all": is_at_all})
        response = self.transport.post_json(
            self.signed_webhook_url(),
            payload,
            {},
            self.timeout_seconds,
        )
        _raise_for_dingtalk_error(response, default_safe_message="DingTalk webhook send failed")

    def signed_webhook_url(self) -> str:
        if not self.secret:
            return self.webhook_url
        timestamp = str(int(float(self.clock()) * 1000))
        string_to_sign = f"{timestamp}\n{self.secret}".encode("utf-8")
        digest = hmac.new(self.secret.encode("utf-8"), string_to_sign, hashlib.sha256).digest()
        sign = base64.b64encode(digest).decode("utf-8")
        parsed = urlparse(self.webhook_url)
        query = parsed.query
        signed_query = urlencode({"timestamp": timestamp, "sign": sign})
        query = f"{query}&{signed_query}" if query else signed_query
        return urlunparse(parsed._replace(query=query))


def _raise_for_dingtalk_error(response: dict[str, Any], *, default_safe_message: str) -> None:
    code = response.get("errcode", response.get("code", 0))
    if str(code) in {"0", "", "None"}:
        return
    message = str(response.get("errmsg") or response.get("message") or default_safe_message)
    raise NonRetryableExecutionError(message, safe_message=default_safe_message)
