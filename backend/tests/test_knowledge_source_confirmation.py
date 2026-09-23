"""来源配置简化：只用合成数据，来源声明不冒充 ONES 技术验证。"""

import json
import shutil
import sqlite3
from types import SimpleNamespace

import pytest

from app.cli import confirm_knowledge_source as cli
from app.modules.knowledge.application.resource_service import KnowledgeResourceService
from app.modules.knowledge.domain.governance import KnowledgeGovernanceError
from app.modules.knowledge.infrastructure.storage import table
from app.shared.database import Database, default_migrations_dir
from app.shared.exceptions import PermissionDenied
from app.shared.migrations import Migrator, load_migration_catalog
from backend.tests.test_knowledge_api import managed as managed_fixture
from backend.tests.test_knowledge_chunks import import_rows, source_fingerprint
from backend.tests.test_knowledge_governance import (
    create,
    governance as governance_fixture,
    prepared as prepared_fixture,
)
from backend.tests.test_knowledge_import import export_row

managed = managed_fixture
governance = governance_fixture
prepared = prepared_fixture


def confirm(fixture, **overrides):
    return fixture[3].confirm_import(
        **{
            "actor_id": "synthetic_admin",
            "source_id": fixture[6],
            "instance_code": "synthetic_instance",
            "team_id": "synthetic_team",
            "expected_revision": 0,
            "confirmed": True,
            **overrides,
        }
    )


def test_confirmation_has_distinct_state_system_digest_and_no_provider_job_or_data_rewrite(
    governance,
):
    db, _, _, service, _, verifier, _ = governance
    before = source_fingerprint(db)
    binding = confirm(governance)
    assert binding["state"] == "CONFIRMED"
    assert len(binding["attestation_hash"]) == 64
    assert (
        binding["verification_hash"] is binding["verified_job_id"] is binding["verified_at"] is None
    )
    assert binding["checked_count"] == 0 and verifier.calls == []
    assert source_fingerprint(db) == before
    assert service.assert_current(binding)
    audits = db.execute("select * from audit_event where event_type='knowledge.source.confirmed'")
    assert len(audits) == 1
    assert "synthetic_team" not in json.dumps(audits)
    with pytest.raises(KnowledgeGovernanceError, match="knowledge_revision_conflict"):
        confirm(governance)


@pytest.mark.parametrize(
    "changes",
    [
        {"confirmed": False},
        {"confirmed": 1},
        {"team_id": ""},
        {"team_id": "显示名称"},
        {"instance_code": "other"},
        {"expected_revision": True},
        {"source_id": "missing"},
    ],
)
def test_confirmation_rejects_unknown_or_implicit_source(governance, changes):
    with pytest.raises(KnowledgeGovernanceError):
        confirm(governance, **changes)
    assert not governance[0].execute('select * from "knowledge.source_binding"')


def test_confirmation_requires_current_management_authority_and_fixed_target(governance):
    governance[4].allowed = False
    with pytest.raises(PermissionDenied):
        confirm(governance)
    governance[4].allowed = True
    governance[3].verifier = None
    with pytest.raises(KnowledgeGovernanceError, match="knowledge_verifier_unavailable"):
        confirm(governance)


def test_legacy_confirmation_is_not_required_by_new_publication(governance):
    db, vector, snapshot, sources, _, verifier, _ = governance
    vector.build("synthetic-v1", snapshot)
    binding = confirm(governance)
    service = KnowledgeResourceService(
        sources,
        vector.repository,
        embedding=vector.embedding,
        qdrant=vector.qdrant,
    )
    resource = service.create(
        actor_id="synthetic_admin",
        knowledge_base_id=snapshot["knowledge_base_id"],
        code="synthetic",
        name="合成确认流程",
    )
    draft = service.save_draft(
        actor_id="synthetic_admin",
        resource_id=resource["id"],
        expected_revision=1,
        index_id=vector.repository.get("synthetic-v1")["id"],
    )
    verified = service.verify_draft(
        actor_id="synthetic_admin",
        resource_id=resource["id"],
        expected_revision=draft["revision"],
    )
    service.publish(
        actor_id="synthetic_admin",
        resource_id=resource["id"],
        expected_revision=verified["revision"],
    )
    pinned = service.resolve(snapshot["knowledge_base_id"])
    assert verifier.calls == []
    assert sources.catalog()["bindings"][0]["state"] == "CONFIRMED"
    assert service.catalog()["bases"][0]["source_ids"] == [governance[6]]
    sources.revoke(actor_id="synthetic_admin", binding_id=binding["id"])
    service.recheck(pinned)  # 历史来源确认不再控制新发布。
    assert db.execute("pragma foreign_key_check") == []


