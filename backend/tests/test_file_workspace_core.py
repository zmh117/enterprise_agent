from __future__ import annotations

import io
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.modules.file_workspace.domain import (
    FileOwner,
    FileSourceKind,
    FileVersionKind,
    FileVersionStatus,
    RetentionPeriod,
    RetentionReason,
    WorkspaceFileRole,
    WorkspaceOwnerType,
)
from app.modules.file_workspace.quota import (
    MAX_TEMPORARY_BYTES,
    WorkspaceQuotaService,
)
from app.modules.file_workspace.repository import FileWorkspaceRepository
from app.modules.file_workspace.txt_validation import TxtStreamValidator
from app.modules.file_workspace.workspace_service import TaskWorkspaceService
from app.modules.platform_config.infrastructure import PlatformConfigRepository
from app.modules.platform_config.application.runtime_config import RuntimeConfigRegistry
from app.shared.exceptions import NonRetryableExecutionError
from backend.tests.test_file_workspace_repository import TIMESTAMP, _database


SHANGHAI = ZoneInfo("Asia/Shanghai")


def _owner() -> FileOwner:
    return FileOwner(WorkspaceOwnerType.PRIVATE_USER, user_id="user-a")


def test_workspace_is_created_only_for_file_work_reused_and_explicitly_switched() -> None:
    database = _database()
    repository = FileWorkspaceRepository(database)
    service = TaskWorkspaceService(repository)
    now = datetime(2026, 8, 12, 9, 0, tzinfo=SHANGHAI)
    arguments = {
        "tenant_id": "tenant-a",
        "session_id": "session-file",
        "owner": _owner(),
        "publication_id": "app-file-p1",
        "retention_period": RetentionPeriod.WEEK,
        "actor_id": "user-a",
        "now": now,
    }
    assert service.resolve_for_request(
        **arguments, has_file_input=False, requests_file_output=False
    ) is None
    assert database.execute_one("select count(*) as value from task_workspace")[
        "value"
    ] == 0

    first = service.resolve_for_request(
        **arguments, has_file_input=True, requests_file_output=False
    )
    assert first is not None
    assert first["expires_at"] == "2026-08-17T00:00:00+08:00"
    assert service.resolve_for_request(
        **arguments, has_file_input=False, requests_file_output=False
    )["id"] == first["id"]
    assert service.resolve_for_request(
        **arguments, has_file_input=True, requests_file_output=False
    )["id"] == first["id"]

    second = service.resolve_for_request(
        **arguments,
        has_file_input=True,
        requests_file_output=False,
        start_new_task=True,
    )
    assert second is not None and second["id"] != first["id"]
    assert repository.get_workspace(str(first["id"]))["status"] == "CLOSED"
    assert database.execute_one(
        "select count(*) as value from task_workspace where status = 'ACTIVE'"
    )["value"] == 1
    assert service.resolve_for_request(
        **arguments,
        has_file_input=False,
        requests_file_output=False,
        end_current_task=True,
    ) is None


def test_txt_stream_validation_accepts_input_bom_and_rejects_output_bom_encoding_type_and_limit() -> None:
    validator = TxtStreamValidator(max_bytes=16)
    destination = io.BytesIO()
    result = validator.validate_and_copy(
        [b"\xef", b"\xbb\xbfhello", "世界".encode()],
        destination,
        display_name="input.txt",
        media_type="text/plain; charset=utf-8",
        agent_output=False,
    )
    assert result.had_utf8_bom is True
    assert destination.getvalue().startswith(b"\xef\xbb\xbf")

    invalid_cases = [
        ([b"\xef\xbb\xbfhello"], "output.txt", "text/plain", True, "file_output_bom_forbidden"),
        (["中文".encode("utf-16")], "input.txt", "text/plain", False, "file_encoding_invalid"),
        ([b"hello"], "input.md", "text/markdown", False, "file_type_unsupported"),
        ([b"x" * 17], "input.txt", "text/plain", False, "file_too_large"),
        ([b"abc\x00def"], "input.txt", "text/plain", False, "file_type_invalid"),
    ]
    for chunks, name, media_type, output, error_code in invalid_cases:
        with pytest.raises(NonRetryableExecutionError) as error:
            validator.validate_and_copy(
                chunks,
                io.BytesIO(),
                display_name=name,
                media_type=media_type,
                agent_output=output,
            )
        assert error.value.error_code == error_code


