from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime, timedelta

import pytest
from PIL import Image
from pypdf import PdfWriter

from app.modules.document_processing import (
    DOCLING_TEXT_V1,
    DocumentProcessingRepository,
    GovernedDocumentProcessingService,
    SourceStreamGrantSigner,
    validate_document_source,
)
from app.modules.file_workspace.domain import (
    CleanupResourceType,
    FileOwner,
    FileSourceKind,
    FileVersionKind,
    FileVersionStatus,
    WorkspaceOwnerType,
)
from app.modules.file_workspace.lifecycle_service import FileLifecycleService
from app.modules.file_workspace.domain_outbox import FileDomainOutboxPublisher
from app.modules.file_workspace.repository import FileWorkspaceRepository
from app.modules.file_workspace.storage import InternalStoredObject
from app.shared.database import Database, default_migrations_dir
from app.shared.exceptions import NonRetryableExecutionError, PermissionDenied
from app.shared.migrations import Migrator


NOW = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
PROCESSOR_DIGEST = "sha256:" + "a" * 64


class _Storage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.sequence = 0

    def new_object_key(self, *, kind: str) -> str:
        self.sequence += 1
        return f"managed/{kind}/opaque-{self.sequence}"

    def put_stream(
        self,
        stream: io.BufferedIOBase,
        *,
        kind: str,
        content_type: str,
        content_sha256: str,
        size_bytes: int,
        internal_object_key: str | None = None,
    ) -> InternalStoredObject:
        del content_type
        body = stream.read()
        assert len(body) == size_bytes
        assert hashlib.sha256(body).hexdigest() == content_sha256
        key = internal_object_key or self.new_object_key(kind=kind)
        self.objects[key] = body
        return InternalStoredObject(key, size_bytes, content_sha256)

    def open_stream(self, *, internal_object_key: str) -> io.BytesIO:
        return io.BytesIO(self.objects[internal_object_key])

    def delete(self, *, internal_object_key: str) -> None:
        self.objects.pop(internal_object_key, None)

    def exists(self, *, internal_object_key: str) -> bool:
        return internal_object_key in self.objects

    def list_keys(self) -> list[str]:
        return sorted(self.objects)


def _database() -> Database:
    database = Database("sqlite:///:memory:")
    Migrator(
        database,
        default_migrations_dir(),
        migrator_build="document-processing-service-test",
    ).run()
    return database


def _source(
    database: Database,
    storage: _Storage,
    *,
    tenant_id: str = "tenant-default",
) -> tuple[FileWorkspaceRepository, str, str, bytes]:
    file_repository = FileWorkspaceRepository(database)
    body = _pdf_bytes(2)
    file_id = "managed_file_document_source"
    version_id = "managed_file_version_document_source"
    object_key = storage.new_object_key(kind="attachment")
    storage.objects[object_key] = body
    file_repository.create_file(
        file_id=file_id,
        tenant_id=tenant_id,
        owner=FileOwner(
            owner_type=WorkspaceOwnerType.PRIVATE_USER,
            user_id="user-document-owner",
        ),
        display_name="source.pdf",
        actor_id="file-worker",
        format_code="PDF",
    )
    file_repository.create_version(
        version_id=version_id,
        file_id=file_id,
        version_number=1,
        version_kind=FileVersionKind.ATTACHMENT,
        status=FileVersionStatus.AVAILABLE,
        media_type="application/pdf",
        encoding="",
        size_bytes=len(body),
        content_sha256=hashlib.sha256(body).hexdigest(),
        object_key=object_key,
        source_kind=FileSourceKind.MESSAGE_ATTACHMENT,
        actor_id="file-worker",
        format_code="PDF",
        advance_current_from="",
    )
    return file_repository, file_id, version_id, body


def _service() -> tuple[
    Database,
    _Storage,
    GovernedDocumentProcessingService,
    str,
    str,
    bytes,
]:
    database = _database()
    storage = _Storage()
    file_repository, file_id, version_id, body = _source(database, storage)
    repository = DocumentProcessingRepository(database)
    service = GovernedDocumentProcessingService(
        repository,
        file_repository,
        storage,
        SourceStreamGrantSigner(b"document-processing-test-signing-key-32"),
        processor_version="1.30.0",
        processor_build_digest=PROCESSOR_DIGEST,
    )
    return database, storage, service, file_id, version_id, body


