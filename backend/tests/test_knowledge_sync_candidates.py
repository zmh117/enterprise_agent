"""候选隔离和恢复合同；全部业务输入为合成数据。"""

import os
import shutil
import sqlite3
import uuid

import pytest

from app.modules.knowledge.application.sync_service import KnowledgeSyncService
from app.modules.knowledge.application.import_service import KnowledgeImportService
from app.modules.knowledge.infrastructure.import_repository import ImportRepository
from app.modules.knowledge.domain.identity import stable_id
from app.modules.knowledge.domain.normalization import ExportValidationError
from app.modules.knowledge.infrastructure.sync_repository import SyncRepository
from app.modules.knowledge.infrastructure.candidate_corpus import (
    CandidateChunkRepository,
    CandidateVectorRepository,
)
from app.modules.knowledge.infrastructure.chunk_repository import ChunkRepository
from app.modules.knowledge.infrastructure.vector_repository import VectorRepository
from app.modules.knowledge.application.chunk_service import ChunkService
from app.modules.knowledge.domain.chunking import DEFAULT_PROFILE, WORK_ITEM_PROFILE
from app.modules.knowledge.domain.vector_contract import VectorError
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import Migrator, load_migration_catalog
from backend.tests.test_knowledge_chunks import import_historical_rows
from backend.tests.test_schema_migration_postgres_integration import (
    postgres_database_dsn as postgres_fixture,
)
from backend.tests.test_knowledge_import import (
    database as database_fixture,
    export_row,
    prepare as prepare_defect,
    run,
)
from backend.tests.test_knowledge_work_item_types import prepare, typed_row
from backend.tests.support.migrations import schema_versions_after

database = database_fixture
postgres_database_dsn = postgres_fixture


def configured(database, *, suffix=""):
    repo = SyncRepository(database)
    codes = {
        "defect": "synthetic_base" + suffix,
        "ticket": "synthetic_tickets" + suffix,
        "requirement": "synthetic_requirements" + suffix,
    }
    binding = repo.configure(
        code="synthetic_sync" + suffix,
        source_code="synthetic_source" + suffix,
        configuration={"base_codes": codes, "resource_ids": []},
        expected_revision=0,
    )
    return repo, binding, KnowledgeSyncService(repo)


def test_new_work_items_are_pending_and_not_current_members(database, tmp_path):
    repo, binding, service = configured(database)
    prepared = prepare(tmp_path, [typed_row()], "requirement")
    result = service.stage_exports(binding["id"], (prepared,))
    assert result["phase"] == "STAGED" and result["counts"] == {"created": 1}
    doc = database.execute_one('select * from "knowledge.document"')
    assert doc["lifecycle_state"] == "pending" and doc["current_revision_id"] is None
    assert database.execute('select * from "knowledge.knowledge_base_document"') == []
    assert database.execute_one('select count(*) as n from "knowledge.document_revision"')["n"] == 1
    assert binding["enabled"] == 0 and binding["interval_seconds"] == 3600
    assert repo.run(result["run_id"])["activated_watermark"] is None
    assert service.stage_exports(binding["id"], (prepared,)) == result


def test_changed_content_and_candidate_relations_do_not_replace_current(database, tmp_path):
    detail, listing = export_row(target="synthetic_item_2")
    run(database, prepare_defect(tmp_path, [(detail, listing)]))
    before = database.execute_one('select * from "knowledge.document"')
    repo, binding, service = configured(database)
    detail["desc"] = "合成更新正文"
    detail["server_update_stamp"] += 100
    detail["links"][0]["task_uuid"] = "synthetic_item_3"
    result = service.stage_exports(binding["id"], (prepare_defect(tmp_path, [(detail, listing)]),))
    assert result["counts"] == {"revised": 1}
    assert database.execute_one('select * from "knowledge.document"') == before
    candidate = repo.candidate(result["run_id"], before["id"])
    assert candidate["candidate_revision_id"] != before["current_revision_id"]
    assert (
        database.execute_one(
            'select to_external_id from "knowledge.document_relation" where evidence_revision_id=?',
            (before["current_revision_id"],),
        )["to_external_id"]
        == "synthetic_item_2"
    )
    assert (
        database.execute_one(
            'select to_external_id from "knowledge.document_relation" where evidence_revision_id=?',
            (candidate["candidate_revision_id"],),
        )["to_external_id"]
        == "synthetic_item_3"
    )


