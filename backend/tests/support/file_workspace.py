from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

from app.bootstrap import build_test_container
from app.modules.attachments.domain import AttachmentImportReceipt
from app.modules.business_application.domain.policies import (
    required_file_mcp_tools,
    validate_task_file_features,
)
from app.shared.config import (
    AttachmentSettings,
    ConversationSettings,
    DingTalkSettings,
    Settings,
)
from backend.tests.support.applications import activate_dingtalk_test_application
from backend.tests.support.authorization import grant_test_application_access
from backend.tests.support.runtime import direct_job_permission_service_factory


FIXTURES = Path(__file__).parents[1] / "fixtures" / "dingtalk_stream"


class FakeDownloader:
    def __init__(self, values: dict[str, bytes]) -> None:
        self.values = values
        self.calls: list[tuple[str, str]] = []

    def download(
        self,
        *,
        download_code: str,
        max_bytes: int,
        connector_id: str = "",
        robot_code: str = "",
    ) -> bytes:
        self.calls.append((connector_id, robot_code))
        value = self.values[download_code]
        if len(value) > max_bytes:
            raise ValueError("file_size_exceeded")
        return value


class RecordingAttachmentImporter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bytes, str]] = []

    def import_content(
        self,
        *,
        attachment_id: str,
        data: bytes,
        content_type: str,
    ) -> AttachmentImportReceipt:
        self.calls.append((attachment_id, data, content_type))
        return AttachmentImportReceipt(
            attachment_id=attachment_id,
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
        )


def multimodal_container(
    *,
    task_file_features: dict[str, bool] | None = None,
    file_format_policy_version: str = "text-v1",
    document_processing_profile_code: str = "NONE",
) -> object:
    settings = Settings(
        database_dsn="sqlite:///:memory:",
        app_config_master_key="multimodal-test-master-key",
        dingtalk=DingTalkSettings(
            secret="test-secret",
            default_robot_code="robot-redacted",
        ),
        conversation=ConversationSettings(
            enabled=True,
            recent_message_limit=4,
            summary_trigger_messages=5,
            max_context_chars=2000,
            max_attachment_context_chars=1000,
        ),
        attachments=AttachmentSettings(enabled=True, max_file_bytes=1024 * 1024),
    )
    settings = replace(
        settings,
        environment="local",
        feature_business_application_control_plane=True,
        identity=replace(
            settings.identity,
            published_agent_runtime_enabled=True,
        ),
    )
    container = build_test_container(
        settings,
        migrate=True,
        seed=True,
        permission_service_factory=direct_job_permission_service_factory,
    )
    normalized_task_file_features = validate_task_file_features(task_file_features)
    tool_identifiers = tuple(
        sorted(
            {"get_er_context", "get_business_flow_context"}
            | set(required_file_mcp_tools(normalized_task_file_features))
        )
    )
    activate_dingtalk_test_application(
        container,
        code="multimodal-test-application",
        robot_code="robot-redacted",
        group_conversation_ids=("group-conversation-redacted",),
        attachments_enabled=True,
        capabilities=tool_identifiers,
        task_file_features=normalized_task_file_features,
        file_format_policy_version=file_format_policy_version,
        document_processing_profile_code=document_processing_profile_code,
    )
    application = container.business_application_repository.get_by_code(
        "multimodal-test-application"
    )
    grant_test_application_access(
        container,
        application_id=str(application["id"]),
        role_code="multimodal-runtime-reader",
        capabilities=tool_identifiers,
    )
    return container


def load_fixture(name: str) -> dict[str, object]:
    payload = json.loads((FIXTURES / name).read_text())
    payload["senderStaffId"] = "user_local_admin"
    payload["senderCorpId"] = "corp-test-enterprise"
    payload["chatbotCorpId"] = "corp-test-enterprise"
    payload["sessionWebhook"] = "https://oapi.dingtalk.com/robot/sendBySession"
    payload["sessionWebhookExpiredTime"] = "2099-01-01T00:00:00+00:00"
    return payload