def test_processing_request_is_idempotent_and_outbox_payload_is_bounded() -> None:
    database, _storage, service, file_id, version_id, _body = _service()
    run = service.request_processing(
        tenant_id="tenant-default",
        source_file_id=file_id,
        source_version_id=version_id,
        actor_id="file-worker",
        correlation_id="correlation-safe",
    )
    repeated = service.request_processing(
        tenant_id="tenant-default",
        source_file_id=file_id,
        source_version_id=version_id,
        actor_id="file-worker",
        correlation_id="ignored-on-repeat",
    )
    assert repeated["id"] == run["id"]
    assert run["status"] == "QUEUED"
    assert run["profile_hash"] == DOCLING_TEXT_V1.profile_hash
    events = database.execute(
        "select * from file_domain_outbox where event_type = 'file.processing.requested'"
    )
    assert len(events) == 1
    projected = FileDomainOutboxPublisher._safe_event(events[0])
    assert projected["payload"] == {
        "attempt": 0,
        "contract_version": "file-processing/v1",
        "correlation_id": "correlation-safe",
        "profile_hash": DOCLING_TEXT_V1.profile_hash,
        "run_id": run["id"],
        "source_version_id": version_id,
    }
    assert (
        not {
            "content",
            "base64",
            "object_key",
            "display_name",
            "token",
            "url",
        }
        & projected["payload"].keys()
    )

    with pytest.raises(PermissionDenied):
        service.request_processing(
            tenant_id="tenant-other",
            source_file_id=file_id,
            source_version_id=version_id,
            actor_id="file-worker",
            correlation_id="safe",
        )


def test_source_stream_grant_binds_tenant_principal_run_and_expiry() -> None:
    _database_value, _storage, service, file_id, version_id, body = _service()
    run = service.request_processing(
        tenant_id="tenant-default",
        source_file_id=file_id,
        source_version_id=version_id,
        actor_id="file-worker",
        correlation_id="safe",
    )
    with service.repository.database.unit_of_work():
        claimed = service.repository.claim_due_run(worker_id="processing-worker-1")
    assert claimed is not None
    grant = service.prepare_source_stream(
        run_id=str(run["id"]),
        tenant_id="tenant-default",
        service_principal_id="file-processing-worker",
        now=NOW,
    )
    assert (
        service.open_source_stream(
            grant=grant["grant"],
            service_principal_id="file-processing-worker",
            now=NOW + timedelta(minutes=1),
        ).read()
        == body
    )
    with pytest.raises(PermissionDenied):
        service.open_source_stream(
            grant=grant["grant"],
            service_principal_id="other-worker",
            now=NOW + timedelta(minutes=1),
        )
    with pytest.raises(PermissionDenied):
        service.open_source_stream(
            grant=grant["grant"],
            service_principal_id="file-processing-worker",
            now=NOW + timedelta(minutes=6),
        )


def test_lost_docling_task_retry_clears_only_the_persisted_external_task() -> None:
    database, _storage, service, file_id, version_id, _body = _service()
    run = service.request_processing(
        tenant_id="tenant-default",
        source_file_id=file_id,
        source_version_id=version_id,
        actor_id="file-worker",
        correlation_id="safe",
    )
    with database.unit_of_work():
        claimed = service.repository.claim_due_run(worker_id="processing-worker-1")
    assert claimed is not None
    service.mark_submitted(run_id=str(run["id"]), external_task_id="task-lost")
    retried = service.schedule_retry(
        run_id=str(run["id"]),
        error_code="docling_task_not_found",
        delay_seconds=30,
        now=NOW,
    )
    assert retried["status"] == "RETRY_WAIT"
    assert retried["external_task_id"] == ""


def test_submitted_run_reaches_every_terminal_state_like_the_real_worker_order() -> None:
    database, _storage, service, file_id, version_id, _body = _service()
    run = service.request_processing(
        tenant_id="tenant-default",
        source_file_id=file_id,
        source_version_id=version_id,
        actor_id="file-worker",
        correlation_id="safe",
    )
    with database.unit_of_work():
        claimed = service.repository.claim_due_run(worker_id="processing-worker-1")
    assert claimed is not None
    # The worker marks the run SUBMITTED before it polls Docling, so the terminal
    # transitions have to be reachable from SUBMITTED rather than only from RUNNING.
    submitted = service.mark_submitted(run_id=str(run["id"]), external_task_id="task-1")
    assert submitted["status"] == "SUBMITTED"

    markdown = b"# Extracted\n\nSafe text.\n"
    docling_json = json.dumps(
        {"schema_name": "DoclingDocument", "texts": []}, sort_keys=True
    ).encode()
    for kind, media_type, content in (
        ("MARKDOWN", "text/markdown", markdown),
        ("DOCLING_JSON", "application/json", docling_json),
    ):
        prepared = service.prepare_representation_transfer(
            run_id=str(run["id"]),
            kind=kind,
            expected_size_bytes=len(content),
            expected_sha256=hashlib.sha256(content).hexdigest(),
            now=NOW,
        )
        service.upload_representation(
            transfer_id=prepared["transfer_id"],
            upload_token=prepared["upload_token"],
            stream=io.BytesIO(content),
            media_type=media_type,
            now=NOW,
        )
    representations = service.finalize(
        run_id=str(run["id"]),
        partial=False,
        page_count=2,
        processing_time_ms=1250,
    )

    assert {item["status"] for item in representations} == {"AVAILABLE"}
    assert service.repository.get_run(str(run["id"]))["status"] == "SUCCEEDED"