def test_confirmation_replaces_legacy_binding_but_never_upgrades_pending_implicitly(governance):
    sources = governance[3]
    old = create(governance)
    with pytest.raises(KnowledgeGovernanceError, match="knowledge_source_unavailable"):
        sources.assert_current(old)
    new = confirm(governance, expected_revision=1)
    assert sources.store.get("source_binding", old["id"])["state"] == "REVOKED"
    assert new["revision"] == 2 and new["state"] == "CONFIRMED"
    with pytest.raises(sqlite3.IntegrityError):
        sources.store.add("source_binding", {**new, "id": "duplicate", "revision": 3})
    governance[0].execute(
        'update "knowledge.document_revision" set source_project_id=?', ("changed",)
    )
    with pytest.raises(KnowledgeGovernanceError, match="knowledge_source_changed"):
        sources.assert_current(new)


def assert_confirmation_migration_preserves_history(db, tmp_path):
    path = tmp_path / "before-confirmation"
    path.mkdir()
    shutil.copyfile(
        default_migrations_dir() / "legacy-v1-manifest.json", path / "legacy-v1-manifest.json"
    )
    for definition in load_migration_catalog(default_migrations_dir()):
        if definition.version <= "137":
            shutil.copyfile(default_migrations_dir() / definition.name, path / definition.name)
    Migrator(db, path, migrator_build="confirmation-before").run()
    from backend.tests.test_knowledge_chunks import import_historical_rows
    import_historical_rows(db, tmp_path, [export_row()])
    source = db.execute_one(f"select id from {table(db, 'source')}")["id"]
    db.execute(
        f"insert into {table(db, 'source_binding')} "
        "(id,source_id,revision,instance_code,target_hash,team_id,attestation_hash,corpus_hash,document_count,created_by,created_at) "
        "values (?,?,?,?,?,?,?,?,?,?,?)",
        (
            "pending",
            source,
            1,
            "synthetic",
            "a" * 64,
            "team",
            "b" * 64,
            "c" * 64,
            1,
            "admin",
            "2026-09-19",
        ),
    )
    db.execute(
        f"insert into {table(db, 'source_binding')} "
        "(id,source_id,revision,instance_code,target_hash,team_id,state,attestation_hash,corpus_hash,document_count,created_by,created_at,verification_hash,checked_count,verified_by,verified_at,verified_job_id) "
        "values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "verified",
            source,
            2,
            "synthetic",
            "a" * 64,
            "team",
            "VERIFIED",
            "b" * 64,
            "c" * 64,
            1,
            "admin",
            "2026-09-19",
            "d" * 64,
            1,
            "admin",
            "2026-09-19",
            "legacy_job",
        ),
    )
    db.execute(
        f"create table synthetic_source_reference (binding_id TEXT NOT NULL REFERENCES {table(db, 'source_binding')}(id))"
    )
    db.execute("insert into synthetic_source_reference(binding_id) values (?)", ("verified",))
    # 同时覆盖 139 对有历史发布/验证与双向外键的资源版本表升级。
    from app.modules.knowledge.application.chunk_service import ChunkService
    from app.modules.knowledge.infrastructure.chunk_repository import ChunkRepository
    from app.modules.knowledge.application.vector_service import VectorService
    from app.modules.knowledge.infrastructure.vector_repository import VectorRepository
    from app.modules.knowledge.domain.chunking import DEFAULT_PROFILE
    from app.modules.knowledge.infrastructure.governance_repository import GovernanceStore
    from backend.tests.test_knowledge_vectors import SyntheticEmbedding, SyntheticQdrant

    chunks = ChunkService(ChunkRepository(db)).run(
        knowledge_base_code="synthetic_base", expected_count=1, commit=True
    )["counts"]["chunks"]
    vector = VectorService(VectorRepository(db), SyntheticEmbedding(), SyntheticQdrant())
    snapshot = vector.repository.snapshot(
        vector.repository.scope("synthetic_base"), DEFAULT_PROFILE.fingerprint, 1, chunks
    )
    vector.build("synthetic-migration", snapshot)
    index = vector.repository.get("synthetic-migration")
    store = GovernanceStore(db)
    store.add(
        "retrieval_resource",
        {
            "id": "legacy-resource",
            "knowledge_base_id": index["knowledge_base_id"],
            "code": "legacy-resource",
            "name": "合成历史资源",
            "created_by": "synthetic_admin",
            "created_at": "2026-09-19",
            "updated_at": "2026-09-19",
        },
    )
    store.add(
        "retrieval_revision",
        {
            "id": "legacy-revision",
            "resource_id": "legacy-resource",
            "revision": 1,
            "binding_id": "verified",
            "index_id": index["id"],
            "profile_hash": index["profile_hash"],
            "corpus_hash": index["corpus_hash"],
            "config_hash": "e" * 64,
            "created_by": "synthetic_admin",
            "created_at": "2026-09-19",
        },
    )
    store.add(
        "retrieval_verification",
        {
            "id": "legacy-verification",
            "resource_id": "legacy-resource",
            "resource_revision": 1,
            "revision_id": "legacy-revision",
            "config_hash": "e" * 64,
            "status": "VERIFIED",
            "evidence_hash": "f" * 64,
            "created_by": "synthetic_admin",
            "created_at": "2026-09-19",
        },
    )
    store.publish("legacy-resource", "legacy-revision", "synthetic_admin")
    history = {
        name: db.execute(f"select * from {table(db, name)}")
        for name in (
            "retrieval_resource",
            "retrieval_revision",
            "retrieval_verification",
        )
    }
    before = db.execute(f"select * from {table(db, 'source_binding')} order by id")
    data_tables = (
        "source",
        "document",
        "document_revision",
        "knowledge_base",
        "knowledge_base_document",
        "import_run",
        "document_relation",
        "document_chunk",
        "document_chunk_set",
        "vector_index",
        "vector_index_item",
    )
    content = {name: db.execute(f"select * from {table(db, name)}") for name in data_tables}
    result = Migrator(db, default_migrations_dir(), migrator_build="confirmation-after").run()
    assert result.applied == ("138", "139", "140", "141", "142", "143", "144")
    assert db.execute(f"select * from {table(db, 'source_binding')} order by id") == before
    after_content = {name: db.execute(f"select * from {table(db, name)}") for name in data_tables}
    for row in after_content["document"]:
        assert row.pop("source_observed_stamp_raw") is None
    for row in after_content["vector_index"]:
        assert row.pop("sync_run_id") is None
        assert row.pop("source_id") is None
        assert row.pop("unreferenced_at") is None
    assert after_content == content
    migrated_history = {name: db.execute(f"select * from {table(db, name)}") for name in history}
    for row in migrated_history["retrieval_revision"]:
        assert row.pop("storage_config_json") is None
        assert row.pop("configuration_version") == 0
    assert migrated_history == history
    assert db.execute_one("select binding_id from synthetic_source_reference") == {
        "binding_id": "verified"
    }
    if db.engine == "sqlite":
        assert db.execute("pragma foreign_key_check") == []
    assert (
        not Migrator(db, default_migrations_dir(), migrator_build="confirmation-replay")
        .run()
        .applied
    )
    from app.modules.audit.application.audit_service import AuditService
    from app.modules.job.infrastructure.repositories import AuditRepository
    from app.modules.knowledge.application.source_service import SourceBindingService
    from app.modules.knowledge.infrastructure.governance_repository import GovernanceStore
    from backend.tests.test_knowledge_governance import SyntheticPermission, SyntheticVerifier

    service = SourceBindingService(
        GovernanceStore(db),
        SyntheticPermission(),
        AuditService(AuditRepository(db)),
        SyntheticVerifier(),
    )
    binding = service.confirm_import(
        actor_id="synthetic_admin",
        source_id=source,
        instance_code="synthetic_instance",
        team_id="team",
        expected_revision=2,
        confirmed=True,
    )
    assert binding["state"] == "CONFIRMED" and binding["verified_job_id"] is None
    assert service.assert_current(binding)
    assert service.store.get("source_binding", "verified")["verification_hash"] == "d" * 64
    resources = KnowledgeResourceService(
        service, vector.repository, embedding=vector.embedding, qdrant=vector.qdrant
    )
    with pytest.raises(KnowledgeGovernanceError):
        resources.resolve(index["knowledge_base_id"])
    current = resources.view("legacy-resource")
    draft = resources.save_draft(
        actor_id="synthetic_admin",
        resource_id=current["id"],
        expected_revision=current["revision"],
        index_id=index["id"],
    )
    assert draft["draft"]["binding_id"] is None
    checked = resources.verify_draft(
        actor_id="synthetic_admin", resource_id=current["id"], expected_revision=draft["revision"]
    )
    resources.publish(
        actor_id="synthetic_admin", resource_id=current["id"], expected_revision=checked["revision"]
    )
    assert resources.resolve(index["knowledge_base_id"])
    assert store.get("retrieval_revision", "legacy-revision") == {
        **history["retrieval_revision"][0], "storage_config_json": None, "configuration_version": 0,
    }
    assert (
        store.get("retrieval_verification", "legacy-verification")
        == history["retrieval_verification"][0]
    )
    if db.engine == "sqlite":
        assert db.execute("pragma foreign_key_check") == []


