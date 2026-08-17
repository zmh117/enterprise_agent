from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pytest

from app.modules.channel.domain.channel_event import ChannelFileReference
from app.modules.file_workspace.domain import (
    FileOwner,
    FileSourceKind,
    FileVersionKind,
    FileVersionStatus,
    WorkspaceFileRole,
    WorkspaceOwnerType,
)
from app.modules.file_workspace.manifest_service import (
    JobFileManifestService,
    is_explicit_text_output_request,
    is_explicit_txt_output_request,
)
from app.modules.file_workspace.repository import FileWorkspaceRepository
from app.modules.file_workspace.workspace_service import TaskWorkspaceService
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.test_file_workspace_repository import TIMESTAMP, _database


@pytest.mark.parametrize(
    "message",
    [
        "请创建一份 Markdown 文件并保存为 report.md",
        "edit the .md document and export it",
    ],
)
def test_text_v2_requires_explicit_markdown_file_output_intent(message: str) -> None:
    assert is_explicit_text_output_request(message, policy_version="text-v2") is True


@pytest.mark.parametrize(
    "message",
    [
        "解释一下 Markdown 的语法",
        "请用 Markdown 排版回复，不要创建文件",
        "分析 service.log 里可能的问题",
        "讨论是否应该生成 Markdown 页面",
    ],
)
def test_text_v2_does_not_create_workspace_for_discussion_or_log_analysis(
    message: str,
) -> None:
    assert is_explicit_text_output_request(message, policy_version="text-v2") is False


def _service() -> tuple[FileWorkspaceRepository, JobFileManifestService]:
    repository = FileWorkspaceRepository(_database())
    return repository, JobFileManifestService(repository, TaskWorkspaceService(repository))


@pytest.mark.parametrize(
    "message",
    (
        "画一个天安门的txt文件",
        "请绘制字符画并保存为 天安门.txt",
        "制作一个 TXT 文档给我",
        "export the result as a txt file",
    ),
)
def test_explicit_txt_output_request_recognizes_generation_phrases(message: str) -> None:
    assert is_explicit_txt_output_request(message) is True


@pytest.mark.parametrize(
    "message",
    (
        "解释一下 TXT 文件格式",
        "分析这个文本文件",
        "普通文字问题",
    ),
)
def test_explicit_txt_output_request_rejects_non_output_questions(message: str) -> None:
    assert is_explicit_txt_output_request(message) is False


def _insert_job(
    repository: FileWorkspaceRepository,
    *,
    job_id: str,
    workspace_id: str,
    session_id: str = "session-file",
) -> None:
    repository.database.execute(
        """
        insert into agent_job
          (id, session_id, idempotency_key, status, created_at,
           source_channel, source_connector_id, requester_id, internal_user_id,
           business_application_id, business_application_publication_id,
           task_workspace_id)
        values (?, ?, ?, 'PENDING', ?, 'dingding_stream', 'connector-a',
                'user-a', 'user-a', 'app-file', 'app-file-p1', ?)
        """,
        (job_id, session_id, f"{job_id}-key", TIMESTAMP, workspace_id),
    )


def _create_txt(
    repository: FileWorkspaceRepository,
    *,
    workspace_id: str,
    file_id: str,
    version_id: str,
    version_number: int = 1,
    advance_from: str = "",
    link: bool = True,
    source_received_at: str | None = None,
) -> None:
    owner = FileOwner(WorkspaceOwnerType.PRIVATE_USER, user_id="user-a")
    if version_number == 1:
        repository.create_file(
            file_id=file_id,
            tenant_id="tenant-a",
            owner=owner,
            display_name="notes.txt",
            actor_id="user-a",
            source_received_at=source_received_at,
        )
    repository.create_version(
        version_id=version_id,
        file_id=file_id,
        version_number=version_number,
        version_kind=FileVersionKind.WORKING,
        status=FileVersionStatus.AVAILABLE,
        media_type="text/plain",
        encoding="utf-8",
        size_bytes=5,
        content_sha256=f"{version_number:064x}",
        object_key=f"opaque/{version_id}",
        source_kind=FileSourceKind.AGENT_EDITED,
        actor_id="user-a",
        advance_current_from=advance_from,
    )
    if link:
        repository.link_workspace_file(
            workspace_id=workspace_id,
            file_id=file_id,
            version_id=version_id,
            logical_name="notes.txt",
            role=WorkspaceFileRole.WORKING,
        )