def _workspace_with_file(
    repository: FileWorkspaceRepository,
    *,
    workspace_id: str,
    file_id: str,
    version_id: str,
    size_bytes: int,
) -> None:
    repository.create_file(
        file_id=file_id,
        tenant_id="tenant-a",
        owner=_owner(),
        display_name=f"{file_id}.txt",
        actor_id="user-a",
    )
    repository.create_version(
        version_id=version_id,
        file_id=file_id,
        version_number=1,
        version_kind=FileVersionKind.WORKING,
        status=FileVersionStatus.AVAILABLE,
        media_type="text/plain",
        encoding="utf-8",
        size_bytes=size_bytes,
        content_sha256=f"{int(file_id.rsplit('-', 1)[-1]) + 1:064x}",
        object_key=f"opaque/{version_id}",
        source_kind=FileSourceKind.AGENT_GENERATED,
        actor_id="user-a",
        advance_current_from="",
    )
    repository.link_workspace_file(
        workspace_id=workspace_id,
        file_id=file_id,
        version_id=version_id,
        logical_name=f"{file_id}.txt",
        role=WorkspaceFileRole.WORKING,
    )


def test_workspace_quota_counts_logical_files_and_only_unretained_temporary_content() -> None:
    database = _database()
    repository = FileWorkspaceRepository(database)
    repository.create_workspace(
        workspace_id="workspace-quota",
        tenant_id="tenant-a",
        session_id="session-file",
        owner=_owner(),
        publication_id="app-file-p1",
        retention_period=RetentionPeriod.WEEK,
        expires_at="2026-08-17T00:00:00+08:00",
        actor_id="user-a",
    )
    for index in range(200):
        _workspace_with_file(
            repository,
            workspace_id="workspace-quota",
            file_id=f"file-{index}",
            version_id=f"version-{index}",
            size_bytes=5,
        )
    quota = WorkspaceQuotaService(database)
    usage = quota.usage("workspace-quota", now=TIMESTAMP)
    assert usage.file_count == 200
    assert usage.temporary_bytes == 1000
    with pytest.raises(NonRetryableExecutionError) as error:
        quota.require_commit_capacity(
            workspace_id="workspace-quota",
            incoming_bytes=1,
            creates_logical_file=True,
            now=TIMESTAMP,
        )
    assert error.value.error_code == "workspace_file_limit_exceeded"

    repository.add_retention(
        version_id="version-0",
        reason=RetentionReason.USER_SAVED,
        source_id="save-a",
        starts_at=TIMESTAMP,
        expires_at="2027-08-09T00:00:00+00:00",
    )
    assert quota.usage("workspace-quota", now=TIMESTAMP).temporary_bytes == 995
    database.execute(
        """
        insert into file_processing_run
          (id, tenant_id, source_file_id, source_version_id, processor_code,
           processor_version, processor_build_digest, profile_code, profile_hash,
           status, source_size_bytes, completed_at, created_by, created_at, updated_at)
        values ('quota-run', 'tenant-a', 'file-0', 'version-0', 'docling-serve',
                '1.30.0', ?, 'docling-layout-ocr-v1', ?, 'SUCCEEDED', 5, ?,
                'file-worker', ?, ?)
        """,
        ("sha256:" + "2" * 64, "3" * 64, TIMESTAMP, TIMESTAMP, TIMESTAMP),
    )
    database.execute(
        """
        insert into file_representation
          (id, processing_run_id, tenant_id, source_file_id, source_version_id,
           kind, media_type, encoding, status, size_bytes, content_sha256,
           object_key, profile_hash, created_at)
        values ('quota-representation', 'quota-run', 'tenant-a', 'file-0',
                'version-0', 'MARKDOWN', 'text/markdown', 'utf-8', 'AVAILABLE',
                5, ?, 'opaque/quota-derived', ?, ?)
        """,
        ("4" * 64, "3" * 64, TIMESTAMP),
    )
    database.execute(
        """
        insert into document_parent_artifact_transfer
          (id, processing_run_id, kind, token_hash, expected_size_bytes,
           expected_sha256, received_size_bytes, received_sha256,
           staging_object_key, status, expires_at, created_at, updated_at, finalized_at)
        values ('quota-parent-transfer', 'quota-run', 'PARENT_MARKDOWN', ?, 5, ?,
                5, ?, 'opaque/quota-derived', 'FINALIZED', ?, ?, ?, ?)
        """,
        (
            "5" * 64,
            "4" * 64,
            "4" * 64,
            "2026-08-22T00:00:00+00:00",
            TIMESTAMP,
            TIMESTAMP,
            TIMESTAMP,
        ),
    )
    assert quota.usage("workspace-quota", now=TIMESTAMP).temporary_bytes == 1000
    database.execute(
        "update managed_file_version set size_bytes = ? where id = 'version-1'",
        (MAX_TEMPORARY_BYTES,),
    )
    with pytest.raises(NonRetryableExecutionError) as error:
        quota.require_commit_capacity(
            workspace_id="workspace-quota",
            incoming_bytes=1,
            creates_logical_file=False,
            now=TIMESTAMP,
        )
    assert error.value.error_code == "workspace_quota_exceeded"


