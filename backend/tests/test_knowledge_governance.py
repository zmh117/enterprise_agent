from app.modules.knowledge.infrastructure.governance_repository import GovernanceStore
from copy import deepcopy
import json
import shutil
import sqlite3
from typing import cast
import uuid

import pytest

from app.modules.audit.application.audit_service import AuditService
from app.modules.job.infrastructure.repositories import AuditRepository
from app.modules.knowledge.domain.governance import KnowledgeGovernanceError
from app.modules.knowledge.application.source_service import SourceBindingService
from app.modules.knowledge.infrastructure.storage import insert, table
from app.modules.knowledge.domain.identity import now
from app.modules.knowledge.domain.vector_contract import fingerprint
from app.modules.permission.application.permission_service import PermissionService
from app.shared.database import Database, assert_external_io_allowed, default_migrations_dir
from app.shared.exceptions import PermissionDenied
from app.shared.migrations import Migrator, load_migration_catalog
from backend.tests.test_knowledge_chunks import import_rows, source_fingerprint
from backend.tests.test_knowledge_import import export_row
from backend.tests.test_knowledge_vectors import prepared as vector_fixture


prepared = vector_fixture


class SyntheticPermission:
    allowed = True

    def require_action(self, **kwargs):
        assert kwargs == {
            "user_id": "synthetic_admin",
            "resource_type": "platform_config",
            "resource_code": "*",
            "action": "manage",
        }
        if not self.allowed:
            raise PermissionDenied("synthetic permission denied")


class SyntheticVerifier:
    instance_code = "synthetic_instance"
    target_hash = "a" * 64

    def __init__(self):
        self.calls = []
        self.callback = lambda: None
        self.result = True

    def verify(self, **kwargs):
        assert_external_io_allowed("synthetic_source_verifier")
        self.calls.append(kwargs)
        self.callback()
        return self.result


@pytest.fixture
def governance(prepared):
    db, vector, snapshot = prepared
    permission = SyntheticPermission()
    verifier = SyntheticVerifier()
    service = SourceBindingService(
        GovernanceStore(db),
        cast(PermissionService, permission),
        AuditService(AuditRepository(db)),
        verifier,
    )
    source_id = db.execute_one('select id from "knowledge.source"')["id"]
    return db, vector, snapshot, service, permission, verifier, source_id


def create(governance, **overrides):
    _, _, _, service, _, _, source_id = governance
    return service.create(
        **dict(
            {
                "actor_id": "synthetic_admin",
                "source_id": source_id,
                "instance_code": "synthetic_instance",
                "team_id": "synthetic_team",
                "expected_revision": 0,
                "batch_attested": True,
                "attestation_hash": "b" * 64,
            },
            **overrides,
        )
    )


def test_forward_migration_is_empty_replayable_and_does_not_modify_old_tables(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    shutil.copyfile(
        default_migrations_dir() / "legacy-v1-manifest.json", migrations / "legacy-v1-manifest.json"
    )
    for definition in load_migration_catalog(default_migrations_dir()):
        if definition.version <= "136":
            shutil.copyfile(
                default_migrations_dir() / definition.name, migrations / definition.name
            )
    db = Database("sqlite:///:memory:")
    try:
        assert (
            Migrator(db, migrations, migrator_build="knowledge-governance-before").run().head
            == "136"
        )
        import_rows(db, tmp_path, [export_row()])
        db.execute_script(
            (default_migrations_dir().parent / "seeds" / "local_seed.sql").read_text()
        )
        publication_tables = (
            "agent_publication_mcp_tool",
            "business_application_revision_mcp_tool",
            "business_application_publication_mcp_tool",
        )
        publications_before = {
            name: db.execute(f"select * from {name} order by 1,2,3") for name in publication_tables
        }
        before = source_fingerprint(db)
        result = Migrator(
            db, default_migrations_dir(), migrator_build="knowledge-governance-after"
        ).run()
        assert result.applied == ("137",)
        assert source_fingerprint(db) == before
        assert {
            name: db.execute(f"select * from {name} order by 1,2,3") for name in publication_tables
        } == publications_before
        db.execute(
            "insert into agent_publication_mcp_tool(agent_publication_id,server_code,tool_identifier,schema_hash,selection_order,created_at) "
            "values ('agent_publication_default_v1','knowledge-mcp','synthetic_knowledge',?,1000,?)",
            ("a" * 64, now()),
        )
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "insert into agent_publication_mcp_tool(agent_publication_id,server_code,tool_identifier,schema_hash,selection_order,created_at) "
                "values ('agent_publication_default_v1','arbitrary-mcp','synthetic_arbitrary',?,1001,?)",
                ("a" * 64, now()),
            )
        for name in (
            "source_binding",
            "retrieval_resource",
            "retrieval_revision",
            "retrieval_verification",
        ):
            assert db.execute(f"select * from {table(db, name)}") == []
        assert (
            not Migrator(db, default_migrations_dir(), migrator_build="knowledge-governance-replay")
            .run()
            .applied
        )
        assert db.execute("pragma foreign_key_check") == []
    finally:
        db.close()