def test_job_manifest_freezes_exact_version_and_later_job_sees_new_current() -> None:
    repository, service = _service()
    workspace = service.resolve_workspace(
        tenant_id="tenant-a",
        session_id="session-file",
        requester_id="user-a",
        conversation_type="direct",
        enterprise_id="tenant-a",
        connector_id="connector-a",
        conversation_id="conversation-a",
        sender_staff_id="staff-a",
        publication_id="app-file-p1",
        retention_period="WEEK",
        attachments=(),
        file_references=(),
        requests_file_output=True,
    )
    assert workspace is not None
    workspace_id = str(workspace["id"])
    _create_txt(
        repository,
        workspace_id=workspace_id,
        file_id="file-notes",
        version_id="version-1",
    )
    _insert_job(repository, job_id="job-1", workspace_id=workspace_id)
    service.register_request(
        job_id="job-1",
        workspace=workspace,
        requester_id="user-a",
        publication_id="app-file-p1",
        file_references=(ChannelFileReference(file_id="file-notes", version_id="version-1"),),
    )
    first = service.finalize("job-1")
    assert first is not None
    assert first["items"][0]["version_id"] == "version-1"
    assert first["items"][0]["auto_materialize"] == 1
    assert first["items"][0]["source_kind"] == "EXPLICIT_REFERENCE"
    assert first["schema_version"] == 3
    assert first["items"][0]["source_received_at"] is None
    assert first["items"][0]["version_created_at"]
    runtime_manifest = service.runtime_manifest("job-1")
    assert runtime_manifest == {
        "schema_version": 3,
        "file_format_policy_version": "text-v1",
        "manifest_hash": first["manifest_hash"],
        "observed_at": first["created_at"],
        "items": [
            {
                "file_id": "file-notes",
                "version_id": "version-1",
                "display_name": "notes.txt",
                "format_code": "TXT",
                "source_kind": "EXPLICIT_REFERENCE",
                "allowed_actions": [
                    "READ_METADATA",
                    "MATERIALIZE",
                    "RETAIN",
                    "DELIVER",
                ],
                "auto_materialize": True,
                "conflict_candidate": False,
                "source_received_at": None,
                "version_created_at": first["items"][0]["version_created_at"],
            }
        ],
    }

    _create_txt(
        repository,
        workspace_id=workspace_id,
        file_id="file-notes",
        version_id="version-2",
        version_number=2,
        advance_from="version-1",
        link=False,
    )
    repository.database.execute(
        """
        update task_workspace_file set selected_version_id = 'version-2'
         where workspace_id = ? and file_id = 'file-notes'
        """,
        (workspace_id,),
    )
    frozen_again = service.finalize("job-1")
    assert frozen_again is not None
    assert frozen_again["items"][0]["version_id"] == "version-1"

    _insert_job(repository, job_id="job-2", workspace_id=workspace_id)
    service.register_request(
        job_id="job-2",
        workspace=workspace,
        requester_id="user-a",
        publication_id="app-file-p1",
        file_references=(),
    )
    second = service.finalize("job-2")
    assert second is not None
    assert second["items"][0]["version_id"] == "version-2"
    assert second["items"][0]["auto_materialize"] == 0
    assert second["items"][0]["source_kind"] == "WORKSPACE"


def test_job_manifest_freezes_attachment_receipt_time_separately_from_version_time() -> None:
    repository, service = _service()
    workspace = service.resolve_workspace(
        tenant_id="tenant-a",
        session_id="session-file",
        requester_id="user-a",
        conversation_type="direct",
        enterprise_id="tenant-a",
        connector_id="connector-a",
        conversation_id="conversation-a",
        sender_staff_id="staff-a",
        publication_id="app-file-p1",
        retention_period="WEEK",
        attachments=(),
        file_references=(),
        requests_file_output=True,
    )
    assert workspace is not None
    _create_txt(
        repository,
        workspace_id=str(workspace["id"]),
        file_id="file-uploaded",
        version_id="version-uploaded",
        source_received_at=TIMESTAMP,
    )
    _insert_job(repository, job_id="job-uploaded", workspace_id=str(workspace["id"]))
    service.register_request(
        job_id="job-uploaded",
        workspace=workspace,
        requester_id="user-a",
        publication_id="app-file-p1",
        file_references=(),
    )

    snapshot = service.finalize("job-uploaded")
    assert snapshot is not None
    item = snapshot["items"][0]
    assert item["source_received_at"] == TIMESTAMP
    assert item["version_created_at"] != item["source_received_at"]
    runtime = service.runtime_manifest("job-uploaded")
    assert runtime["items"][0]["source_received_at"] == TIMESTAMP
    assert runtime["items"][0]["version_created_at"] == item["version_created_at"]


