from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime, timedelta

import pytest
from PIL import Image
from pypdf import PdfWriter

from app.modules.audit.application.audit_service import AuditService
from app.modules.document_processing import (
    DOCLING_LAYOUT_OCR_V2,
    DocumentProcessingRepository,
    GovernedDocumentProcessingService,
    PictureItemStatus,
    SourceStreamGrantSigner,
    validate_document_source,
)
from app.modules.document_processing.layout_ocr import assemble_layout_representation
from app.modules.document_processing.image_normalization import normalize_picture_asset
from app.modules.document_processing.layout_ocr import (
    adapt_docling_picture_result,
    append_layout_ocr_markdown,
)
from app.modules.file_workspace.domain import (
    CleanupResourceType,
    FileOwner,
    FileSourceKind,
    FileVersionKind,
    FileVersionStatus,
    RetentionPeriod,
    WorkspaceFileRole,
    WorkspaceOwnerType,
)
from app.modules.file_workspace.lifecycle_service import FileLifecycleService
from app.modules.file_workspace.domain_outbox import FileDomainOutboxPublisher
from app.modules.file_workspace.repository import FileWorkspaceRepository
from app.modules.file_workspace.storage import InternalStoredObject
from app.modules.job.infrastructure.repositories import AuditRepository
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
    timestamp = NOW.isoformat()
    database.execute(
        """
        insert into business_application
          (id, code, name, project_code, status, revision,
           created_by, created_at, updated_at)
        values ('document-app', 'document-app', 'Document App', 'default',
                'enabled', 1, 'file-worker', ?, ?)
        """,
        (timestamp, timestamp),
    )
    database.execute(
        """
        insert into business_application_revision
          (id, application_id, revision, status, created_by, created_at, updated_at)
        values ('document-app-r1', 'document-app', 1, 'published',
                'file-worker', ?, ?)
        """,
        (timestamp, timestamp),
    )
    database.execute(
        """
        insert into business_application_publication
          (id, application_id, revision_id, revision, schema_version,
           snapshot_json, config_hash, published_by, published_at)
        values ('document-app-p1', 'document-app', 'document-app-r1', 1, 1,
                '{}', ?, 'file-worker', ?)
        """,
        ("a" * 64, timestamp),
    )
    database.execute(
        """
        insert into agent_session
          (id, source_channel, source_connector_id, external_conversation_id,
           requester_id, project_code, session_key, created_at, updated_at)
        values ('document-session', 'test', 'document-connector',
                'document-conversation', 'user-document-owner', 'default',
                'document-session', ?, ?)
        """,
        (timestamp, timestamp),
    )
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
    owner = FileOwner(
        owner_type=WorkspaceOwnerType.PRIVATE_USER,
        user_id="user-document-owner",
    )
    file_repository.create_workspace(
        workspace_id="document-workspace",
        tenant_id=tenant_id,
        session_id="document-session",
        owner=owner,
        publication_id="document-app-p1",
        retention_period=RetentionPeriod.WEEK,
        expires_at="2026-08-24T00:00:00+00:00",
        actor_id="file-worker",
    )
    file_repository.create_file(
        file_id=file_id,
        tenant_id=tenant_id,
        owner=owner,
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
    file_repository.link_workspace_file(
        workspace_id="document-workspace",
        file_id=file_id,
        version_id=version_id,
        logical_name="source.pdf",
        role=WorkspaceFileRole.INPUT,
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
        AuditService(AuditRepository(database)),
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
    assert run["profile_hash"] == DOCLING_LAYOUT_OCR_V2.profile_hash
    events = database.execute(
        "select * from file_domain_outbox where event_type = 'file.processing.requested'"
    )
    assert len(events) == 1
    projected = FileDomainOutboxPublisher._safe_event(events[0])
    assert projected["payload"] == {
        "attempt": 0,
        "contract_version": "file-processing/v1",
        "correlation_id": "correlation-safe",
        "profile_hash": DOCLING_LAYOUT_OCR_V2.profile_hash,
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


def test_layout_profile_freezes_three_outputs_deadline_and_unique_picture_assembly() -> None:
    database, storage, service, file_id, version_id, _body = _service()
    run = service.request_processing(
        tenant_id="tenant-default",
        source_file_id=file_id,
        source_version_id=version_id,
        actor_id="file-worker",
        correlation_id="layout-run",
        profile_code="docling-layout-ocr-v2",
    )
    assert run["profile_hash"] == DOCLING_LAYOUT_OCR_V2.profile_hash
    assert json.loads(str(run["required_output_kinds_json"])) == [
        "MARKDOWN",
        "DOCLING_JSON",
        "OCR_LAYOUT_JSON",
    ]
    assert run["run_deadline_at"]
    with database.unit_of_work():
        assert service.repository.claim_due_run(worker_id="layout-parent") is not None
        object_key = storage.new_object_key(kind="picture")
        asset, created = service.repository.create_or_get_picture_asset(
            run_id=str(run["id"]),
            normalized_sha256="b" * 64,
            media_type="image/png",
            original_width_pixels=32,
            original_height_pixels=24,
            width_pixels=32,
            height_pixels=24,
            normalization_transform_json=json.dumps(
                {
                    "version": "embedded-media-exif-orientation/v1",
                    "pixel_basis": "RAW_EMBEDDED_MEDIA_AFTER_EXIF",
                    "office_display_transform_applied": False,
                    "source_origin": "TOPLEFT",
                    "target_origin": "TOPLEFT",
                    "exif_orientation": 1,
                    "original_size": [32, 24],
                    "normalized_size": [32, 24],
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            size_bytes=256,
            object_key=object_key,
        )
        assert created
        transfer, _ = service.repository.create_or_get_picture_asset_transfer(
            picture_asset_id=str(asset["id"]),
            token_hash="c" * 64,
            staging_object_key=object_key,
            expires_at=(NOW + timedelta(minutes=10)).isoformat(),
        )
        finalized_asset = service.repository.finalize_picture_asset_transfer(
            transfer_id=str(transfer["id"]),
            received_size_bytes=256,
            received_sha256="b" * 64,
        )
        assert finalized_asset["status"] == "AVAILABLE"
        occurrence, _ = service.repository.create_or_get_picture_occurrence(
            run_id=str(run["id"]),
            picture_asset_id=str(asset["id"]),
            occurrence_index=1,
            source_format="DOCX",
            picture_ref="#/pictures/0",
            parent_ref="#/body",
            parent_label="body",
            parent_ordinal=0,
            slide_no=None,
            parent_bbox_json="",
        )
        assert occurrence["picture_ref"] == "#/pictures/0"
        skipped_occurrence, _ = service.repository.create_or_get_picture_occurrence(
            run_id=str(run["id"]),
            picture_asset_id=str(asset["id"]),
            occurrence_index=2,
            source_format="DOCX",
            picture_ref="#/pictures/1",
            parent_ref="#/body",
            parent_label="body",
            parent_ordinal=1,
            slide_no=None,
            parent_bbox_json="",
            selection_status="SKIPPED_LIMIT",
        )
        assert skipped_occurrence["selection_status"] == "SKIPPED_LIMIT"
        item, item_created = service.repository.create_or_get_picture_item(
            run_id=str(run["id"]),
            picture_asset_id=str(asset["id"]),
            occurrence_count=2,
            ocr_engine_code="docling-rapidocr",
            model_revision="v1.30.0",
            model_digest="sha256:" + "d" * 64,
            correlation_id="layout-run",
        )
        assert item_created

    replayed, replay_created = service.repository.create_or_get_picture_item(
        run_id=str(run["id"]),
        picture_asset_id=str(asset["id"]),
        occurrence_count=2,
        ocr_engine_code="docling-rapidocr",
        model_revision="v1.30.0",
        model_digest="sha256:" + "d" * 64,
        correlation_id="layout-run-replay",
    )
    assert replayed["id"] == item["id"]
    assert replay_created is False
    claimed, did_claim = service.repository.claim_picture_item(
        picture_item_id=str(item["id"]),
        claim_token="claim-a",
        claim_expires_at=(NOW + timedelta(minutes=2)).isoformat(),
    )
    assert did_claim and claimed["attempt"] == 1
    duplicate_claim, did_duplicate_claim = service.repository.claim_picture_item(
        picture_item_id=str(item["id"]),
        claim_token="claim-b",
        claim_expires_at=(NOW + timedelta(minutes=2)).isoformat(),
    )
    assert duplicate_claim["id"] == item["id"]
    assert did_duplicate_claim is False
    database.execute(
        "update file_processing_run set stage_code = 'PICTURE_OCR' where id = ?",
        (run["id"],),
    )
    completed = service.repository.complete_picture_item(
        picture_item_id=str(item["id"]),
        status=PictureItemStatus.AVAILABLE,
        result_size_bytes=128,
        result_sha256="e" * 64,
        correlation_id="layout-run",
    )
    assert completed["status"] == "AVAILABLE"
    service.repository.complete_picture_item(
        picture_item_id=str(item["id"]),
        status=PictureItemStatus.AVAILABLE,
        result_size_bytes=128,
        result_sha256="e" * 64,
        correlation_id="layout-run-replay",
    )
    outbox = database.execute(
        "select * from document_processing_stage_outbox order by event_type"
    )
    assert [row["event_type"] for row in outbox] == [
        "ASSEMBLY_REQUESTED",
        "PICTURE_OCR_REQUESTED",
    ]
    assert all("object_key" not in str(row["payload_json"]) for row in outbox)
    assembly, assembly_claimed = service.repository.claim_assembly(
        run_id=str(run["id"]), claim_token="assembly-a"
    )
    assert assembly_claimed and assembly["assembly_attempt"] == 1
    repeated_assembly, repeated_claimed = service.repository.claim_assembly(
        run_id=str(run["id"]), claim_token="assembly-b"
    )
    assert repeated_assembly["id"] == run["id"]
    assert repeated_claimed is False
    context = service.assembly_context(run_id=str(run["id"]))
    assert [item["status"] for item in context["occurrences"]] == [
        "AVAILABLE",
        "SKIPPED_LIMIT",
    ]
    assert context["occurrences"][1]["error_code"] == "picture_soft_limit"

    metrics = service.repository.processing_summary()
    assert set(metrics) == {
        "groups",
        "stage_backlog",
        "picture_items",
        "stage_outbox",
        "staging",
        "cleanup",
    }
    assert metrics["picture_items"][0]["status"] == "AVAILABLE"
    assert {row["event_type"] for row in metrics["stage_outbox"]} == {
        "PICTURE_OCR_REQUESTED",
        "ASSEMBLY_REQUESTED",
    }
    serialized_metrics = json.dumps(metrics, sort_keys=True)
    for forbidden in (
        "source.pdf",
        "managed/",
        "#/pictures/0",
        "object_key",
        "picture_ref",
        "normalization_transform",
    ):
        assert forbidden not in serialized_metrics


def test_source_stream_grant_binds_tenant_principal_run_and_expiry() -> None:
    database, _storage, service, file_id, version_id, body = _service()
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
    with pytest.raises(PermissionDenied):
        service.prepare_source_stream(
            run_id=str(run["id"]),
            tenant_id="tenant-other",
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
    audit_rows = database.execute(
        """
        select event_type, status, payload_summary from audit_event
         where event_type like 'file.document.source_%'
         order by created_at, id
        """
    )
    assert [row["event_type"] for row in audit_rows].count(
        "file.document.source_grant.issued"
    ) == 1
    assert [row["event_type"] for row in audit_rows].count(
        "file.document.source_stream.opened"
    ) == 1
    assert [row["status"] for row in audit_rows].count("DENIED") == 3
    serialized = json.dumps(audit_rows)
    for forbidden in (
        grant["grant"],
        "document.pdf",
        "object/source",
        body.hex()[:32],
        "test-signing-key",
    ):
        assert forbidden not in serialized


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
    layout = assemble_layout_representation(
        source_file_id=file_id,
        source_version_id=version_id,
        run_id=str(run["id"]),
        profile=DOCLING_LAYOUT_OCR_V2,
        occurrences=[],
    )
    for kind, media_type, content in (
        ("MARKDOWN", "text/markdown", markdown),
        ("DOCLING_JSON", "application/json", docling_json),
        ("OCR_LAYOUT_JSON", "application/json", layout),
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
    audit = database.execute_one(
        """
        select payload_summary from audit_event
         where event_type = 'file.document.processing.completed'
         order by created_at desc, id desc limit 1
        """
    )
    assert audit is not None
    bounded_audit = json.loads(str(audit["payload_summary"]))
    audit_payload = json.loads(str(bounded_audit["payload"]))
    assert audit_payload["page_count"] == 2
    assert audit_payload["processing_time_ms"] == 1250
    assert audit_payload["representation_sizes"]["MARKDOWN"] == len(markdown)
    assert "Safe text" not in json.dumps(audit_payload)


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
    layout = assemble_layout_representation(
        source_file_id=file_id,
        source_version_id=version_id,
        run_id=str(run["id"]),
        profile=DOCLING_LAYOUT_OCR_V2,
        occurrences=[],
    )
    staged = {}
    for kind, media_type, content in (
        ("MARKDOWN", "text/markdown", markdown),
        ("DOCLING_JSON", "application/json", docling_json),
        ("OCR_LAYOUT_JSON", "application/json", layout),
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
        "OCR_LAYOUT_JSON",
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
    assert len(storage.objects) == 4
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


def test_layout_profile_requires_and_atomically_publishes_all_three_outputs() -> None:
    _database_value, _storage, service, file_id, version_id, _body = _service()
    run = service.request_processing(
        tenant_id="tenant-default",
        source_file_id=file_id,
        source_version_id=version_id,
        actor_id="file-worker",
        correlation_id="layout-output",
        profile_code="docling-layout-ocr-v2",
    )
    with service.repository.database.unit_of_work():
        assert service.repository.claim_due_run(worker_id="layout-worker") is not None
    layout = assemble_layout_representation(
        source_file_id=file_id,
        source_version_id=version_id,
        run_id=str(run["id"]),
        profile=DOCLING_LAYOUT_OCR_V2,
        occurrences=[],
    )
    outputs = (
        ("MARKDOWN", "text/markdown", b"# Parent\n"),
        ("DOCLING_JSON", "application/json", b'{"schema_name":"DoclingDocument"}'),
        ("OCR_LAYOUT_JSON", "application/json", layout),
    )
    for kind, media_type, content in outputs:
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
        processing_time_ms=200,
    )
    assert {item["kind"] for item in representations} == {
        "MARKDOWN",
        "DOCLING_JSON",
        "OCR_LAYOUT_JSON",
    }


def test_layout_finalize_binds_every_occurrence_and_cleans_private_artifacts() -> None:
    database, storage, service, file_id, version_id, _body = _service()
    run = service.request_processing(
        tenant_id="tenant-default",
        source_file_id=file_id,
        source_version_id=version_id,
        actor_id="file-worker",
        correlation_id="layout-cleanup",
        profile_code="docling-layout-ocr-v2",
    )
    with database.unit_of_work():
        assert service.repository.claim_due_run(worker_id="layout-worker") is not None

    parent = b"# Parent\n"
    parent_prepared = service.prepare_parent_artifact_transfer(
        run_id=str(run["id"]),
        expected_size_bytes=len(parent),
        expected_sha256=hashlib.sha256(parent).hexdigest(),
        now=NOW,
    )
    service.upload_parent_artifact(
        transfer_id=str(parent_prepared["transfer_id"]),
        upload_token=str(parent_prepared["upload_token"]),
        stream=io.BytesIO(parent),
        now=NOW,
    )
    docling_json = b'{"schema_name":"DoclingDocument"}'
    docling_prepared = service.prepare_representation_transfer(
        run_id=str(run["id"]),
        kind="DOCLING_JSON",
        expected_size_bytes=len(docling_json),
        expected_sha256=hashlib.sha256(docling_json).hexdigest(),
        now=NOW,
    )
    service.upload_representation(
        transfer_id=str(docling_prepared["transfer_id"]),
        upload_token=str(docling_prepared["upload_token"]),
        stream=io.BytesIO(docling_json),
        media_type="application/json",
        now=NOW,
    )

    raw_picture = io.BytesIO()
    Image.new("RGB", (16, 8), color="white").save(raw_picture, format="PNG")
    picture = normalize_picture_asset(
        raw_picture.getvalue(),
        declared_media_type="image/png",
        profile=DOCLING_LAYOUT_OCR_V2,
    )
    asset_prepared = service.prepare_picture_asset_transfer(
        run_id=str(run["id"]),
        normalized_sha256=picture.content_sha256,
        media_type=picture.media_type,
        original_width_pixels=picture.original_width_pixels,
        original_height_pixels=picture.original_height_pixels,
        width_pixels=picture.width_pixels,
        height_pixels=picture.height_pixels,
        normalization_transform=picture.transform,
        size_bytes=len(picture.content),
        now=NOW,
    )
    service.upload_picture_asset(
        transfer_id=str(asset_prepared["transfer_id"]),
        upload_token=str(asset_prepared["upload_token"]),
        stream=io.BytesIO(picture.content),
        media_type=picture.media_type,
        now=NOW,
    )
    service.register_picture_occurrence(
        run_id=str(run["id"]),
        picture_asset_id=str(asset_prepared["picture_asset_id"]),
        occurrence_index=1,
        source_format="DOCX",
        picture_ref="#/pictures/0",
        parent_ref="#/body",
        parent_label="body",
        parent_ordinal=0,
        slide_no=None,
        parent_bbox=None,
    )
    item = service.register_picture_item(
        run_id=str(run["id"]),
        picture_asset_id=str(asset_prepared["picture_asset_id"]),
        occurrence_count=1,
        ocr_engine_code="docling-rapidocr",
        model_revision="v1.30.0",
        model_digest="sha256:" + "d" * 64,
        correlation_id="layout-cleanup",
    )
    service.complete_parent_parse(
        run_id=str(run["id"]), correlation_id="layout-cleanup"
    )
    service.claim_picture_item(
        picture_item_id=str(item["id"]),
        claim_token="picture-claim",
        claim_expires_at=(NOW + timedelta(minutes=2)).isoformat(),
    )
    picture_result = adapt_docling_picture_result(
        json.dumps(
            {
                "schema_name": "DoclingDocument",
                "pages": {"1": {"size": {"width": 16, "height": 8}}},
                "texts": [],
            }
        ).encode(),
        picture=picture,
        profile=DOCLING_LAYOUT_OCR_V2,
    )
    result_prepared = service.prepare_picture_result_transfer(
        picture_item_id=str(item["id"]),
        expected_size_bytes=len(picture_result),
        expected_sha256=hashlib.sha256(picture_result).hexdigest(),
        now=NOW,
    )
    service.upload_picture_result(
        transfer_id=str(result_prepared["transfer_id"]),
        upload_token=str(result_prepared["upload_token"]),
        stream=io.BytesIO(picture_result),
        now=NOW,
    )
    service.complete_picture_item(
        picture_item_id=str(item["id"]),
        status="NO_TEXT",
        result_size_bytes=len(picture_result),
        result_sha256=hashlib.sha256(picture_result).hexdigest(),
        error_code="",
        correlation_id="layout-cleanup",
    )

    occurrence = service.assembly_context(run_id=str(run["id"]))["occurrences"][0]
    occurrence["result"] = picture_result
    layout = assemble_layout_representation(
        source_file_id=file_id,
        source_version_id=version_id,
        run_id=str(run["id"]),
        profile=DOCLING_LAYOUT_OCR_V2,
        occurrences=[occurrence],
    )
    markdown = append_layout_ocr_markdown(parent, layout)
    for kind, media_type, content in (
        ("MARKDOWN", "text/markdown", markdown),
        ("OCR_LAYOUT_JSON", "application/json", layout),
    ):
        prepared = service.prepare_representation_transfer(
            run_id=str(run["id"]),
            kind=kind,
            expected_size_bytes=len(content),
            expected_sha256=hashlib.sha256(content).hexdigest(),
            now=NOW,
        )
        service.upload_representation(
            transfer_id=str(prepared["transfer_id"]),
            upload_token=str(prepared["upload_token"]),
            stream=io.BytesIO(content),
            media_type=media_type,
            now=NOW,
        )
    representations = service.finalize(
        run_id=str(run["id"]),
        partial=False,
        page_count=1,
        processing_time_ms=200,
    )

    cleanup = database.execute(
        "select * from document_picture_cleanup_fact order by object_kind"
    )
    assert [row["object_kind"] for row in cleanup] == [
        "PARENT_ARTIFACT",
        "PICTURE_ASSET",
        "PICTURE_RESULT",
    ]
    private_keys = {str(row["internal_object_key"]) for row in cleanup}
    assert private_keys <= storage.objects.keys()
    result = service.cleanup_picture_artifacts(now=NOW + timedelta(minutes=1))
    assert result == {"claimed": 3, "deleted": 3, "retried": 0, "dead": 0}
    assert private_keys.isdisjoint(storage.objects)
    assert all(str(row["object_key"]) in storage.objects for row in representations)
    assert service.repository.get_picture_asset(
        str(asset_prepared["picture_asset_id"])
    )["status"] == "CONTENT_UNAVAILABLE"
    assert service.cleanup_picture_artifacts(now=NOW + timedelta(minutes=2))["claimed"] == 0


def test_layout_upload_rejects_omitted_frozen_picture_occurrence() -> None:
    database, _storage, service, file_id, version_id, _body = _service()
    run = service.request_processing(
        tenant_id="tenant-default",
        source_file_id=file_id,
        source_version_id=version_id,
        actor_id="file-worker",
        correlation_id="layout-binding",
        profile_code="docling-layout-ocr-v2",
    )
    with database.unit_of_work():
        assert service.repository.claim_due_run(worker_id="layout-worker") is not None
        asset, _ = service.repository.create_or_get_picture_asset(
            run_id=str(run["id"]),
            normalized_sha256="b" * 64,
            media_type="image/png",
            original_width_pixels=16,
            original_height_pixels=8,
            width_pixels=16,
            height_pixels=8,
            normalization_transform_json=json.dumps(
                {
                    "version": "embedded-media-exif-orientation/v1",
                    "pixel_basis": "RAW_EMBEDDED_MEDIA_AFTER_EXIF",
                    "office_display_transform_applied": False,
                    "source_origin": "TOPLEFT",
                    "target_origin": "TOPLEFT",
                    "exif_orientation": 1,
                    "original_size": [16, 8],
                    "normalized_size": [16, 8],
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            size_bytes=32,
            object_key="private/staging/bound-picture",
        )
        service.repository.create_or_get_picture_occurrence(
            run_id=str(run["id"]),
            picture_asset_id=str(asset["id"]),
            occurrence_index=1,
            source_format="DOCX",
            picture_ref="#/pictures/0",
            parent_ref="#/body",
            parent_label="body",
            parent_ordinal=0,
            slide_no=None,
            parent_bbox_json="",
        )
        service.repository.create_or_get_picture_item(
            run_id=str(run["id"]),
            picture_asset_id=str(asset["id"]),
            occurrence_count=1,
            ocr_engine_code="docling-rapidocr",
            model_revision="v1.30.0",
            model_digest="sha256:" + "d" * 64,
            correlation_id="layout-binding",
        )
    omitted = assemble_layout_representation(
        source_file_id=file_id,
        source_version_id=version_id,
        run_id=str(run["id"]),
        profile=DOCLING_LAYOUT_OCR_V2,
        occurrences=[],
    )
    prepared = service.prepare_representation_transfer(
        run_id=str(run["id"]),
        kind="OCR_LAYOUT_JSON",
        expected_size_bytes=len(omitted),
        expected_sha256=hashlib.sha256(omitted).hexdigest(),
        now=NOW,
    )
    with pytest.raises(NonRetryableExecutionError) as captured:
        service.upload_representation(
            transfer_id=str(prepared["transfer_id"]),
            upload_token=str(prepared["upload_token"]),
            stream=io.BytesIO(omitted),
            media_type="application/json",
            now=NOW,
        )
    assert captured.value.error_code == "document_layout_occurrence_mismatch"


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
    layout = assemble_layout_representation(
        source_file_id=file_id,
        source_version_id=version_id,
        run_id=str(run["id"]),
        profile=DOCLING_LAYOUT_OCR_V2,
        occurrences=[],
    )
    for kind, media_type, content in (
        ("MARKDOWN", "text/markdown", b"safe text"),
        ("DOCLING_JSON", "application/json", b'{"texts": []}'),
        ("OCR_LAYOUT_JSON", "application/json", layout),
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
    audit_count_before = database.execute_one(
        """
        select count(*) as value from audit_event
         where event_type like 'file.document.%'
        """
    )
    service.file_repository.remove_active_workspace_files(
        workspace_id="document-workspace",
        removed_at=NOW.isoformat(),
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
    retained_run = service.repository.get_run(str(run["id"]))
    assert retained_run["processor_build_digest"] == PROCESSOR_DIGEST
    assert retained_run["profile_hash"] == DOCLING_LAYOUT_OCR_V2.profile_hash
    assert {item["content_sha256"] for item in retired} == {
        item["content_sha256"] for item in representations
    }
    assert database.execute_one(
        """
        select count(*) as value from audit_event
         where event_type like 'file.document.%'
        """
    ) == audit_count_before


def test_source_version_cleanup_waits_for_nonterminal_document_processing() -> None:
    _database_value, storage, service, file_id, version_id, _body = _service()
    run = service.request_processing(
        tenant_id="tenant-default",
        source_file_id=file_id,
        source_version_id=version_id,
        actor_id="file-worker",
        correlation_id="retention-boundary",
        profile_code="docling-layout-ocr-v2",
    )
    service.file_repository.remove_active_workspace_files(
        workspace_id="document-workspace",
        removed_at=NOW.isoformat(),
    )
    service.file_repository.enqueue_cleanup(
        resource_type=CleanupResourceType.FILE_VERSION,
        resource_id=version_id,
        reason="SOURCE_RETENTION_EXPIRED",
        due_at=NOW.isoformat(),
    )
    lifecycle = FileLifecycleService(
        service.file_repository,
        storage,
        now=lambda: NOW + timedelta(minutes=1),
    )

    first = lifecycle.run_once()

    assert int(first["cleanup_retried"]) >= 1
    assert service.file_repository.get_version(version_id)["status"] == "AVAILABLE"
    with service.repository.database.unit_of_work():
        assert service.repository.claim_due_run(worker_id="layout-worker") is not None
    service.fail(run_id=str(run["id"]), error_code="document_processing_failed")
    completed = FileLifecycleService(
        service.file_repository,
        storage,
        now=lambda: NOW + timedelta(hours=2),
    ).run_once()
    assert int(completed["cleanup_completed"]) >= 1
    assert service.file_repository.get_version(version_id)["status"] == (
        "CONTENT_UNAVAILABLE"
    )


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
