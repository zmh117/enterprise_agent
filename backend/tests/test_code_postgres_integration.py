"""Disposable PostgreSQL only: actual row locks, CAS and cleanup preservation.

SVN completion and model I/O remain synthetic; the explicit Qdrant test uses
an isolated real vector service. No business database or collection is used.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import os
from threading import Barrier
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import pytest

from app.modules.knowledge.infrastructure.vector_clients import QdrantClient
from app.modules.knowledge.infrastructure.code_index_executor import CodeIndexExecutor
from app.modules.knowledge.infrastructure.code_index_store import CodeIndexStore
from app.modules.knowledge.infrastructure.code_answer_reader import CodeAnswerReader
from app.modules.knowledge.application.code_answer_search import search_code_answers
from backend.tests.test_knowledge_vectors import SyntheticEmbedding
from backend.tests.test_code_answer_search import Reranker
from backend.tests.test_code_answer_indexing import task
from backend.tests import test_code_answer_indexing as index_cases
from backend.tests import test_code_answer_search as search_cases
from backend.tests.support.code_answers import CODE_INDEX_ID

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.infrastructure.code_answer_store import CodeAnswerStore
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import Migrator
from backend.tests.support.runtime import (
    build_test_container,
    test_settings as runtime_settings,
    direct_job_permission_service_factory,
)
from backend.tests.support.code_answers import analysis_context, code_configuration, confirm
from backend.tests.test_code_answer_store import prepared, save

indexing = index_cases.indexing


@pytest.fixture
def database():
    dsn = os.environ.get("KNOWLEDGE_POLICY_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("explicit disposable PostgreSQL DSN not supplied")
    name = "codex_code_test_" + uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        db = Database(make_conninfo(dsn, dbname=name), pool_max_size=8)
        try:
            yield db
        finally:
            db.close()
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


@pytest.fixture
def workspace(database, tmp_path):
    Migrator(database, default_migrations_dir(), migrator_build="code-pg-test").run()
    runtime = build_test_container(
        replace(runtime_settings(), database_dsn=database.dsn),
        migrate=False,
        seed=True,
        configure_seed_secrets=True,
        permission_service_factory=direct_job_permission_service_factory,
    )
    try:
        runtime.create_agent_job_service.published_agent_runtime_enabled = True
        runtime.create_agent_job_service.runtime_readiness_guard = None
        _, source, checkout, _ = code_configuration(runtime, tmp_path)
        yield (
            runtime,
            CodeAnswerStore(runtime.database, authorize=lambda context: None),
            source,
            checkout,
        )
    finally:
        runtime.database.close()


def concurrent(function, values):
    barrier = Barrier(len(values))

    def run(value):
        barrier.wait(timeout=10)
        return function(value)

    with ThreadPoolExecutor(max_workers=len(values)) as pool:
        return list(pool.map(run, values))


def test_postgres_schema_comments_and_cross_source_constraints(workspace):
    from backend.tests.test_code_on_demand_schema import NEW_TABLES

    runtime, store, _, checkout = workspace
    db = runtime.database
    tables = db.execute(
        "SELECT c.relname AS name, obj_description(c.oid) AS comment "
        "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='knowledge' AND c.relkind='r' AND c.relname LIKE ?",
        ("code_%",),
    )
    assert {row["name"] for row in tables} == NEW_TABLES
    assert all(row["comment"] for row in tables)
    missing = db.execute(
        "SELECT c.relname,a.attname FROM pg_attribute a "
        "JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='knowledge' AND c.relkind='r' AND c.relname LIKE ? "
        "AND a.attnum>0 AND NOT a.attisdropped AND col_description(c.oid,a.attnum) IS NULL",
        ("code_%",),
    )
    assert missing == []
    other = store.register_repository(
        "00000000-0000-0000-0000-000000000002", "trunk", "https://svn.invalid/other"
    )
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        db.execute(
            "UPDATE knowledge.code_resource_config SET source_id=? WHERE revision_id=?",
            (other, "code-config"),
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "UPDATE knowledge.code_checkout SET verified_revision=NULL WHERE id=?",
            (checkout["id"],),
        )


def test_postgres_nearest_higher_applies_authorization_before_version_choice(indexing):
    search_cases.test_nearest_higher_is_authorized_ready_version_and_only_a_hint(indexing)


@pytest.mark.parametrize(
    "case",
    [
        index_cases.test_late_upsert_cannot_replace_new_ready_generation,
        index_cases.test_late_remove_cannot_delete_reincluded_generation,
    ],
)
def test_postgres_late_vector_operation_cannot_replace_current_answer(indexing, monkeypatch, case):
    case(indexing, monkeypatch)


def test_postgres_expired_writer_requires_stop_before_correction(indexing):
    index_cases.test_expired_claim_is_not_takeover_and_corrected_answer_is_not_visible(indexing)


def test_postgres_index_worker_recovery_requires_stop_proof(indexing):
    index_cases.test_index_worker_recovery_requires_local_stop_proof(indexing)


def test_postgres_background_worker_indexes_queued_answer(indexing, monkeypatch, tmp_path):
    index_cases.test_background_worker_discovers_and_indexes_queued_answer(
        indexing, monkeypatch, tmp_path
    )


def test_postgres_shared_readers_stop_proof_and_write_to_read(workspace):
    runtime, store, source, checkout = workspace
    contexts = [analysis_context(runtime, source, checkout, key=key) for key in ("a", "b")]
    readers = concurrent(lambda ctx: confirm(store, ctx, store.begin(ctx, ctx.job_id)), contexts)
    assert readers[0]["generation"] == readers[1]["generation"]
    writer = analysis_context(runtime, source, checkout, key="writer", revision=101)
    with pytest.raises(CodeKnowledgeError, match="WORKSPACE_BUSY"):
        store.begin(writer, "writer")
    store.db.execute(
        f"UPDATE {store.t('code_analysis')} SET lease_until='2000-01-01T00:00:00+00:00' WHERE id=?",
        (readers[0]["id"],),
    )
    with pytest.raises(CodeKnowledgeError, match="CODE_EXECUTION_NOT_QUIESCED"):
        store.release_stopped(contexts[0], readers[0]["id"])
    for ctx, analysis in zip(contexts, readers, strict=True):
        runtime.database.execute(
            "UPDATE agent_runtime_invocation SET execution_quiesced_at=CURRENT_TIMESTAMP WHERE invocation_id=?",
            (ctx.invocation_id,),
        )
        store.release_stopped(ctx, analysis["id"])
        if ctx == contexts[0]:
            with pytest.raises(CodeKnowledgeError, match="WORKSPACE_BUSY"):
                store.begin(writer, "writer")
    writing = store.begin(writer, "writer")
    assert store.row("code_checkout", checkout["id"])["writer_operation_id"]
    reading = confirm(store, writer, writing)
    state = store.row("code_checkout", checkout["id"])
    assert state["writer_operation_id"] is None and state["verified_revision"] == 101
    assert store.require_reader(writer, reading["id"])["requested_revision"] == 101


def test_postgres_same_identity_double_save_and_correction_cas(workspace):
    store = workspace[1]
    inputs = [prepared(workspace, key) for key in ("first", "second")]
    results = concurrent(lambda args: save(store, *args), inputs)
    assert results[0]["revision_id"] == results[1]["revision_id"]
    assert len(store.db.execute(f"SELECT id FROM {store.t('document_revision')}")) == 1
    assert len(store.db.execute(f"SELECT id FROM {store.t('code_index_task')}")) == 1
    corrections = [prepared(workspace, key) for key in ("correct-a", "correct-b")]
    for pos, (_, _, value) in enumerate(corrections):
        value.update(
            answer=f"Synthetic corrected result {pos}",
            expected_current_revision_id=results[0]["revision_id"],
        )

    def apply(args):
        try:
            return save(store, *args)
        except CodeKnowledgeError as exc:
            return {"error": exc.code}

    outcomes = concurrent(apply, corrections)
    assert sum("revision_id" in item for item in outcomes) == 1
    assert [item["error"] for item in outcomes if "error" in item] == [
        "CODE_ANSWER_REVISION_CONFLICT"
    ]


def test_postgres_retirement_and_migration_preserve_other_sources(database, tmp_path):
    from backend.tests.test_code_on_demand_schema import legacy_catalog
    from app.modules.knowledge.infrastructure.storage import insert
    from app.modules.knowledge.infrastructure.code_retirement_inventory import (
        CodeRetirementInventory,
    )
    from app.modules.knowledge.infrastructure.code_retirement import CodeRetirement

    Migrator(database, legacy_catalog(tmp_path), migrator_build="retirement-pg-test").run()
    stamp = "2026-11-09T00:00:00+00:00"
    for source, kind in (("code", "rule"), ("ones", "article")):
        insert(
            database,
            "source",
            dict(
                id=source,
                code=source,
                display_name=source,
                source_system="svn" if source == "code" else "ones",
                origin_state="verified",
                identity_metadata={},
                created_at=stamp,
            ),
        )
        insert(
            database,
            "knowledge_base",
            dict(
                id=source,
                code=source,
                display_name=source,
                description="",
                state="storage_only",
                created_at=stamp,
            ),
        )
        insert(
            database,
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
    insert(
        database,
        "code_binding",
        dict(
            source_id="code",
            knowledge_base_id="code",
            config_revision=1,
            config_hash="a" * 64,
            config_json={},
            created_at=stamp,
            updated_at=stamp,
        ),
    )
    inventory = CodeRetirementInventory(database).inspect()
    with pytest.raises(CodeKnowledgeError, match="CODE_RETIREMENT_INVENTORY_CHANGED"):
        CodeRetirement(database).retire("0" * 64)
    assert CodeRetirementInventory(database).inspect() == inventory
    result = CodeRetirement(database).retire(inventory["digest"])
    assert result["retired_documents"] == 1 and result["retained_other_documents"] == 1
    Migrator(database, default_migrations_dir(), migrator_build="retirement-pg-test").run()
    assert database.execute("SELECT id FROM knowledge.document") == [{"id": "ones"}]
    assert (
        database.execute_one("SELECT kind FROM knowledge.knowledge_base WHERE id='code'")["kind"]
        == "code"
    )


@pytest.mark.parametrize("revision", [100, 101])
@pytest.mark.parametrize("outcome", ["failed", "expired"])
def test_postgres_operation_failure_and_expiry_close_typed_timestamps(workspace, revision, outcome):
    from app.modules.knowledge.infrastructure.code_operation_store import CodeOperationStore

    runtime, _, source, checkout = workspace
    store = CodeOperationStore(runtime.database, authorize=lambda context: None)
    ctx = analysis_context(runtime, source, checkout, revision=revision)
    analysis = store.begin(ctx, "begin")
    operation = store.db.execute_one(
        f"SELECT id FROM {store.t('code_svn_operation')} WHERE analysis_id=?", (analysis["id"],)
    )
    if outcome == "failed":
        owned = store.claim(operation["id"], owner="worker")
        store.stopped(
            operation["id"],
            owner="worker",
            claim=owned["claim_version"],
            error_code="CODE_SYNTHETIC_FAILURE",
        )
    else:
        store.db.execute(
            f"UPDATE {store.t('code_svn_operation')} SET deadline_at='2000-01-01T00:00:00+00:00' WHERE id=?",
            (operation["id"],),
        )
        assert store.expire_queued(operation["id"])
    closed = store.row("code_analysis", analysis["id"])
    assert closed["closed_at"] and closed["reads_quiesced_at"]
    assert (closed["read_released_at"] is None) == (revision == 101)


def test_real_qdrant_lost_response_version_filter_and_reinclude(workspace, tmp_path, monkeypatch):
    """Real PG/Qdrant with synthetic embeddings; never touches a production collection."""
    endpoint = os.environ.get("CODE_TEST_QDRANT_ENDPOINT")
    if not endpoint:
        pytest.skip("explicit disposable Qdrant endpoint not supplied")

    db = workspace[0].database
    store = CodeIndexStore(db)
    db.execute(
        f"UPDATE {store.t('vector_index')} SET collection_name=? WHERE id=?",
        ("code_answers_" + CODE_INDEX_ID.replace("-", ""), CODE_INDEX_ID),
    )
    embedding, qdrant = SyntheticEmbedding(), QdrantClient(endpoint=endpoint)
    executor = CodeIndexExecutor(
        store, embedding, qdrant, owner="real-vector-test", execution_root=tmp_path.resolve()
    )
    original = qdrant.upsert

    def lose_response(index, points):
        original(index, points)
        raise TimeoutError("synthetic response loss after actual Qdrant acknowledgement")

    def search(revision, mode="exact"):
        index = store.db.execute_one(
            f"SELECT * FROM {store.t('vector_index')} WHERE id=?", (CODE_INDEX_ID,)
        )
        return search_code_answers(
            store=CodeAnswerReader(db),
            index=index,
            revision=revision,
            mode=mode,
            allowed_paths=["set_server"],
            query="为什么无法发布工单",
            top_k=10,
            resource_revision_id="code-config",
            embedding=embedding,
            qdrant=qdrant,
            reranker=Reranker(),
            check=lambda: None,
        )

    try:
        ctx, analysis, result = prepared(workspace)
        saved = save(workspace[1], ctx, analysis, result)
        work = task(store, saved["revision_id"])
        monkeypatch.setattr(qdrant, "upsert", lose_response)
        assert executor.execute(work["id"])
        failed = store.row("code_index_task", work["id"])
        assert failed["state"] == "failed" and failed["ready_at"] is None
        monkeypatch.setattr(qdrant, "upsert", original)
        with db.unit_of_work():
            index, _, _ = store._current(failed)
            store.enqueue(index, work["document_id"], work["revision_id"], "upsert", restart=True)
        encoded = embedding.encoded
        assert executor.execute(work["id"])
        assert store.row("code_index_task", work["id"])["state"] == "succeeded"
        assert embedding.encoded == encoded
        assert [x["svn_revision"] for x in search(100)["documents"]] == [100]
        assert search(99)["documents"] == []
        hint = search(99, "next_higher_hint")
        assert hint["requires_verification"] and hint["matched_revision"] == 100
        with db.unit_of_work():
            db.execute(f"UPDATE {store.t('knowledge_base_document')} SET state='removed'")
            store.enqueue(index, work["document_id"], work["revision_id"], "remove")
        assert executor.execute(task(store, saved["revision_id"], "remove")["id"])
        assert qdrant.count(index) == 0
        ctx, analysis, result = prepared(workspace, "reinclude-real")
        assert save(workspace[1], ctx, analysis, result)["revision_id"] == saved["revision_id"]
        assert executor.execute(work["id"])
        assert [x["svn_revision"] for x in search(100)["documents"]] == [100]
    finally:
        qdrant.http.close()