def test_forward_confirmation_migration_preserves_pending_and_verified_history(tmp_path):
    db = Database("sqlite:///:memory:")
    try:
        assert_confirmation_migration_preserves_history(db, tmp_path)
    finally:
        db.close()


def test_cli_is_explicit_no_job_no_external_calls_and_safe_output(managed, monkeypatch, capsys):
    runtime, _, _, sources, _ = managed
    db = runtime.database
    monkeypatch.setattr(cli, "Database", lambda _: db)
    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda: SimpleNamespace(
            database_dsn="synthetic",
            ones_identity=SimpleNamespace(instance_code="synthetic_instance"),
            ones_mcp=SimpleNamespace(provider_base_url="http://ones-mock:8001"),
        ),
    )
    source = db.execute_one('select id from "knowledge.source"')["id"]
    args = [
        "--source-id",
        source,
        "--actor-id",
        "user_local_admin",
        "--instance-code",
        "synthetic_instance",
        "--team-id",
        "synthetic_team",
        "--expected-revision",
        "0",
    ]
    assert cli.main(args) == 0
    assert json.loads(capsys.readouterr().out)["event"] == "source_preflight_passed"
    assert not sources.catalog()["bindings"]
    assert cli.main([*args, "--commit"]) == 1
    assert "knowledge_input_invalid" in capsys.readouterr().out
    assert not sources.catalog()["bindings"]
    assert cli.main([*args, "--confirm-source", "--commit"]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "CONFIRMED"
    assert sources.catalog()["bindings"][0]["verified_job_id"] is None


def test_cli_failure_does_not_print_raw_exception(monkeypatch, capsys):
    def unavailable():
        raise RuntimeError("synthetic-private-database-error")

    monkeypatch.setattr(cli, "load_settings", unavailable)
    assert (
        cli.main(
            [
                "--source-id",
                "s",
                "--actor-id",
                "a",
                "--instance-code",
                "i",
                "--team-id",
                "t",
                "--expected-revision",
                "0",
            ]
        )
        == 1
    )
    assert "synthetic-private" not in capsys.readouterr().out