def test_binding_lifecycle_does_not_change_sources_chunks_vectors_or_import_replay(
    governance, tmp_path
):
    db, vector, snapshot, service, _, verifier, _ = governance
    vector.build("synthetic-v1", snapshot)
    before = source_fingerprint(db)
    points = deepcopy(vector.qdrant.points)
    chunk_rows = db.execute('select * from "knowledge.document_chunk" order by id')
    pending = create(governance)
    assert pending["state"] == "PENDING" and pending["verification_hash"] is None
    assert verifier.calls == []
    verified = service.verify(
        actor_id="synthetic_admin", job_id="synthetic_job", binding_id=pending["id"]
    )
    assert verified["state"] == "VERIFIED" and verified["checked_count"] == 2
    assert len(verifier.calls) == 1 and verifier.calls[0]["team_id"] == "synthetic_team"
    assert {item.project_id for item in verifier.calls[0]["items"]} == {"project_id"}
    assert source_fingerprint(db) == before
    assert import_rows(db, tmp_path, [export_row(), export_row(2)])["replayed"]
    replay = vector.build("synthetic-v1", snapshot)
    assert replay["encoded"] == 0 and replay["reused"] == snapshot["expected_chunk_count"]
    assert vector.qdrant.points == points
    assert db.execute('select * from "knowledge.document_chunk" order by id') == chunk_rows
    service.revoke(actor_id="synthetic_admin", binding_id=pending["id"])
    service.revoke(actor_id="synthetic_admin", binding_id=pending["id"])
    assert source_fingerprint(db) == before
    assert db.execute("pragma foreign_key_check") == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"batch_attested": False},
        {"batch_attested": 1},
        {"expected_revision": True},
        {"expected_revision": -1},
        {"instance_code": "unknown"},
        {"team_id": "显示名称"},
        {"team_id": "https://example.invalid"},
        {"attestation_hash": "not a digest"},
        {"attestation_hash": "A" * 64},
    ],
)
def test_binding_input_is_strict_and_never_calls_provider(governance, overrides):
    db, _, _, _, _, verifier, _ = governance
    with pytest.raises(KnowledgeGovernanceError, match="knowledge_input_invalid"):
        create(governance, **overrides)
    assert not db.execute('select * from "knowledge.source_binding"') and not verifier.calls


def test_unauthorized_and_unconfigured_verifier_fail_closed(governance):
    db, _, _, service, permission, verifier, _ = governance
    permission.allowed = False
    with pytest.raises(PermissionDenied):
        create(governance)
    permission.allowed = True
    service.verifier = None
    with pytest.raises(KnowledgeGovernanceError, match="knowledge_verifier_unavailable"):
        create(governance)
    assert not db.execute('select * from "knowledge.source_binding"') and not verifier.calls


def test_technical_sample_is_bounded_and_not_the_batch_attestation(governance, tmp_path):
    db, _, _, service, _, verifier, _ = governance
    import_rows(db, tmp_path, [export_row(i) for i in range(1, 22)])
    binding = create(governance)
    verified = service.verify(
        actor_id="synthetic_admin", job_id="synthetic_job", binding_id=binding["id"]
    )
    assert verified["document_count"] == 21 and verified["checked_count"] == 20
    assert len(verifier.calls[0]["items"]) == 20
    assert verified["attestation_hash"] == "b" * 64
    assert verified["corpus_hash"] != verified["verification_hash"]


def test_source_without_current_revision_cannot_be_silently_omitted(governance):
    db, _, _, _, _, verifier, _ = governance
    doc = db.execute_one('select id from "knowledge.document" order by id')
    db.execute('update "knowledge.document" set current_revision_id=null where id=?', (doc["id"],))
    with pytest.raises(KnowledgeGovernanceError, match="knowledge_source_unavailable"):
        create(governance)
    assert not db.execute('select * from "knowledge.source_binding"') and not verifier.calls


def test_new_binding_revokes_old_and_stale_management_write_does_not_change_it(governance):
    db, _, _, service, _, _, _ = governance
    first = create(governance)
    service.verify(actor_id="synthetic_admin", job_id="synthetic_job", binding_id=first["id"])
    second = create(governance, expected_revision=1, team_id="new_team")
    assert (
        second["state"] == "PENDING"
        and second["revision"] == 2
        and second["verification_hash"] is None
    )
    with pytest.raises(KnowledgeGovernanceError, match="knowledge_revision_conflict"):
        create(governance, expected_revision=1)
    stored = db.execute('select * from "knowledge.source_binding" order by revision')
    assert [row["state"] for row in stored] == ["REVOKED", "PENDING"]
    assert stored[0]["verification_hash"] is not None


