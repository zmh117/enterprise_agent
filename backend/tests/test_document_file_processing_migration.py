from __future__ import annotations

import sqlite3

import pytest

from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import Migrator


TIMESTAMP = "2026-08-17T00:00:00+00:00"


def _migrated_database() -> Database:
    database = Database("sqlite:///:memory:")
    result = Migrator(
        database,
        default_migrations_dir(),
        migrator_build="document-file-processing-schema-test",
    ).run()
    assert result.head == "123"
    return database


def _insert_source_file(database: Database) -> None:
    database.execute(
        """
        insert into managed_file
          (id, tenant_id, owner_type, owner_user_id, display_name, format_code,
           created_by, created_at, updated_at)
        values ('file-source', 'tenant-a', 'PRIVATE_USER', 'user-a',
                'evidence.pdf', 'PDF', 'user-a', ?, ?)
        """,
        (TIMESTAMP, TIMESTAMP),
    )
    database.execute(
        """
        insert into managed_file_version
          (id, file_id, version_number, version_kind, media_type, encoding,
           size_bytes, format_code, content_sha256, object_key, source_kind,
           created_by, created_at)
        values ('version-source-1', 'file-source', 1, 'ATTACHMENT',
                'application/pdf', '', 1024, 'PDF', ?,
                'objects/version-source-1', 'MESSAGE_ATTACHMENT', 'user-a', ?)
        """,
        ("a" * 64, TIMESTAMP),
    )


def _insert_processing_run(
    database: Database,
    *,
    run_id: str = "run-a",
    profile_code: str = "docling-layout-ocr-v2",
) -> None:
    database.execute(
        """
        insert into file_processing_run
          (id, tenant_id, source_file_id, source_version_id, processor_code,
           processor_version, processor_build_digest, profile_code, profile_hash,
           status, attempt, source_size_bytes, created_by, created_at, updated_at)
        values (?, 'tenant-a', 'file-source', 'version-source-1', 'docling-serve',
                '1.30.0', ?, ?, ?, 'QUEUED', 0, 1024,
                'file-worker', ?, ?)
        """,
        (
            run_id,
            "sha256:" + "b" * 64,
            profile_code,
            "c" * 64,
            TIMESTAMP,
            TIMESTAMP,
        ),
    )


def test_document_processing_expand_schema_and_defaults() -> None:
    database = _migrated_database()
    tables = {
        str(row["name"])
        for row in database.execute("select name from sqlite_master where type = 'table'")
    }
    assert {
        "file_processing_run",
        "file_representation",
        "file_representation_transfer",
        "document_parent_artifact_transfer",
        "document_picture_asset",
        "document_picture_asset_transfer",
        "document_picture_occurrence",
        "document_picture_processing_item",
        "document_picture_processing_attempt",
        "document_picture_result_transfer",
        "document_processing_stage_outbox",
        "document_picture_cleanup_fact",
    } <= tables

    run_columns = {
        str(row["name"]) for row in database.execute("pragma table_info(file_processing_run)")
    }
    assert {
        "stage_code",
        "required_output_kinds_json",
        "run_deadline_at",
        "assembly_status",
        "assembly_attempt",
        "assembly_claim_token",
        "assembly_claimed_at",
    } <= run_columns

    revision_columns = {
        str(row["name"])
        for row in database.execute("pragma table_info(business_application_revision)")
    }
    publication_columns = {
        str(row["name"])
        for row in database.execute("pragma table_info(business_application_publication)")
    }
    attachment_columns = {
        str(row["name"]) for row in database.execute("pragma table_info(message_attachment)")
    }
    snapshot_item_columns = {
        str(row["name"])
        for row in database.execute("pragma table_info(agent_job_file_snapshot_item)")
    }
    assert "document_processing_profile_code" in revision_columns
    assert {
        "document_processing_profile_code",
        "document_processing_profile_version",
        "document_processing_profile_hash",
    } <= publication_columns
    assert {
        "readability_status",
        "file_processing_run_id",
        "readability_error_code",
        "readability_updated_at",
    } <= attachment_columns
    assert {
        "representation_id",
        "representation_kind",
        "representation_size_bytes",
        "representation_sha256",
        "representation_format_code",
        "representation_created_at",
    } <= snapshot_item_columns

    snapshot_sql = database.execute_one(
        "select sql from sqlite_master where type = 'table' and name = 'agent_job_file_snapshot'"
    )
    assert snapshot_sql is not None
    assert "schema_version = 5" in str(snapshot_sql["sql"])

    revision_info = {
        str(row["name"]): row
        for row in database.execute("pragma table_info(business_application_revision)")
    }
    publication_info = {
        str(row["name"]): row
        for row in database.execute("pragma table_info(business_application_publication)")
    }
    attachment_info = {
        str(row["name"]): row for row in database.execute("pragma table_info(message_attachment)")
    }
    assert str(revision_info["document_processing_profile_code"]["dflt_value"]) == "'NONE'"
    assert str(publication_info["document_processing_profile_code"]["dflt_value"]) == "'NONE'"
    assert str(attachment_info["readability_status"]["dflt_value"]) == "'NOT_REQUIRED'"