def test_timestamp_only_update_reuses_revision_and_holds_observation_watermark(database, tmp_path):
    detail, listing = export_row()
    run(database, prepare_defect(tmp_path, [(detail, listing)]))
    before = database.execute_one('select * from "knowledge.document"')
    repo, binding, service = configured(database)
    detail["server_update_stamp"] += 100
    result = service.stage_exports(binding["id"], (prepare_defect(tmp_path, [(detail, listing)]),))
    candidate = repo.candidate(result["run_id"], before["id"])
    assert result["counts"] == {"unchanged": 1}
    assert candidate["candidate_revision_id"] == before["current_revision_id"]
    assert candidate["observed_stamp"] == detail["server_update_stamp"]
    assert repo.changed_bases(result["run_id"]) == set()
    assert database.execute_one('select * from "knowledge.document"') == before
    assert database.execute_one('select count(*) as n from "knowledge.document_revision"')["n"] == 1


def test_type_migration_has_two_candidate_members_but_no_current_mutation(database, tmp_path):
    run(database, prepare_defect(tmp_path, [export_row()]))
    before = database.execute_one('select * from "knowledge.document"')
    repo, binding, service = configured(database)
    row = typed_row("ticket", body="合成工单正文")
    row[0]["server_update_stamp"] += 100
    result = service.stage_exports(binding["id"], (prepare(tmp_path, [row], "ticket"),))
    candidate = repo.candidate(result["run_id"], before["id"])
    assert candidate["candidate_kind"] == "ticket"
    assert candidate["candidate_members_json"] == {
        stable_id("base", "synthetic_base"): "removed",
        stable_id("base", "synthetic_tickets"): "included",
    }
    assert repo.changed_bases(result["run_id"]) == set(candidate["candidate_members_json"])
    assert database.execute_one('select * from "knowledge.document"') == before
    assert (
        database.execute_one('select count(*) as n from "knowledge.knowledge_base_document"')["n"]
        == 1
    )


def test_stale_type_migration_never_readds_member(database, tmp_path):
    run(database, prepare_defect(tmp_path, [export_row()]))
    repo, binding, service = configured(database)
    row = typed_row("ticket")
    row[0]["server_update_stamp"] -= 1
    result = service.stage_exports(binding["id"], (prepare(tmp_path, [row], "ticket"),))
    candidate = next(repo.candidates(result["run_id"]))
    assert candidate["outcome"] == "stale" and candidate["candidate_kind"] == "defect"
    assert candidate["candidate_members_json"] == candidate["baseline_members_json"]


def test_equal_version_content_conflict_keeps_current_and_failed_checkpoint(database, tmp_path):
    run(database, prepare_defect(tmp_path, [export_row()]))
    repo, binding, service = configured(database)
    row = export_row()
    row[0]["desc"] = "合成冲突"
    before = database.execute_one('select * from "knowledge.document"')
    with pytest.raises(ExportValidationError, match="knowledge_source_version_conflict"):
        service.stage_exports(binding["id"], (prepare_defect(tmp_path, [row]),))
    active = database.execute_one('select * from "knowledge.sync_run"')
    assert active["phase"] == "COLLECTING" and active["active"] == 1
    assert active["error_code"] == "knowledge_source_version_conflict"
    assert repo.run(active["id"])["checkpoint_json"]["processed"] == 0
    assert database.execute_one('select * from "knowledge.document"') == before


def test_restart_replays_committed_records_without_duplicates(database, tmp_path, monkeypatch):
    repo, binding, service = configured(database)
    prepared = prepare(tmp_path, [typed_row(index=1), typed_row(index=2)], "requirement")
    stage = repo.stage
    count = 0

    def crash_after_commit(run_id, record):
        nonlocal count
        outcome = stage(run_id, record)
        count += 1
        if count == 1:
            raise RuntimeError("synthetic body MUST NOT be saved in error code")
        return outcome

    monkeypatch.setattr(repo, "stage", crash_after_commit)
    with pytest.raises(ExportValidationError, match="knowledge_sync_failed"):
        service.stage_exports(binding["id"], (prepared,))
    assert database.execute_one('select count(*) as n from "knowledge.document_revision"')["n"] == 1
    recovered = KnowledgeSyncService(SyncRepository(database)).stage_exports(
        binding["id"], (prepared,)
    )
    assert recovered["checkpoint"] == {"processed": 2, "total": 2}
    assert recovered["counts"] == {"created": 2} and recovered["error_code"] is None
    assert database.execute_one('select count(*) as n from "knowledge.document_revision"')["n"] == 2