def test_workspace_quota_reservations_are_concurrency_safe_and_lowering_is_read_only() -> None:
    database = _database()
    repository = FileWorkspaceRepository(database)
    repository.create_workspace(
        workspace_id="workspace-reservations",
        tenant_id="tenant-a",
        session_id="session-file",
        owner=_owner(),
        publication_id="app-file-p1",
        retention_period=RetentionPeriod.WEEK,
        expires_at="2026-08-17T00:00:00+08:00",
        actor_id="user-a",
    )
    quota = WorkspaceQuotaService(database)

    def reserve(index: int) -> str:
        try:
            quota.reserve(
                workspace_id="workspace-reservations",
                operation_type="ATTACHMENT_IMPORT",
                operation_id=f"concurrent-{index}",
                logical_file_slots=1,
                billable_bytes=1,
                expires_at="2026-08-22T00:00:00+00:00",
                now=TIMESTAMP,
            )
            return "reserved"
        except NonRetryableExecutionError as exc:
            return exc.error_code

    with ThreadPoolExecutor(max_workers=16) as pool:
        outcomes = list(pool.map(reserve, range(205)))
    assert outcomes.count("reserved") == 200
    assert outcomes.count("workspace_file_limit_exceeded") == 5
    usage = quota.usage("workspace-reservations", now=TIMESTAMP)
    assert usage.reserved_file_slots == 200
    assert usage.reserved_billable_bytes == 200

    reserved_operations = database.execute(
        """
        select operation_id from task_workspace_quota_reservation
         where workspace_id = 'workspace-reservations' and status = 'RESERVED'
        """
    )
    for row in reserved_operations:
        quota.finalize_operation(
            workspace_id="workspace-reservations",
            operation_type="ATTACHMENT_IMPORT",
            operation_id=str(row["operation_id"]),
            committed=False,
            now=TIMESTAMP,
        )
    _workspace_with_file(
        repository,
        workspace_id="workspace-reservations",
        file_id="existing-file-0",
        version_id="existing-version-0",
        size_bytes=5,
    )
    config_repository = PlatformConfigRepository(database)
    RuntimeConfigRegistry(config_repository).ensure_builtin_definitions()
    config_repository.upsert_runtime_config_value(
        key="FILE_WORKSPACE_ACTIVE_FILE_LIMIT",
        scope_type="service",
        scope_code="file-service",
        service_name="file-service",
        value=1,
    )
    assert repository.require_content_available("existing-version-0")["size_bytes"] == 5
    with pytest.raises(NonRetryableExecutionError) as lowered:
        quota.reserve(
            workspace_id="workspace-reservations",
            operation_type="ATTACHMENT_IMPORT",
            operation_id="after-lowering",
            logical_file_slots=1,
            billable_bytes=1,
            expires_at="2026-08-22T00:00:00+00:00",
            now=TIMESTAMP,
        )
    assert lowered.value.error_code == "workspace_file_limit_exceeded"


def test_deleted_internal_content_is_terminal_even_when_external_reference_remains() -> None:
    database = _database()
    repository = FileWorkspaceRepository(database)
    repository.create_file(
        file_id="file-0",
        tenant_id="tenant-a",
        owner=_owner(),
        display_name="source.txt",
        actor_id="user-a",
    )
    repository.create_version(
        version_id="version-0",
        file_id="file-0",
        version_number=1,
        version_kind=FileVersionKind.ATTACHMENT,
        status=FileVersionStatus.AVAILABLE,
        media_type="text/plain",
        encoding="utf-8",
        size_bytes=5,
        content_sha256="a" * 64,
        object_key="opaque/version-0",
        source_kind=FileSourceKind.MESSAGE_ATTACHMENT,
        actor_id="user-a",
        advance_current_from="",
    )
    repository.add_external_reference(
        file_id="file-0",
        version_id="version-0",
        provider="DINGTALK",
        source_type="DRIVE_FILE",
        source_id="still-exists-online",
    )
    version = repository.mark_content_unavailable(
        version_id="version-0", deleted_at=TIMESTAMP
    )
    assert version["status"] == "CONTENT_UNAVAILABLE"
    assert repository.get_file("file-0")["status"] == "CONTENT_UNAVAILABLE"
    assert database.execute_one(
        "select source_id from file_external_reference where version_id = 'version-0'"
    )["source_id"] == "still-exists-online"
    with pytest.raises(NonRetryableExecutionError) as error:
        repository.require_content_available("version-0")
    assert error.value.error_code == "file_content_unavailable"
    assert "重新" in error.value.safe_message
