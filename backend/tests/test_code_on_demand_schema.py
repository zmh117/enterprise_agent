"""Migration 160 retires only prepared legacy structures and preserves shared content."""

from pathlib import Path
import sqlite3

import pytest

from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import MigrationExecutionError, Migrator


NEW_TABLES = {
    "code_repository",
    "code_resource_config",
    "code_checkout",
    "code_svn_operation",
    "code_analysis",
    "code_evidence",
    "code_answer",
    "code_answer_revision",
    "code_qa_record",
    "code_index_task",
}


def legacy_catalog(tmp_path: Path) -> Path:
    root = tmp_path / "legacy"
    root.mkdir()
    for path in default_migrations_dir().iterdir():
        if path.suffix == ".json" or (path.suffix == ".sql" and path.name[:3] <= "159"):
            (root / path.name).write_bytes(path.read_bytes())
    return root


def seed_shared_content(db: Database) -> None:
    db.execute(
        'INSERT INTO "knowledge.source" VALUES (?,?,?,?,?,?,?)',
        ("ones", "ones", "Fixture", "ones", "verified", "{}", "2026-11-09"),
    )
    db.execute(
        'INSERT INTO "knowledge.knowledge_base" VALUES (?,?,?,?,?,?)',
        ("ones-kb", "ones-kb", "Fixture", "", "storage_only", "2026-11-09"),
    )
    db.execute(
        'INSERT INTO "knowledge.document" (id,source_id,source_object_type,external_id,external_number,document_kind,lifecycle_state,created_at,last_seen_at) VALUES (?,?,?,?,?,?,?,?,?)',
        (
            "ones-document",
            "ones",
            "article",
            "one",
            "one",
            "article",
            "pending",
            "2026-11-09",
            "2026-11-09",
        ),
    )


def test_clean_upgrade_replaces_legacy_code_tables_and_preserves_ones(tmp_path):
    db = Database("sqlite:///:memory:")
    try:
        Migrator(db, legacy_catalog(tmp_path), migrator_build="schema-test").run()
        seed_shared_content(db)
        Migrator(db, default_migrations_dir(), migrator_build="schema-test").run()
        tables = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name GLOB 'knowledge.code_*'"
        )
        assert {r["name"].removeprefix("knowledge.") for r in tables} == NEW_TABLES
        assert db.execute_one('SELECT id FROM "knowledge.document"')["id"] == "ones-document"
        assert db.execute_one('SELECT kind FROM "knowledge.knowledge_base"')["kind"] == "ones"
        assert db.execute("PRAGMA foreign_key_check") == []
        revision_columns = {
            r["name"]: r for r in db.execute('PRAGMA table_info("knowledge.document_revision")')
        }
        assert revision_columns["import_run_id"]["notnull"] == 0
        assert "code_analysis_id" in revision_columns
    finally:
        db.close()


def test_migration_refuses_unretired_code_without_deleting_any_data(tmp_path):
    db = Database("sqlite:///:memory:")
    try:
        Migrator(db, legacy_catalog(tmp_path), migrator_build="schema-test").run()
        seed_shared_content(db)
        db.execute(
            'INSERT INTO "knowledge.code_binding" (source_id,knowledge_base_id,config_revision,config_hash,config_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?)',
            ("ones", "ones-kb", 1, "0" * 64, "{}", "2026-11-09", "2026-11-09"),
        )
        with pytest.raises(MigrationExecutionError, match="160"):
            Migrator(db, default_migrations_dir(), migrator_build="schema-test").run()
        assert db.execute_one('SELECT count(*) AS n FROM "knowledge.code_binding"')["n"] == 1
        assert db.execute_one('SELECT count(*) AS n FROM "knowledge.document"')["n"] == 1
        assert db.execute_one("SELECT max(version) AS head FROM schema_migration")["head"] == "159"
        assert db.execute("PRAGMA foreign_key_check") == []
    finally:
        db.close()


def test_new_structure_rejects_cross_source_checkout_binding(tmp_path):
    from backend.tests.support.runtime import container
    from backend.tests.support.code_answers import code_configuration

    runtime = container()
    try:
        store, _, checkout, _ = code_configuration(runtime, tmp_path)
        other = store.register_repository(
            "00000000-0000-0000-0000-000000000002", "trunk", "https://svn.invalid/other"
        )
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            runtime.database.execute(
                f"UPDATE {store.t('code_resource_config')} SET source_id=? WHERE revision_id=?",
                (other, "code-config"),
            )
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            runtime.database.execute(
                f"UPDATE {store.t('code_checkout')} SET verified_revision=NULL WHERE id=?",
                (checkout["id"],),
            )
        assert runtime.database.execute("PRAGMA foreign_key_check") == []
    finally:
        runtime.database.close()
