from __future__ import annotations

import shutil

from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import Migrator, load_migration_catalog


TIMESTAMP = "2026-08-25T00:00:00+00:00"


def test_concurrency_migration_is_additive_and_seeds_exactly_two_slots(tmp_path) -> None:
    source = default_migrations_dir()
    staged = tmp_path / "migrations"
    staged.mkdir()
    shutil.copy2(source / "legacy-v1-manifest.json", staged)
    catalog = load_migration_catalog(source)
    for artifact in catalog:
        if artifact.version <= "120":
            shutil.copy2(artifact.path, staged / artifact.path.name)

    database = Database("sqlite:///:memory:")
    first = Migrator(database, staged, migrator_build="concurrency-before").run()
    assert first.head == "120"
    database.execute(
        """
        insert into managed_file
          (id, tenant_id, owner_type, owner_user_id, display_name, format_code,
           created_by, created_at, updated_at)
        values ('file-before-121', 'tenant-a', 'PRIVATE_USER', 'user-a',
                'before.pdf', 'PDF', 'user-a', ?, ?)
        """,
        (TIMESTAMP, TIMESTAMP),
    )
    database.execute(
        """
        insert into managed_file_version
          (id, file_id, version_number, version_kind, media_type, encoding,
           size_bytes, format_code, content_sha256, object_key, source_kind,
           created_by, created_at)
        values ('version-before-121', 'file-before-121', 1, 'ATTACHMENT',
                'application/pdf', '', 128, 'PDF', ?, 'managed/source.pdf',
                'MESSAGE_ATTACHMENT', 'user-a', ?)
        """,
        ("a" * 64, TIMESTAMP),
    )
    database.execute(
        """
        insert into file_processing_run
          (id, tenant_id, source_file_id, source_version_id, processor_code,
           processor_version, processor_build_digest, profile_code, profile_hash,
           status, source_size_bytes, required_output_kinds_json, assembly_status,
           completed_at, created_by, created_at, updated_at)
        values ('run-before-121', 'tenant-a', 'file-before-121', 'version-before-121',
                'docling-serve', '1.30.0', ?, 'docling-layout-ocr-v2', ?, 'FAILED',
                128, '["MARKDOWN","DOCLING_JSON","OCR_LAYOUT_JSON"]', 'FAILED', ?,
                'file-worker', ?, ?)
        """,
        ("sha256:" + "b" * 64, "c" * 64, TIMESTAMP, TIMESTAMP, TIMESTAMP),
    )

    shutil.copy2(source / "121_expand_docling_processing_concurrency.sql", staged)
    second = Migrator(database, staged, migrator_build="concurrency-after").run()

    assert second.head == "121"
    assert database.execute_one(
        "select id, profile_hash, status from file_processing_run where id = ?",
        ("run-before-121",),
    ) == {"id": "run-before-121", "profile_hash": "c" * 64, "status": "FAILED"}
    assert database.execute(
        "select slot_no, state, owner_id from document_processing_docling_slot order by slot_no"
    ) == [
        {"slot_no": 1, "state": "AVAILABLE", "owner_id": ""},
        {"slot_no": 2, "state": "AVAILABLE", "owner_id": ""},
    ]
    assert database.execute_one(
        "select count(*) as count from file_processing_worker_heartbeat"
    ) == {"count": 0}

    migration_sql = (source / "121_expand_docling_processing_concurrency.sql").read_text(
        encoding="utf-8"
    ).lower()
    for protected_table in (
        "business_application_revision",
        "business_application_publication",
        "agent_job",
        "file_processing_run",
        "file_representation",
    ):
        assert f"update {protected_table}" not in migration_sql
        assert f"delete from {protected_table}" not in migration_sql
    database.close()