def test_freezing_baseline_commits_bounded_pages_and_resumes(database, tmp_path, monkeypatch):
    from app.shared.database import assert_external_io_allowed

    prepared = prepare_defect(tmp_path, [export_row()])
    run(database, prepared)
    repo, binding, service = configured(database)
    freeze = repo._freeze_page

    def crash_after_page(run_id):
        result = freeze(run_id)
        assert_external_io_allowed("synthetic_assert_page_transaction_closed")
        if result:
            raise RuntimeError("synthetic interruption after persisted page")
        return result

    monkeypatch.setattr(repo, "_freeze_page", crash_after_page)
    with pytest.raises(ExportValidationError, match="knowledge_sync_failed"):
        service.stage_exports(binding["id"], (prepared,))
    active = database.execute_one('select id from "knowledge.sync_run"')["id"]
    checkpoint = repo.run(active)["checkpoint_json"]
    assert checkpoint["baseline_seen"] == 1 and checkpoint["processed"] == 0
    assert checkpoint["baseline_complete"] is False
    assert len(list(repo.candidates(active))) == 1
    recovered = KnowledgeSyncService(SyncRepository(database)).stage_exports(
        binding["id"], (prepared,)
    )
    assert recovered["counts"] == {"unchanged": 1}
    assert recovered["checkpoint"] == {"processed": 1, "total": 1}


def test_configuration_revision_invalidates_staging_and_new_batch_cannot_bypass_active_run(
    database, tmp_path
):
    repo, binding, service = configured(database)
    prepared = prepare(tmp_path, [typed_row()], "requirement")
    run_row = repo.begin(binding["id"], (prepared,))
    repo.configure(
        code=binding["code"],
        source_code="synthetic_source",
        configuration=binding["configuration_json"],
        expected_revision=1,
    )
    with pytest.raises(ExportValidationError, match="knowledge_sync_configuration_changed"):
        repo.stage(run_row["id"], prepared.records[0])
    with pytest.raises(ExportValidationError, match="knowledge_source_import_busy"):
        service.stage_exports(binding["id"], (prepared,))
    assert database.execute('select * from "knowledge.document_revision"') == []


def test_configuration_rejects_unexpected_keys_and_duplicate_bases(database):
    repo, binding, _ = configured(database)
    for config in (
        {**binding["configuration_json"], "password": "synthetic"},
        {
            "base_codes": {k: "same" for k in ("defect", "ticket", "requirement")},
            "resource_ids": [],
        },
    ):
        with pytest.raises(ExportValidationError, match="knowledge_sync_configuration_invalid"):
            repo.configure(
                code=binding["code"],
                source_code="synthetic_source",
                configuration=config,
                expected_revision=1,
            )
    assert repo.binding(binding["id"])["configuration_revision"] == 1


def test_direct_import_is_blocked_during_active_candidate_run(database, tmp_path):
    repo, binding, service = configured(database)
    service.stage_exports(binding["id"], (prepare(tmp_path, [typed_row()], "requirement"),))
    with pytest.raises(ExportValidationError, match="knowledge_source_import_busy"):
        run(database, prepare_defect(tmp_path, [export_row(2)]))


def test_duplicate_uuid_across_types_fails_before_any_run(database, tmp_path):
    _, binding, service = configured(database)
    defects = prepare_defect(tmp_path, [export_row()])
    requirements = prepare(tmp_path, [typed_row()], "requirement")
    with pytest.raises(ExportValidationError, match="knowledge_sync_batch_invalid"):
        service.stage_exports(binding["id"], (defects, requirements))
    assert database.execute('select * from "knowledge.sync_run"') == []


def test_stage_transition_requires_order_and_cancel_is_recoverable(database, tmp_path):
    repo, binding, service = configured(database)
    prepared = prepare(tmp_path, [typed_row()], "requirement")
    result = service.stage_exports(binding["id"], (prepared,))
    run_id = result["run_id"]
    repo.assert_baseline(run_id)
    with pytest.raises(ExportValidationError, match="knowledge_sync_phase_invalid"):
        repo.advance(run_id, expected_phase="STAGED", phase="VERIFIED")
    repo.advance(run_id, expected_phase="STAGED", phase="CHUNKING")
    assert SyncRepository(database).run(run_id)["phase"] == "CHUNKING"
    repo.fail(run_id, "unsafe synthetic detail")
    assert repo.run(run_id)["error_code"] == "knowledge_sync_failed"
    repo.cancel(run_id)
    repo.cancel(run_id)
    assert repo.run(run_id)["active"] == 0
    assert (
        database.execute_one('select lifecycle_state from "knowledge.document"')["lifecycle_state"]
        == "pending"
    )
    # 原输入被明确取消，不能在同一配置下悄悄复活。
    with pytest.raises(ExportValidationError, match="knowledge_sync_run_cancelled"):
        service.stage_exports(binding["id"], (prepared,))


