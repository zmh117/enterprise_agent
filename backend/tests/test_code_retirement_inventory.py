"""Retirement inventories must identify ownership without reading source/credential payloads."""

import json
import pytest

from app.modules.knowledge.infrastructure.code_retirement_inventory import CodeRetirementInventory
from app.modules.knowledge.infrastructure.storage import insert
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import Migrator
from app.modules.knowledge.infrastructure.code_retirement import CodeRetirement
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError


def test_inventory_is_read_only_deterministic_and_excludes_payloads(tmp_path):
    migrations = tmp_path / "legacy-migrations"
    migrations.mkdir()
    for path in default_migrations_dir().glob("*.sql"):
        if path.name[:3].isdigit() and int(path.name[:3]) <= 159:
            (migrations / path.name).write_bytes(path.read_bytes())
    manifest = default_migrations_dir() / "legacy-v1-manifest.json"
    (migrations / manifest.name).write_bytes(manifest.read_bytes())
    db = Database("sqlite:///:memory:")
    try:
        Migrator(db, migrations, migrator_build="inventory-test").run()
        stamp = "2026-11-09T00:00:00+00:00"
        private_fixture = "synthetic-value-that-must-not-appear-in-inventory"
        for source in ("code-source", "ones-source"):
            insert(
                db,
                "source",
                dict(
                    id=source,
                    code=source,
                    display_name=private_fixture,
                    source_system="svn" if source == "code-source" else "ones",
                    origin_state="verified",
                    identity_metadata={"private": private_fixture},
                    created_at=stamp,
                ),
            )
        insert(
            db,
            "knowledge_base",
            dict(
                id="code-kb",
                code="code-kb",
                display_name="Code",
                description="",
                state="storage_only",
                created_at=stamp,
            ),
        )
        insert(
            db,
            "code_binding",
            dict(
                source_id="code-source",
                knowledge_base_id="code-kb",
                config_revision=1,
                config_hash="a" * 64,
                config_json={"private": private_fixture},
                created_at=stamp,
                updated_at=stamp,
            ),
        )
        for source, kind in (("code-source", "rule"), ("ones-source", "article")):
            insert(
                db,
                "document",
                dict(
                    id=source,
                    source_id=source,
                    source_object_type=kind,
                    external_id=source,
                    external_number=source,
                    document_kind=kind,
                    lifecycle_state="pending",
                    created_at=stamp,
                    last_seen_at=stamp,
                ),
            )
        first = CodeRetirementInventory(db).inspect()
        second = CodeRetirementInventory(db).inspect()
        assert first == second
        assert private_fixture not in json.dumps(first)
        manifest = first["manifest"]
        assert manifest["schema_head"] == "159"
        assert manifest["legacy_table_counts"]["code_binding"] == 1
        assert len(manifest["legacy_table_counts"]) == 20
        assert [row["id"] for row in manifest["objects"]["documents"]] == ["code-source"]
        assert manifest["retained_other_source_document_count"] == 1
        assert set(manifest["scope_conflicts"].values()) == {0}
        with pytest.raises(CodeKnowledgeError, match="CODE_RETIREMENT_INVENTORY_CHANGED"):
            CodeRetirement(db).retire("0" * 64)
        assert CodeRetirementInventory(db).inspect() == first
        retired = CodeRetirement(db).retire(first["digest"])
        assert retired["retired_documents"] == 1
        assert retired["retained_other_documents"] == 1
        assert db.execute_one('SELECT id FROM "knowledge.document"')["id"] == "ones-source"
        assert db.execute("PRAGMA foreign_key_check") == []
        Migrator(db, default_migrations_dir(), migrator_build="retirement-test").run()
        assert db.execute_one('SELECT kind FROM "knowledge.knowledge_base"')["kind"] == "code"
        assert db.execute("PRAGMA foreign_key_check") == []
    finally:
        db.close()