def test_manifest_rejects_cross_workspace_reference_without_snapshot_side_effect() -> None:
    repository, service = _service()
    workspace = service.resolve_workspace(
        tenant_id="tenant-a",
        session_id="session-file",
        requester_id="user-a",
        conversation_type="direct",
        enterprise_id="tenant-a",
        connector_id="connector-a",
        conversation_id="conversation-a",
        sender_staff_id="staff-a",
        publication_id="app-file-p1",
        retention_period="WEEK",
        attachments=(),
        file_references=(),
        requests_file_output=True,
    )
    assert workspace is not None
    _create_txt(
        repository,
        workspace_id=str(workspace["id"]),
        file_id="file-local",
        version_id="version-local",
    )
    repository.create_file(
        file_id="file-foreign",
        tenant_id="tenant-a",
        owner=FileOwner(WorkspaceOwnerType.PRIVATE_USER, user_id="user-a"),
        display_name="foreign.txt",
        actor_id="user-a",
    )
    repository.create_version(
        version_id="version-foreign",
        file_id="file-foreign",
        version_number=1,
        version_kind=FileVersionKind.WORKING,
        status=FileVersionStatus.AVAILABLE,
        media_type="text/plain",
        encoding="utf-8",
        size_bytes=5,
        content_sha256="f" * 64,
        object_key="opaque/version-foreign",
        source_kind=FileSourceKind.AGENT_GENERATED,
        actor_id="user-a",
        advance_current_from="",
    )
    _insert_job(repository, job_id="job-cross", workspace_id=str(workspace["id"]))
    service.register_request(
        job_id="job-cross",
        workspace=workspace,
        requester_id="user-a",
        publication_id="app-file-p1",
        file_references=(
            ChannelFileReference(file_id="file-foreign", version_id="version-foreign"),
        ),
    )
    with pytest.raises(NonRetryableExecutionError) as error:
        service.finalize("job-cross")
    assert error.value.error_code == "file_reference_denied"
    assert (
        repository.database.execute_one(
            "select id from agent_job_file_snapshot where job_id = 'job-cross'"
        )
        is None
    )


def test_group_file_workspace_requires_actual_sender_staff_id() -> None:
    repository, service = _service()
    with pytest.raises(NonRetryableExecutionError) as error:
        service.resolve_workspace(
            tenant_id="tenant-a",
            session_id="session-file",
            requester_id="user-a",
            conversation_type="group",
            enterprise_id="tenant-a",
            connector_id="connector-a",
            conversation_id="group-a",
            sender_staff_id="",
            publication_id="app-file-p1",
            retention_period="WEEK",
            attachments=(),
            file_references=(),
            requests_file_output=True,
        )
    assert error.value.error_code == "file_group_sender_missing"


def test_attachment_queries_do_not_embed_or_bind_txt_only_suffix_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, service = _service()
    database = repository.database
    original_execute = database.execute
    calls: list[tuple[str, tuple[Any, ...]]] = []

    def recording_execute(
        sql: str,
        params: Iterable[Any] = (),
    ) -> list[dict[str, Any]]:
        values = tuple(params)
        calls.append((sql, values))
        return original_execute(sql, values)

    monkeypatch.setattr(database, "execute", recording_execute)
    assert service.has_pending_txt_attachments("job-bind-txt") is False

    workspace = service.resolve_workspace(
        tenant_id="tenant-a",
        session_id="session-file",
        requester_id="user-a",
        conversation_type="direct",
        enterprise_id="tenant-a",
        connector_id="connector-a",
        conversation_id="conversation-a",
        sender_staff_id="staff-a",
        publication_id="app-file-p1",
        retention_period="WEEK",
        attachments=(),
        file_references=(),
        requests_file_output=True,
    )
    assert workspace is not None
    _insert_job(
        repository,
        job_id="job-bind-txt",
        workspace_id=str(workspace["id"]),
        session_id="session-file",
    )
    service.register_request(
        job_id="job-bind-txt",
        workspace=workspace,
        requester_id="user-a",
        publication_id="app-file-p1",
        file_references=(),
    )
    assert service.finalize("job-bind-txt") is not None

    attachment_queries = [
        (" ".join(sql.split()), params) for sql, params in calls if "message_attachment" in sql
    ]
    assert len(attachment_queries) == 2
    for sql, params in attachment_queries:
        assert "lower(file_name)" not in sql
        assert "lower(a.file_name)" not in sql
        assert "%.txt" not in sql
        assert "%.txt" not in params