def test_baseline_check_rejects_concurrent_member_change(database, tmp_path):
    run(database, prepare_defect(tmp_path, [export_row()]))
    repo, binding, service = configured(database)
    result = service.stage_exports(binding["id"], (prepare_defect(tmp_path, [export_row()]),))
    repo.assert_baseline(result["run_id"])
    database.execute("update \"knowledge.knowledge_base_document\" set state='removed'")
    with pytest.raises(ExportValidationError, match="knowledge_sync_baseline_changed"):
        repo.assert_baseline(result["run_id"])


@pytest.mark.skipif(
    not os.getenv("KNOWLEDGE_TEST_POSTGRES_DSN"), reason="requires isolated PostgreSQL"
)
def test_postgres_pending_candidate_replay_and_source_exclusion(tmp_path):
    # 显式隔离实例中使用唯一来源；不清表或清理其他运行。
    dsn = os.environ["KNOWLEDGE_TEST_POSTGRES_DSN"]
    database, contender = Database(dsn), Database(dsn)
    try:
        Migrator(database, default_migrations_dir(), migrator_build="knowledge-sync-test").run()
        suffix = uuid.uuid4().hex
        repo, binding, service = configured(database, suffix=suffix)
        old_row = export_row(2)
        KnowledgeImportService(ImportRepository(database)).import_export(
            prepare_defect(tmp_path, [old_row]),
            source_code="synthetic_source" + suffix,
            knowledge_base_code="synthetic_base" + suffix,
        )
        with repo.source_lock(binding["source_id"]):
            with pytest.raises(ExportValidationError, match="knowledge_source_import_busy"):
                with SyncRepository(contender).source_lock(binding["source_id"]):
                    pytest.fail("a second process must not own the source")
        prepared = prepare(tmp_path, [typed_row()], "requirement")
        old_row[0]["server_update_stamp"] += 100
        exports = (prepared, prepare_defect(tmp_path, [old_row]))
        result = service.stage_exports(binding["id"], exports)
        assert result["counts"] == {"created": 1, "unchanged": 1}
        assert service.stage_exports(binding["id"], exports) == result
        doc = database.execute_one(
            "select lifecycle_state,current_revision_id from knowledge.document where source_id=? and external_id='synthetic_item_1'",
            (binding["source_id"],),
        )
        assert doc == {"lifecycle_state": "pending", "current_revision_id": None}
        assert repo.run(result["run_id"])["activated_watermark"] is None
        check_candidate_chunks(
            database, result["run_id"], binding["configuration_json"]["base_codes"]["requirement"]
        )
    finally:
        database.close()
        contender.close()


def check_candidate_chunks(database, run_id, base_code):
    chunks = CandidateChunkRepository(database, run_id, profile=WORK_ITEM_PROFILE)
    result = ChunkService(chunks).run(knowledge_base_code=base_code, expected_count=1, commit=True)
    assert result["counts"]["documents"] == 1
    repeated = ChunkService(chunks).run(
        knowledge_base_code=base_code, expected_count=1, commit=True
    )
    assert repeated["counts"]["reused"] == 1
    vectors = CandidateVectorRepository(database, run_id)
    base_id = stable_id("base", base_code)
    snapshot = vectors.snapshot(
        base_id, WORK_ITEM_PROFILE.fingerprint, 1, result["counts"]["chunks"]
    )
    assert snapshot["expected_document_count"] == 1
    rows = list(vectors.rows(base_id, WORK_ITEM_PROFILE.fingerprint))
    assert rows and all(row["document_kind"] == "requirement" for row in rows)
    assert list(VectorRepository(database).rows(base_id, WORK_ITEM_PROFILE.fingerprint)) == []
    with pytest.raises(VectorError, match="knowledge_vector_candidate_not_queryable"):
        vectors.evidence_many(snapshot, [rows[0]["id"]])


def test_pending_documents_can_be_chunked_only_in_frozen_candidate(database, tmp_path):
    _, binding, service = configured(database)
    result = service.stage_exports(
        binding["id"], (prepare(tmp_path, [typed_row()], "requirement"),)
    )
    check_candidate_chunks(database, result["run_id"], "synthetic_requirements")