def test_processing_run_and_representation_constraints_are_source_bound() -> None:
    database = _migrated_database()
    _insert_source_file(database)
    _insert_processing_run(database)

    with pytest.raises(sqlite3.IntegrityError):
        _insert_processing_run(database, run_id="run-duplicate")

    database.execute(
        """
        insert into file_representation
          (id, processing_run_id, tenant_id, source_file_id, source_version_id,
           kind, media_type, encoding, status, size_bytes, content_sha256,
           object_key, profile_hash, created_at)
        values ('representation-md', 'run-a', 'tenant-a', 'file-source',
                'version-source-1', 'MARKDOWN', 'text/markdown', 'utf-8',
                'AVAILABLE', 128, ?, 'representations/run-a/markdown', ?, ?)
        """,
        ("d" * 64, "c" * 64, TIMESTAMP),
    )
    with pytest.raises(sqlite3.IntegrityError):
        database.execute(
            """
            insert into file_representation
              (id, processing_run_id, tenant_id, source_file_id, source_version_id,
               kind, media_type, encoding, status, size_bytes, content_sha256,
               object_key, profile_hash, created_at)
            values ('representation-md-duplicate', 'run-a', 'tenant-a', 'file-source',
                    'version-source-1', 'MARKDOWN', 'text/markdown', 'utf-8',
                    'AVAILABLE', 128, ?, 'representations/run-a/markdown-2', ?, ?)
            """,
            ("d" * 64, "c" * 64, TIMESTAMP),
        )

    with pytest.raises(sqlite3.IntegrityError):
        database.execute("update file_processing_run set status = 'UNKNOWN' where id = 'run-a'")
    with pytest.raises(sqlite3.IntegrityError):
        database.execute(
            "update file_representation set kind = 'SOURCE' where id = 'representation-md'"
        )

    database.execute(
        """
        insert into file_representation
          (id, processing_run_id, tenant_id, source_file_id, source_version_id,
           kind, media_type, encoding, status, size_bytes, content_sha256,
           object_key, profile_hash, created_at)
        values ('representation-layout', 'run-a', 'tenant-a', 'file-source',
                'version-source-1', 'OCR_LAYOUT_JSON', 'application/json', 'utf-8',
                'AVAILABLE', 128, ?, 'representations/run-a/layout', ?, ?)
        """,
        ("e" * 64, "c" * 64, TIMESTAMP),
    )