def test_submitted_run_can_complete_without_text() -> None:
    database, _storage, service, file_id, version_id, _body = _service()
    run = service.request_processing(
        tenant_id="tenant-default",
        source_file_id=file_id,
        source_version_id=version_id,
        actor_id="file-worker",
        correlation_id="safe",
    )
    with database.unit_of_work():
        assert service.repository.claim_due_run(worker_id="processing-worker-1") is not None
    service.mark_submitted(run_id=str(run["id"]), external_task_id="task-2")

    completed = service.complete_without_text(
        run_id=str(run["id"]),
        page_count=1,
        processing_time_ms=100,
    )

    assert completed["status"] == "NO_TEXT"


def test_two_staged_outputs_become_visible_atomically_and_finalize_is_idempotent() -> None:
    database, storage, service, file_id, version_id, _body = _service()
    run = service.request_processing(
        tenant_id="tenant-default",
        source_file_id=file_id,
        source_version_id=version_id,
        actor_id="file-worker",
        correlation_id="safe",
    )
    with database.unit_of_work():
        claimed = service.repository.claim_due_run(worker_id="processing-worker-1")
    assert claimed is not None
    markdown = b"# Extracted\n\nSafe text.\n"
    docling_json = json.dumps(
        {"schema_name": "DoclingDocument", "texts": []}, sort_keys=True
    ).encode()
    staged = {}
    for kind, media_type, content in (
        ("MARKDOWN", "text/markdown", markdown),
        ("DOCLING_JSON", "application/json", docling_json),
    ):
        prepared = service.prepare_representation_transfer(
            run_id=str(run["id"]),
            kind=kind,
            expected_size_bytes=len(content),
            expected_sha256=hashlib.sha256(content).hexdigest(),
            now=NOW,
        )
        staged[kind] = service.upload_representation(
            transfer_id=prepared["transfer_id"],
            upload_token=prepared["upload_token"],
            stream=io.BytesIO(content),
            media_type=media_type,
            now=NOW,
        )
    assert service.repository.list_representations(str(run["id"])) == []
    representations = service.finalize(
        run_id=str(run["id"]),
        partial=False,
        page_count=2,
        processing_time_ms=1250,
    )
    assert {item["kind"] for item in representations} == {
        "MARKDOWN",
        "DOCLING_JSON",
    }
    assert {item["status"] for item in representations} == {"AVAILABLE"}
    assert service.repository.get_run(str(run["id"]))["status"] == "SUCCEEDED"
    completion = database.execute_one(
        """
        select payload_json from file_domain_outbox
         where event_type = 'file.processing.completed' and aggregate_id = ?
        """,
        (run["id"],),
    )
    assert completion is not None
    assert json.loads(str(completion["payload_json"]))["status"] == "SUCCEEDED"
    assert len(storage.objects) == 3
    repeated = service.finalize(
        run_id=str(run["id"]),
        partial=False,
        page_count=2,
        processing_time_ms=1250,
    )
    assert [item["id"] for item in repeated] == [item["id"] for item in representations]
    assert database.execute_one(
        """
        select count(*) as value from file_domain_outbox
         where event_type = 'file.processing.completed' and aggregate_id = ?
        """,
        (run["id"],),
    ) == {"value": 1}
    assert staged["MARKDOWN"]["status"] == "STAGED"