@pytest.mark.parametrize("change", ["revoke", "replace", "source", "target", "permission"])
def test_recheck_after_external_io_rejects_changes(governance, change):
    db, _, _, service, permission, verifier, _ = governance
    binding = create(governance)

    def mutate():
        if change == "revoke":
            service.revoke(actor_id="synthetic_admin", binding_id=binding["id"])
        elif change == "replace":
            create(governance, expected_revision=1)
        elif change == "source":
            db.execute(
                'update "knowledge.document_revision" set source_project_id=?', ("other_project",)
            )
        elif change == "target":
            verifier.target_hash = "c" * 64
        else:
            permission.allowed = False

    verifier.callback = mutate
    with pytest.raises((KnowledgeGovernanceError, PermissionDenied)):
        service.verify(actor_id="synthetic_admin", job_id="synthetic_job", binding_id=binding["id"])
    stored = service.store.get("source_binding", binding["id"])
    assert stored["state"] != "VERIFIED" and stored["verification_hash"] is None


@pytest.mark.parametrize("provider_result", [False, "true", "exception"])
def test_provider_failure_is_safe_and_audited(governance, provider_result):
    db, _, _, service, _, verifier, _ = governance
    binding = create(governance)
    verifier.result = provider_result
    if provider_result == "exception":

        def fail():
            raise RuntimeError("synthetic-hidden-provider-body")

        verifier.callback = fail
    with pytest.raises(KnowledgeGovernanceError, match="^knowledge_verification_failed$"):
        service.verify(actor_id="synthetic_admin", job_id="synthetic_job", binding_id=binding["id"])
    audits = db.execute("select * from audit_event where event_type like 'knowledge.%'")
    serialized = json.dumps(audits, default=str)
    assert "synthetic-hidden-provider-body" not in serialized
    assert "project_id" not in serialized and "synthetic_item" not in serialized
    assert "knowledge_verification_failed" in serialized
    assert service.store.get("source_binding", binding["id"])["state"] == "PENDING"


def test_binding_database_constraints(governance):
    db, _, _, service, _, _, _ = governance
    binding = create(governance)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "update \"knowledge.source_binding\" set state='VERIFIED' where id=?", (binding["id"],)
        )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "update \"knowledge.source_binding\" set state='REVOKED' where id=?", (binding["id"],)
        )
    with pytest.raises(sqlite3.IntegrityError):
        insert(db, "source_binding", {**binding, "id": str(uuid.uuid4())})
    service.verify(actor_id="synthetic_admin", job_id="synthetic_job", binding_id=binding["id"])
    verified = service.store.get("source_binding", binding["id"])
    with pytest.raises(sqlite3.IntegrityError):
        insert(db, "source_binding", {**verified, "id": str(uuid.uuid4()), "revision": 2})


def test_resource_defaults_uniqueness_and_revision_pointer_ownership(governance):
    db, vector, snapshot, _, _, _, _ = governance
    vector.build("synthetic-v1", snapshot)
    index = vector.repository.get("synthetic-v1")
    binding = create(governance)
    resource = {
        "id": str(uuid.uuid4()),
        "knowledge_base_id": snapshot["knowledge_base_id"],
        "code": "synthetic_resource",
        "name": "合成管理名称",
        "created_by": "synthetic_admin",
        "created_at": now(),
        "updated_at": now(),
    }
    insert(db, "retrieval_resource", resource)
    stored = db.execute_one('select * from "knowledge.retrieval_resource"')
    assert stored["draft_revision_id"] is stored["published_revision_id"] is None
    duplicate = {**resource, "id": str(uuid.uuid4()), "code": "synthetic_other"}
    with pytest.raises(sqlite3.IntegrityError):
        insert(db, "retrieval_resource", duplicate)
    insert(db, "retrieval_resource", {**duplicate, "status": "disabled"})
    revision = {
        "id": str(uuid.uuid4()),
        "resource_id": resource["id"],
        "revision": 1,
        "binding_id": binding["id"],
        "index_id": index["id"],
        "profile_hash": index["profile_hash"],
        "corpus_hash": index["corpus_hash"],
        "config_hash": fingerprint("synthetic_config"),
        "created_by": "synthetic_admin",
        "created_at": now(),
    }
    insert(db, "retrieval_revision", revision)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            'update "knowledge.retrieval_resource" set published_revision_id=? where id=?',
            (revision["id"], duplicate["id"]),
        )
    verification = {
        "id": str(uuid.uuid4()),
        "resource_id": resource["id"],
        "revision_id": revision["id"],
        "resource_revision": 1,
        "config_hash": revision["config_hash"],
        "status": "VERIFIED",
        "evidence_hash": "c" * 64,
        "created_by": "synthetic_admin",
        "created_at": now(),
    }
    insert(db, "retrieval_verification", verification)
    with pytest.raises(sqlite3.IntegrityError):
        insert(
            db,
            "retrieval_verification",
            {**verification, "id": str(uuid.uuid4()), "resource_id": duplicate["id"]},
        )
    with pytest.raises(sqlite3.IntegrityError):
        insert(
            db,
            "retrieval_verification",
            {**verification, "id": str(uuid.uuid4()), "error_code": "bad"},
        )
    assert db.execute("pragma foreign_key_check") == []