def test_candidate_corpus_keeps_unchanged_baseline_and_overrides_changed_revision(
    database, tmp_path
):
    rows = [export_row(1), export_row(2)]
    run(database, prepare_defect(tmp_path, rows))
    original = ChunkService(ChunkRepository(database)).run(
        knowledge_base_code="synthetic_base", expected_count=2, commit=True
    )
    old_ids = {
        row["document_id"]: row["revision_id"]
        for row in ChunkRepository(database).rows(
            stable_id("base", "synthetic_base"), stable_id("source", "synthetic_source")
        )
    }
    repo, binding, service = configured(database)
    rows[0][0]["desc"] = "合成新内容"
    rows[0][0]["server_update_stamp"] += 100
    result = service.stage_exports(binding["id"], (prepare_defect(tmp_path, rows[:1]),))
    assert result["counts"] == {"baseline": 1, "revised": 1}
    candidate = CandidateChunkRepository(database, result["run_id"], profile=DEFAULT_PROFILE)
    derived = ChunkService(candidate).run(
        knowledge_base_code="synthetic_base", expected_count=2, commit=True
    )
    assert derived["counts"]["created"] == 1 and derived["counts"]["reused"] == 1
    old_again = ChunkService(ChunkRepository(database)).run(
        knowledge_base_code="synthetic_base", expected_count=2
    )
    assert (
        original["input_hash"] == old_again["input_hash"]
        and original["output_hash"] == old_again["output_hash"]
    )
    for record in candidate.rows(stable_id("base", "synthetic_base"), binding["source_id"]):
        item = repo.candidate(result["run_id"], record["document_id"])
        assert (record["revision_id"] == old_ids[record["document_id"]]) == (
            item["outcome"] == "baseline"
        )


def assert_upgrade_preserves_content_and_vector_references(database, tmp_path):
    from app.modules.knowledge.infrastructure.storage import table

    historical = tmp_path / "head-140"
    historical.mkdir()
    shutil.copyfile(
        default_migrations_dir() / "legacy-v1-manifest.json", historical / "legacy-v1-manifest.json"
    )
    for entry in load_migration_catalog(default_migrations_dir()):
        if entry.version <= "140":
            shutil.copyfile(default_migrations_dir() / entry.name, historical / entry.name)
    assert Migrator(database, historical, migrator_build="sync-before").run().head == "140"
    import_historical_rows(database, tmp_path, [export_row(target="synthetic_item_2")])
    chunks = ChunkService(ChunkRepository(database)).run(
        knowledge_base_code="synthetic_base", expected_count=1, commit=True
    )
    vectors = VectorRepository(database)
    snapshot = vectors.snapshot(
        stable_id("base", "synthetic_base"),
        DEFAULT_PROFILE.fingerprint,
        1,
        chunks["counts"]["chunks"],
    )
    index = vectors.create("synthetic-historical", snapshot)
    vectors.manifest(index)
    names = (
        "document",
        "document_revision",
        "document_relation",
        "knowledge_base_document",
        "document_chunk_set",
        "document_chunk",
        "vector_index",
        "vector_index_item",
    )
    before = {
        name: database.execute(f"select * from {table(database, name)} order by 1")
        for name in names
    }
    migrated = Migrator(database, default_migrations_dir(), migrator_build="sync-after").run()
    assert migrated.applied == schema_versions_after("140")
    after = {
        name: database.execute(f"select * from {table(database, name)} order by 1")
        for name in names
    }
    for row in after["document"]:
        assert row.pop("source_observed_stamp_raw") is None
    for row in after["vector_index"]:
        assert row.pop("sync_run_id") is None
        assert row.pop("source_id") is None
        assert row.pop("unreferenced_at") is None
    assert after == before
    assert (
        not Migrator(database, default_migrations_dir(), migrator_build="sync-replay").run().applied
    )
    if database.engine == "sqlite":
        assert database.execute("pragma foreign_key_check") == []
    # 标题块扩展必须保留旧 offset 和字符数约束。
    import psycopg

    with pytest.raises((sqlite3.IntegrityError, psycopg.IntegrityError)):
        with database.unit_of_work():
            database.execute(
                f"update {table(database, 'document_chunk')} set source_end=source_start"
            )
    for name in ("sync_binding", "sync_run", "sync_candidate"):
        assert database.execute(f"select * from {table(database, name)}") == []


def test_sqlite_upgrade_preserves_content_and_vector_references(tmp_path):
    database = Database("sqlite:///:memory:")
    try:
        assert_upgrade_preserves_content_and_vector_references(database, tmp_path)
    finally:
        database.close()


@pytest.mark.skipif(not os.getenv("MIGRATION_POSTGRES_DSN"), reason="requires isolated PostgreSQL")
def test_postgres_upgrade_preserves_content_and_vector_references(postgres_database_dsn, tmp_path):
    database = Database(postgres_database_dsn)
    try:
        assert_upgrade_preserves_content_and_vector_references(database, tmp_path)
    finally:
        database.close()