def test_representation_rejects_wrong_token_media_digest_and_partial_visibility() -> None:
    database, _storage, service, file_id, version_id, _body = _service()
    run = service.request_processing(
        tenant_id="tenant-default",
        source_file_id=file_id,
        source_version_id=version_id,
        actor_id="file-worker",
        correlation_id="safe",
    )
    with database.unit_of_work():
        service.repository.claim_due_run(worker_id="processing-worker-1")
    content = b"safe markdown"
    prepared = service.prepare_representation_transfer(
        run_id=str(run["id"]),
        kind="MARKDOWN",
        expected_size_bytes=len(content),
        expected_sha256=hashlib.sha256(content).hexdigest(),
        now=NOW,
    )
    with pytest.raises(PermissionDenied):
        service.upload_representation(
            transfer_id=prepared["transfer_id"],
            upload_token="wrong-token",
            stream=io.BytesIO(content),
            media_type="text/markdown",
            now=NOW,
        )
    with pytest.raises(NonRetryableExecutionError) as media_error:
        service.upload_representation(
            transfer_id=prepared["transfer_id"],
            upload_token=prepared["upload_token"],
            stream=io.BytesIO(content),
            media_type="text/plain",
            now=NOW,
        )
    assert media_error.value.error_code == "document_representation_media_type_invalid"
    with pytest.raises(NonRetryableExecutionError) as digest_error:
        service.upload_representation(
            transfer_id=prepared["transfer_id"],
            upload_token=prepared["upload_token"],
            stream=io.BytesIO(content + b"!"),
            media_type="text/markdown",
            now=NOW,
        )
    assert digest_error.value.error_code == "document_representation_digest_mismatch"
    service.upload_representation(
        transfer_id=prepared["transfer_id"],
        upload_token=prepared["upload_token"],
        stream=io.BytesIO(content),
        media_type="text/markdown",
        now=NOW,
    )
    with pytest.raises(NonRetryableExecutionError) as incomplete:
        service.finalize(
            run_id=str(run["id"]),
            partial=False,
            page_count=1,
            processing_time_ms=100,
        )
    assert incomplete.value.error_code == "document_representation_incomplete"
    assert service.repository.list_representations(str(run["id"])) == []


def test_document_source_sniffing_rejects_mismatch_and_accepts_fixed_formats() -> None:
    pdf = _pdf_bytes(2)
    result = validate_document_source(
        io.BytesIO(pdf),
        display_name="safe.pdf",
        declared_media_type="application/pdf",
        declared_size_bytes=len(pdf),
    )
    assert result.format_code.value == "PDF"
    assert result.page_count == 2

    with pytest.raises(NonRetryableExecutionError) as mismatch:
        validate_document_source(
            io.BytesIO(pdf),
            display_name="safe.png",
            declared_media_type="image/png",
            declared_size_bytes=len(pdf),
        )
    assert mismatch.value.error_code in {
        "document_source_signature_mismatch",
        "document_source_malformed",
    }

    png = io.BytesIO()
    Image.new("RGB", (2, 2), color="white").save(png, format="PNG")
    png_body = png.getvalue()
    assert (
        validate_document_source(
            io.BytesIO(png_body),
            display_name="safe.png",
            declared_media_type="image/png",
            declared_size_bytes=len(png_body),
        ).format_code.value
        == "PNG"
    )

    docx = _ooxml_bytes("word/document.xml")
    assert (
        validate_document_source(
            io.BytesIO(docx),
            display_name="safe.docx",
            declared_media_type=(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
            declared_size_bytes=len(docx),
        ).format_code.value
        == "DOCX"
    )


def test_representation_cleanup_follows_source_version_lifecycle() -> None:
    database, storage, service, file_id, version_id, _body = _service()
    run = service.request_processing(
        tenant_id="tenant-default",
        source_file_id=file_id,
        source_version_id=version_id,
        actor_id="file-worker",
        correlation_id="safe",
    )
    with database.unit_of_work():
        service.repository.claim_due_run(worker_id="processing-worker-1")
    for kind, media_type, content in (
        ("MARKDOWN", "text/markdown", b"safe text"),
        ("DOCLING_JSON", "application/json", b'{"texts": []}'),
    ):
        prepared = service.prepare_representation_transfer(
            run_id=str(run["id"]),
            kind=kind,
            expected_size_bytes=len(content),
            expected_sha256=hashlib.sha256(content).hexdigest(),
            now=NOW,
        )
        service.upload_representation(
            transfer_id=prepared["transfer_id"],
            upload_token=prepared["upload_token"],
            stream=io.BytesIO(content),
            media_type=media_type,
            now=NOW,
        )
    representations = service.finalize(
        run_id=str(run["id"]),
        partial=False,
        page_count=1,
        processing_time_ms=100,
    )
    service.file_repository.enqueue_cleanup(
        resource_type=CleanupResourceType.FILE_VERSION,
        resource_id=version_id,
        reason="SOURCE_RETENTION_EXPIRED",
        due_at=NOW.isoformat(),
    )
    result = FileLifecycleService(
        service.file_repository,
        storage,
        now=lambda: NOW + timedelta(minutes=1),
    ).run_once()
    assert int(result["cleanup_completed"]) >= 1
    assert service.file_repository.get_version(version_id)["status"] == ("CONTENT_UNAVAILABLE")
    retired = service.repository.list_representations(str(run["id"]))
    assert {item["status"] for item in retired} == {"CONTENT_UNAVAILABLE"}
    assert all(str(item["object_key"]) not in storage.objects for item in representations)


def _pdf_bytes(page_count: int) -> bytes:
    output = io.BytesIO()
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=72, height=72)
    writer.write(output)
    return output.getvalue()


def _ooxml_bytes(required_part: str) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr(required_part, "<document />")
    return output.getvalue()
