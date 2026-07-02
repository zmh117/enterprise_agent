from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from app.modules.dingding.application.dingtalk_stream_service import (
    DingTalkStreamHandleResult,
)
from app.shared.exceptions import NonRetryableExecutionError


class DingTalkStreamClient(Protocol):
    def start_forever(self) -> None:
        pass


StreamCallback = Callable[[dict[str, Any]], DingTalkStreamHandleResult]


class DingTalkStreamSdkClient:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        callback: StreamCallback,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.callback = callback

    def start_forever(self) -> None:
        try:
            import dingtalk_stream
        except ModuleNotFoundError as exc:
            raise NonRetryableExecutionError(
                "dingtalk-stream package is required for DingTalk Stream ingress",
                safe_message="DingTalk Stream SDK is not installed",
            ) from exc

        outer = self

        class EnterpriseAgentStreamHandler(dingtalk_stream.ChatbotHandler):  # type: ignore[name-defined]
            async def process(self, callback: Any) -> tuple[str, str]:
                payload = callback.data if isinstance(callback.data, dict) else {}
                result = outer.callback(payload)
                ack_message = getattr(dingtalk_stream, "AckMessage")
                if result.ack_status == "OK":
                    status = getattr(ack_message, "STATUS_OK", "OK")
                else:
                    status = getattr(ack_message, "STATUS_SYSTEM_EXCEPTION", "ERROR")
                return status, result.ack_message

        credential = dingtalk_stream.Credential(self.client_id, self.client_secret)
        client = dingtalk_stream.DingTalkStreamClient(credential)
        topic = dingtalk_stream.chatbot.ChatbotMessage.TOPIC
        client.register_callback_handler(topic, EnterpriseAgentStreamHandler())
        client.start_forever()
