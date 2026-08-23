from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
import uuid

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
from app.modules.file_workspace.domain import (
    FileOwner,
    FileSourceKind,
    FileVersionKind,
    FileVersionStatus,
    WorkspaceFileRole,
    WorkspaceOwnerType,
)
from app.modules.file_workspace.repository import FileWorkspaceRepository
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
    """In-memory File Service boundary fake that publishes canonical file identity."""

    def __init__(self, repository: FileWorkspaceRepository | None = None) -> None:
        self.repository = repository
        self.calls: list[tuple[str, bytes, str]] = []

    def import_content(
        self,
        *,
        attachment_id: str,
        data: bytes,
        content_type: str,
    ) -> AttachmentImportReceipt:
        self.calls.append((attachment_id, data, content_type))
        if self.repository is None:
            raise RuntimeError("canonical attachment importer is not bound")
        attachment = self.repository.database.execute_one(
            "select * from message_attachment where id = ?",
            (attachment_id,),
        )
        assert attachment is not None
        workspace = self.repository.get_workspace(str(attachment["task_workspace_id"]))
        owner = FileOwner(
            WorkspaceOwnerType(str(workspace["owner_type"])),
            user_id=str(workspace.get("owner_user_id") or ""),
            enterprise_id=str(workspace.get("owner_enterprise_id") or ""),
            connector_id=str(workspace.get("owner_connector_id") or ""),
            conversation_id=str(workspace.get("owner_conversation_id") or ""),
        )
        digest = hashlib.sha256(data).hexdigest()
        file_id = f"managed_file_{uuid.uuid4().hex}"
        version_id = f"file_version_{uuid.uuid4().hex}"
        display_name = str(attachment["file_name"])
        suffix = Path(display_name).suffix.lower()
        format_code = {".txt": "TXT", ".md": "MARKDOWN", ".log": "LOG"}[suffix]
        self.repository.create_file(
            file_id=file_id,
            tenant_id=str(workspace["tenant_id"]),
            owner=owner,
            display_name=display_name,
            actor_id="file-worker-test",
            format_code=format_code,
        )
        self.repository.create_version(
            version_id=version_id,
            file_id=file_id,
            version_number=1,
            version_kind=FileVersionKind.ATTACHMENT,
            status=FileVersionStatus.AVAILABLE,
            media_type=content_type,
            encoding="utf-8",
            size_bytes=len(data),
            content_sha256=digest,
            object_key=f"test/{version_id}",
            source_kind=FileSourceKind.MESSAGE_ATTACHMENT,
            actor_id="file-worker-test",
            format_code=format_code,
            advance_current_from="",
        )
        self.repository.link_workspace_file(
            workspace_id=str(workspace["id"]),
            file_id=file_id,
            version_id=version_id,
            logical_name=display_name,
            role=WorkspaceFileRole.INPUT,
        )
        self.repository.bind_attachment(
            attachment_id=attachment_id,
            file_id=file_id,
            version_id=version_id,
            retention_expires_at=str(workspace["expires_at"]),
        )
        return AttachmentImportReceipt(
            attachment_id=attachment_id,
            size_bytes=len(data),
            sha256=digest,
            file_id=file_id,
            version_id=version_id,
        )


def multimodal_container(
    *,
    task_file_features: dict[str, bool] | None = None,
    document_processing_profile_code: str = "NONE",
) -> object:
    if task_file_features is None:
        task_file_features = {"workspace_enabled": True}
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
    placeholder_importer = RecordingAttachmentImporter()
    container = build_test_container(
        settings,
        migrate=True,
        seed=True,
        service_name="file-worker",
        permission_service_factory=direct_job_permission_service_factory,
        attachment_importer_override=placeholder_importer,
    )
    assert container.attachment_service is not None
    container.attachment_service.importer = RecordingAttachmentImporter(
        FileWorkspaceRepository(container.database)
    )
    normalized_task_file_features = validate_task_file_features(task_file_features)
    tool_identifiers = tuple(sorted(required_file_mcp_tools(normalized_task_file_features)))
    activate_dingtalk_test_application(
        container,
        code="multimodal-test-application",
        robot_code="robot-redacted",
        group_conversation_ids=("group-conversation-redacted",),
        attachments_enabled=True,
        capabilities=tool_identifiers,
        task_file_features=normalized_task_file_features,
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


def file_workspace_command_kwargs(container: object) -> dict[str, object]:
    publication = container.database.execute_one(
        """
        select publication.id
          from business_application_publication publication
          join business_application_revision revision on revision.id = publication.revision_id
          join business_application application on application.id = revision.application_id
         where application.code = 'multimodal-test-application'
        """
    )
    assert publication is not None
    return {
        "tenant_id": "default",
        "business_application_publication_id": str(publication["id"]),
        "task_file_features": {"workspace_enabled": True},
    }


def load_fixture(name: str) -> dict[str, object]:
    payload = json.loads((FIXTURES / name).read_text())
    payload["senderStaffId"] = "user_local_admin"
    payload["senderCorpId"] = "corp-test-enterprise"
    payload["chatbotCorpId"] = "corp-test-enterprise"
    payload["sessionWebhook"] = "https://oapi.dingtalk.com/robot/sendBySession"
    payload["sessionWebhookExpiredTime"] = "2099-01-01T00:00:00+00:00"
    return payload
