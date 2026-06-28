from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any

from app.modules.dingding.infrastructure.dingding_callback_client import DingTalkCallbackClient
from app.modules.job.application.create_agent_job_service import (
    CreateAgentJobCommand,
    CreateAgentJobService,
)
from app.shared.exceptions import PermissionDenied


@dataclass(frozen=True)
class DingTalkIncomingMessage:
    conversation_id: str
    user_id: str
    message_id: str
    content: str
    project_code: str = "default"
    source: str = "dingding"


class DingTalkMessageService:
    def __init__(
        self,
        *,
        secret: str,
        create_job_service: CreateAgentJobService,
        callback_client: DingTalkCallbackClient,
    ) -> None:
        self.secret = secret
        self.create_job_service = create_job_service
        self.callback_client = callback_client

    def verify_signature(self, *, timestamp: str, sign: str) -> bool:
        if not self.secret:
            return False
        string_to_sign = f"{timestamp}\n{self.secret}".encode("utf-8")
        digest = hmac.new(self.secret.encode("utf-8"), string_to_sign, hashlib.sha256).digest()
        expected = base64.b64encode(digest).decode("utf-8")
        return hmac.compare_digest(expected, sign)

    def parse_message(self, payload: dict[str, Any]) -> DingTalkIncomingMessage:
        text = payload.get("text", {})
        content = text.get("content") if isinstance(text, dict) else payload.get("content")
        if not content:
            content = payload.get("message", "")
        conversation_id = (
            payload.get("conversationId")
            or payload.get("conversation_id")
            or payload.get("conversationTitle")
            or "unknown-conversation"
        )
        user_id = payload.get("senderStaffId") or payload.get("senderId") or payload.get("user_id")
        message_id = payload.get("msgId") or payload.get("message_id")
        project_code = payload.get("project_code") or "default"
        if not user_id or not message_id:
            raise ValueError("DingTalk payload missing sender or message id")
        return DingTalkIncomingMessage(
            conversation_id=str(conversation_id),
            user_id=str(user_id),
            message_id=str(message_id),
            content=str(content).strip(),
            project_code=str(project_code),
        )

    def handle_webhook(
        self,
        *,
        payload: dict[str, Any],
        timestamp: str,
        sign: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        if not self.verify_signature(timestamp=timestamp, sign=sign):
            return {"accepted": False, "status": "invalid_signature"}
        message = self.parse_message(payload)
        try:
            job = self.create_job_service.execute(
                CreateAgentJobCommand(
                    idempotency_key=f"dingding:{message.message_id}",
                    dingding_conversation_id=message.conversation_id,
                    dingding_user_id=message.user_id,
                    user_message=message.content,
                    project_code=message.project_code,
                    source=message.source,
                    correlation_id=correlation_id,
                )
            )
        except PermissionDenied as exc:
            return {"accepted": False, "status": "permission_denied", "message": exc.safe_message}
        return {
            "accepted": True,
            "status": "received",
            "job_id": job.id,
            "message": "Task accepted, analysis is starting.",
        }

    def send_final_result(self, conversation_id: str, report: str) -> None:
        self.callback_client.send_markdown(
            conversation_id=conversation_id, title="Agent analysis", text=report
        )

    def safe_failure_notice(self, reason: str) -> str:
        return json.dumps({"status": "failed", "reason": reason}, ensure_ascii=False)