def test_current_layout_ocr_picture_facts_are_run_bound_and_unique() -> None:
    database = _migrated_database()
    _insert_source_file(database)
    _insert_processing_run(database, profile_code="docling-layout-ocr-v2")
    database.execute(
        """
        insert into document_picture_asset
          (id, processing_run_id, tenant_id, source_file_id, source_version_id,
           profile_code, profile_hash, normalized_sha256, media_type,
           original_width_pixels, original_height_pixels, width_pixels,
           height_pixels, normalization_transform_json, size_bytes, object_key, status,
           created_at, updated_at)
        values ('asset-a', 'run-a', 'tenant-a', 'file-source', 'version-source-1',
                'docling-layout-ocr-v2', ?, ?, 'image/png', 32, 24, 32, 24,
                '{"version":"exif-orientation/v1"}', 256,
                'private/pictures/asset-a', 'AVAILABLE', ?, ?)
        """,
        ("c" * 64, "f" * 64, TIMESTAMP, TIMESTAMP),
    )
    database.execute(
        """
        insert into document_picture_occurrence
          (id, processing_run_id, picture_asset_id, occurrence_index,
           source_format, picture_ref, parent_ref, parent_label, parent_ordinal,
           created_at)
        values ('occurrence-a', 'run-a', 'asset-a', 1, 'DOCX', '#/pictures/0',
                '#/body', 'body', 0, ?)
        """,
        (TIMESTAMP,),
    )
    database.execute(
        """
        insert into document_picture_processing_item
          (id, processing_run_id, picture_asset_id, status, occurrence_count,
           attempt, ocr_engine_code, model_revision, model_digest,
           created_at, updated_at)
        values ('item-a', 'run-a', 'asset-a', 'QUEUED', 1, 0,
                'docling-easyocr', 'docling-serve-v1.40.0', ?, ?, ?)
        """,
        ("sha256:" + "a" * 64, TIMESTAMP, TIMESTAMP),
    )
    with pytest.raises(sqlite3.IntegrityError):
        database.execute(
            """
            insert into document_picture_processing_item
              (id, processing_run_id, picture_asset_id, status, occurrence_count,
               attempt, ocr_engine_code, model_revision, model_digest,
               created_at, updated_at)
            values ('item-b', 'run-a', 'asset-a', 'QUEUED', 1, 0,
                    'docling-easyocr', 'docling-serve-v1.40.0', ?, ?, ?)
            """,
            ("sha256:" + "a" * 64, TIMESTAMP, TIMESTAMP),
        )


def test_layout_ocr_v2_profile_constraints_accept_v2_and_reject_unknown_codes() -> None:
    database = _migrated_database()
    _insert_source_file(database)
    _insert_processing_run(database, profile_code="docling-layout-ocr-v2")
    database.execute(
        """
        insert into document_picture_asset
          (id, processing_run_id, tenant_id, source_file_id, source_version_id,
           profile_code, profile_hash, normalized_sha256, media_type,
           original_width_pixels, original_height_pixels, width_pixels,
           height_pixels, normalization_transform_json, size_bytes, object_key, status,
           created_at, updated_at)
        values ('asset-v2', 'run-a', 'tenant-a', 'file-source', 'version-source-1',
                'docling-layout-ocr-v2', ?, ?, 'image/png', 32, 24, 32, 24,
                '{"version":"exif-orientation/v1"}', 256,
                'private/pictures/asset-v2', 'AVAILABLE', ?, ?)
        """,
        ("c" * 64, "f" * 64, TIMESTAMP, TIMESTAMP),
    )

    with pytest.raises(sqlite3.IntegrityError):
        database.execute(
            "update file_processing_run set profile_code = 'docling-layout-ocr-v3' where id = 'run-a'"
        )
    with pytest.raises(sqlite3.IntegrityError):
        database.execute(
            "update document_picture_asset set profile_code = 'docling-layout-ocr-v3' where id = 'asset-v2'"
        )


def test_processing_schema_has_retry_lookup_and_cleanup_indexes() -> None:
    database = _migrated_database()
    indexes = {
        str(row["name"])
        for row in database.execute("select name from sqlite_master where type = 'index'")
    }
    assert {
        "uq_file_processing_run_build_profile",
        "idx_file_processing_run_retry_due",
        "idx_file_processing_run_tenant_status",
        "uq_file_representation_run_kind",
        "idx_file_representation_source",
        "idx_file_representation_cleanup",
        "idx_file_representation_transfer_expiry",
        "idx_message_attachment_readability",
        "idx_file_processing_run_layout_stage",
        "idx_document_parent_artifact_transfer_expiry",
        "idx_document_picture_asset_cleanup",
        "idx_document_picture_occurrence_asset",
        "idx_document_picture_item_claim",
        "idx_document_processing_stage_outbox_claim",
        "idx_document_picture_cleanup_claim",
    } <= indexes
