"""补采和派生热路径合成验收；不连接 ONES、不读取部署凭据。"""

from datetime import UTC, date, datetime, timedelta
from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path

import pytest
import yaml
from types import SimpleNamespace

from app.cli import sync_ones_knowledge as cli
from app.modules.knowledge.application.chunk_service import ChunkService
from app.modules.knowledge.application.managed_sync_activation import ManagedSyncActivation
from app.modules.knowledge.application.managed_sync_pipeline import ManagedSyncPipeline
from app.modules.knowledge.domain.collection_window import check_resumed_range, validate_backfill
from app.modules.knowledge.domain.normalization import ExportValidationError
from app.modules.knowledge.domain.sync_health import sync_health
from app.modules.knowledge.infrastructure.chunk_repository import ChunkRepository
from backend.tests.test_knowledge_import import database as database_fixture, export_row
from backend.tests.test_knowledge_chunks import import_rows
from app.modules.knowledge.infrastructure.vector_repository import VectorRepository
from app.modules.knowledge.domain.chunking import DEFAULT_PROFILE
from app.modules.knowledge.domain.vector_contract import VectorError
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import Migrator
from backend.tests.test_knowledge_managed_activation import _prepare_run
from backend.tests.test_knowledge_managed_pipeline import FakeStore
from backend.tests.test_knowledge_ones_collection import _enabled_binding
from backend.tests.test_knowledge_vectors import prepared as prepared_fixture

database = database_fixture
prepared = prepared_fixture


def baseline(repo, binding, database):
    run = repo.begin_collection(binding["id"], "2026-10-01T00:00:00+00:00")
    # 仅为日期选择测试模拟已独立验收的基线；原子激活另有集成测试。
    database.execute(
        "update \"knowledge.sync_run\" set phase='ACTIVATED',active=0 where id=?", (run["id"],)
    )


def test_backfill_freezes_twenty_days_without_changing_normal_window(database):
    repo, binding = _enabled_binding(database)
    baseline(repo, binding, database)
    frozen = deepcopy(repo.binding(binding["id"]))
    run = repo.begin_collection(
        binding["id"],
        "2026-10-26T12:00:00+00:00",
        first=date(2026, 10, 7),
        through=date(2026, 10, 26),
    )
    assert repo.binding(binding["id"]) == frozen
    for manifest in run["manifest_json"].values():
        assert (manifest["scan_mode"], manifest["scan_first"], manifest["scan_last"]) == (
            "backfill",
            "2026-10-07",
            "2026-10-26",
        )
    window = (date(2026, 10, 7), date(2026, 10, 26))
    check_resumed_range(run, window)
    for wrong in (None, (date(2026, 10, 8), window[1])):
        with pytest.raises(ExportValidationError, match="knowledge_collection_range_changed"):
            check_resumed_range(run, wrong)
    database.execute(
        "update \"knowledge.sync_run\" set phase='ACTIVATED',active=0 where id=?", (run["id"],)
    )
    normal = repo.begin_collection(binding["id"], "2026-10-27T00:00:00+00:00")
    assert normal["manifest_json"]["defect"]["scan_first"] == "2026-10-21"


@pytest.mark.parametrize(
    "first,last",
    [
        (date(2023, 12, 31), date(2026, 10, 26)),
        (date(2026, 10, 27), date(2026, 10, 26)),
        (date(2026, 10, 7), date(2026, 10, 27)),
    ],
)
def test_invalid_backfill_rejected_before_begin(first, last):
    with pytest.raises(ExportValidationError, match="knowledge_collection_range_invalid"):
        validate_backfill(first, last, date(2024, 1, 1), date(2026, 10, 26))


def test_backfill_requires_prior_full_baseline(database):
    repo, binding = _enabled_binding(database)
    with pytest.raises(
        ExportValidationError, match="knowledge_collection_backfill_requires_baseline"
    ):
        repo.begin_collection(
            binding["id"],
            "2026-10-26T12:00:00+00:00",
            first=date(2026, 10, 7),
            through=date(2026, 10, 26),
        )
    assert database.execute('select id from "knowledge.sync_run"') == []


def test_pipeline_rejects_other_window_even_after_collecting():
    store = FakeStore("INDEXING", set())
    original = store.run

    def run(run_id, **kwargs):
        return {
            **original(run_id, **kwargs),
            "manifest_json": {
                "defect": {
                    "scan_mode": "backfill",
                    "scan_first": "2026-10-07",
                    "scan_last": "2026-10-26",
                }
            },
        }

    store.run = run
    pipeline = ManagedSyncPipeline(
        store,
        collect_once=lambda _: pytest.fail("new run"),
        chunk_base=lambda *_: pytest.fail("chunk"),
        index_base=lambda *_: pytest.fail("index"),
        activate=lambda _: pytest.fail("activate"),
    )
    with pytest.raises(ExportValidationError, match="knowledge_collection_range_changed"):
        pipeline.run_once("binding")


@pytest.mark.parametrize(
    "arguments",
    [
        ["--from-date", "2026-10-07"],
        ["--through-date", "2026-10-26"],
        ["--from-date", "invalid-synthetic-date", "--through-date", "2026-10-26"],
        ["--from-date", "2026-10-27", "--through-date", "2026-10-26"],
    ],
)
def test_cli_invalid_range_is_safe_before_database(monkeypatch, capsys, arguments):
    monkeypatch.setattr(cli, "load_settings", lambda: pytest.fail("must not connect"))
    assert cli.main(["--mode", "once", "--binding-code", "synthetic", *arguments]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["error_code"] in {
        "knowledge_collection_range_invalid",
        "knowledge_sync_arguments_invalid",
    }
    assert "invalid-synthetic-date" not in json.dumps(output)


def test_manifest_and_checkpoint_use_batch_sql(prepared, monkeypatch):
    db, service, snapshot = prepared
    repo = service.repository
    index = repo.create("synthetic-batched", snapshot)
    executed = []
    execute = db.execute

    def count_sql(sql, params=()):
        executed.append(sql)
        return execute(sql, params)

    monkeypatch.setattr(db, "execute", count_sql)
    repo.manifest(index)
    inserts = [
        sql for sql in executed if sql.startswith('insert into "knowledge.vector_index_item"')
    ]
    assert len(inserts) == 1 and snapshot["expected_chunk_count"] > 1
    assert not any("where index_id=? and chunk_id=?" in sql for sql in executed)
    rows = list(repo.rows(index["knowledge_base_id"], index["chunk_profile_hash"]))
    executed.clear()
    repo.checkpoint(index, rows, "INDEXED", attempted=True)
    assert sum(sql.startswith('update "knowledge.vector_index_item"') for sql in executed) == 1
    assert {
        row["attempt_count"]
        for row in db.execute('select attempt_count from "knowledge.vector_index_item"')
    } == {1}
    repo.manifest(index)  # 重放不覆盖已有检查点。
    assert {
        row["state"] for row in db.execute('select state from "knowledge.vector_index_item"')
    } == {"INDEXED"}


def test_reuse_hash_index_exists_and_is_used(prepared):
    db, service, snapshot = prepared
    service.build("synthetic-indexed", snapshot)
    index = service.repository.get("synthetic-indexed")
    rows = list(service.repository.rows(index["knowledge_base_id"], index["chunk_profile_hash"]))
    reused = service.repository.reusable_rows(index, [rows[0]["embedding_hash"]])
    assert rows[0]["embedding_hash"] in reused
    plan = db.execute(
        'explain query plan select chunk_id from "knowledge.vector_index_item" '
        "where index_id=? and state='INDEXED' and embedding_text_hash=?",
        (index["id"], rows[0]["embedding_hash"]),
    )
    assert any("knowledge_vector_reuse_hash_idx" in row["detail"] for row in plan)


def test_existing_chunks_reused_without_preparing_again(prepared, monkeypatch):
    db, _, _ = prepared
    monkeypatch.setattr(
        "app.modules.knowledge.application.chunk_service.prepare_chunks",
        lambda *_: pytest.fail("unchanged chunk recomputed"),
    )
    monkeypatch.setattr(
        ChunkRepository, "load_record", lambda *_: pytest.fail("unchanged source body loaded")
    )
    result = ChunkService(ChunkRepository(db)).run(
        knowledge_base_code="synthetic_base", expected_count=2, commit=True
    )
    assert result["counts"]["reused"] == 2 and result["counts"]["created"] == 0


def test_only_changed_revision_loads_source_and_prepares(prepared, tmp_path, monkeypatch):
    from app.modules.knowledge.application import chunk_service

    db, _, _ = prepared
    changed = export_row()
    changed[0]["desc"] += "合成新增描述"
    changed[0]["server_update_stamp"] += 100
    import_rows(db, tmp_path, [changed, export_row(2)])
    original = chunk_service.prepare_chunks
    calls = []

    def prepare(record, profile):
        calls.append(record["document_id"])
        return original(record, profile)

    monkeypatch.setattr(chunk_service, "prepare_chunks", prepare)
    result = ChunkService(ChunkRepository(db)).run(
        knowledge_base_code="synthetic_base", expected_count=2, commit=True
    )
    assert len(calls) == 1 and result["counts"]["created"] == result["counts"]["reused"] == 1


@pytest.mark.parametrize("mutation", ["missing", "hash", "profile"])
def test_reused_chunks_still_validate_integrity(prepared, mutation):
    db, _, _ = prepared
    statements = {
        "missing": 'delete from "knowledge.document_chunk" where id=(select id from "knowledge.document_chunk" limit 1)',
        "hash": 'update "knowledge.document_chunk" set embedding_hash=\'' + "0" * 64 + "'",
        "profile": "update \"knowledge.document_chunk_set\" set profile_version='wrong'",
    }
    db.execute(statements[mutation])
    with pytest.raises(ExportValidationError):
        ChunkService(ChunkRepository(db)).run(
            knowledge_base_code="synthetic_base", expected_count=2, commit=True
        )


def test_activation_verifies_same_target_once_and_not_again_on_replay(
    database, tmp_path, monkeypatch
):
    repo, resources, vectors, run_id, _, _ = _prepare_run(database, tmp_path, change=True)
    original = resources.qdrant.retrieve
    calls = []

    def retrieve(index, ids):
        calls.append(index["id"])
        return original(index, ids)

    monkeypatch.setattr(resources.qdrant, "retrieve", retrieve)
    activation = ManagedSyncActivation(repo, resources, vectors)
    assert activation.run(run_id)["phase"] == "ACTIVATED"
    assert len(calls) == 1
    activation.run(run_id)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "state,expected",
    [
        ("healthy", []),
        ("disabled", []),
        ("first_stale", ["knowledge_sync_success_stale"]),
        ("success_stale", ["knowledge_sync_success_stale"]),
        ("progress_stale", ["knowledge_sync_progress_stale"]),
        ("failed", ["knowledge_sync_run_failed"]),
    ],
)
def test_health_distinguishes_stale_and_disabled(state, expected):
    now = datetime(2026, 10, 26, 12, tzinfo=UTC)
    old, fresh = (now - timedelta(hours=3)).isoformat(), (now - timedelta(minutes=5)).isoformat()
    binding = {"enabled": int(state != "disabled"), "interval_seconds": 3600, "created_at": fresh}
    success = {"updated_at": old if state == "success_stale" else fresh}
    latest = {
        "id": "synthetic",
        "phase": "INDEXING",
        "error_code": "knowledge_vector_unavailable" if state == "failed" else None,
    }
    active = {"updated_at": old if state == "progress_stale" else fresh}
    if state == "first_stale":
        success = None
        binding["created_at"] = old
    result = sync_health(binding, latest, success, active, now)
    assert result["reasons"] == expected and result["healthy"] == (not expected)


def test_progress_keeps_collection_checkpoint_and_updates_status(database):
    repo, binding = _enabled_binding(database)
    run = repo.begin_collection(binding["id"], "2026-10-26T12:00:00+00:00")
    database.execute("update \"knowledge.sync_run\" set phase='INDEXING' where id=?", (run["id"],))
    before = repo.run(run["id"])["checkpoint_json"]
    repo.fail(run["id"], "knowledge_vector_timeout")
    repo.record_progress(
        run["id"], "indexing", {"processed": 32, "total": 65, "reused": 32, "encoded": 0}
    )
    after = repo.run(run["id"])["checkpoint_json"]
    assert {key: after[key] for key in before} == before
    assert repo.summary(run["id"])["progress"]["processed"] == 32
    assert repo.summary(run["id"])["error_code"] is None
    with pytest.raises(ExportValidationError, match="knowledge_sync_progress_invalid"):
        repo.record_progress(run["id"], "indexing", {"raw_text": "private synthetic"})


def test_compose_healthcheck_only_runs_read_only_health():
    service = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "knowledge/sync.compose.yml").read_text()
    )["services"]["knowledge-sync"]
    test = service["healthcheck"]["test"]
    assert "health" in test and "--commit" not in test and "--capacity-path" not in test
    assert service["healthcheck"]["interval"] == "60s"


def test_stage_progress_is_throttled_but_completion_is_persisted(database, tmp_path, monkeypatch):
    from app.modules.knowledge.infrastructure import managed_sync_steps
    from app.modules.knowledge.infrastructure.sync_repository import SyncRepository

    repo, binding = _enabled_binding(database)
    run = repo.begin_collection(binding["id"], "2026-10-26T12:00:00+00:00")
    database.execute("update \"knowledge.sync_run\" set phase='INDEXING' where id=?", (run["id"],))
    tick, calls = [0], []
    monkeypatch.setattr(managed_sync_steps, "time", SimpleNamespace(monotonic=lambda: tick[0]))
    record = SyncRepository.record_progress

    def persisted(self, run_id, phase, value):
        calls.append(value["processed"])
        record(self, run_id, phase, value)

    monkeypatch.setattr(SyncRepository, "record_progress", persisted)
    steps = managed_sync_steps.ManagedSyncSteps(database, None, None, tmp_path)
    for seconds, count in ((0, 32), (1, 64), (16, 96), (16, 100)):
        tick[0] = seconds
        steps._progress(run["id"], "indexing", {"processed": count, "total": 100})
    assert calls == [32, 96, 100]
    assert repo.summary(run["id"])["progress"]["processed"] == 100


def test_health_error_is_machine_code_not_exception_text():
    at = datetime(2026, 10, 26, 12, tzinfo=UTC)
    fresh = at.isoformat()
    value = sync_health(
        {"enabled": 1, "interval_seconds": 3600, "created_at": fresh},
        {
            "id": "synthetic",
            "phase": "INDEXING",
            "updated_at": fresh,
            "error_code": "private-input: http://synthetic",
        },
        None,
        None,
        at,
    )
    assert value["latest_error_code"] == "knowledge_sync_failed"
    assert "private-input" not in json.dumps(value)


def test_activation_does_not_reuse_proof_for_another_target(database, tmp_path, monkeypatch):
    repo, resources, vectors, run_id, resource_id, _ = _prepare_run(database, tmp_path, change=True)
    index = repo.indexes(run_id)
    run = repo.run(run_id)
    resource = resources.store.get("retrieval_resource", resource_id)
    target = {
        "postgres": {"mode": "platform"},
        "qdrant": {"url": "http://other-qdrant:6333", "api_key_ref": ""},
    }
    get = resources.store.get

    def selected(name, identifier):
        value = get(name, identifier)
        if name == "retrieval_revision" and identifier == resource["published_revision_id"]:
            value = {**value, "storage_config_json": json.dumps(target)}
        return value

    monkeypatch.setattr(resources.store, "get", selected)
    monkeypatch.setattr(
        resources,
        "resolve",
        lambda _: SimpleNamespace(
            resource_id=resource_id, revision_id=resource["published_revision_id"]
        ),
    )
    calls = []

    class MissingTarget:
        def check(self, index):
            pass

        def retrieve(self, index, ids):
            calls.append(ids)
            return {}

    @contextmanager
    def content(*args, **kwargs):
        yield SimpleNamespace(records=resources.store, qdrant=MissingTarget())

    monkeypatch.setattr(resources, "content", content)
    activation = ManagedSyncActivation(repo, resources, vectors)
    proofs = activation._verify_indexes(index)
    with pytest.raises(VectorError, match="knowledge_vector_points_missing"):
        activation._verify_resources(run, index, [resource], proofs)
    assert len(calls) == 1
    assert repo.run(run_id)["phase"] == "INDEXING"


def test_health_does_not_load_master_key_or_provider(monkeypatch, tmp_path, capsys):
    from backend.tests.test_knowledge_sync_compose import _stub_schema, _synthetic_file_key_settings

    settings, _ = _synthetic_file_key_settings(tmp_path)
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "load_master_key_settings", lambda *_: pytest.fail("master key read"))
    monkeypatch.setattr(
        cli, "build_api_container", lambda *_a, **_kw: pytest.fail("provider bootstrap")
    )
    _stub_schema(monkeypatch, cli)
    monkeypatch.setattr(
        cli,
        "IncrementalSyncRepository",
        lambda _: SimpleNamespace(
            binding=lambda _: {
                "configuration_revision": 1,
                "enabled": 1,
                "interval_seconds": 3600,
                "next_run_at": None,
            },
            active_run=lambda _: None,
            health=lambda *_: {"healthy": False, "reasons": ["knowledge_sync_success_stale"]},
        ),
    )
    assert cli.main(["--mode", "health", "--binding-code", "synthetic"]) == 1
    assert json.loads(capsys.readouterr().out)["health"]["reasons"] == [
        "knowledge_sync_success_stale"
    ]


def test_sixty_four_document_manifest_query_count_is_per_batch(database, tmp_path, monkeypatch):
    import_rows(database, tmp_path, [export_row(i + 1) for i in range(64)])
    count = ChunkService(ChunkRepository(database)).run(
        knowledge_base_code="synthetic_base", expected_count=64, commit=True
    )["counts"]["chunks"]
    repo = VectorRepository(database)
    index = repo.create(
        "synthetic-bulk-benchmark",
        repo.snapshot(repo.scope("synthetic_base"), DEFAULT_PROFILE.fingerprint, 64, count),
    )
    execute = database.execute
    writes = []

    def counted(sql, params=()):
        if "knowledge.vector_index_item" in sql and (
            sql.startswith("insert into") or "chunk_id in (" in sql
        ):
            writes.append(sql)
        return execute(sql, params)

    monkeypatch.setattr(database, "execute", counted)
    repo.manifest(index)
    assert len(writes) == 2 * ((count + 31) // 32)
    assert len(writes) < count * 2 / 10  # 原实现每块 INSERT+SELECT；至少减少一个数量级。
    print(
        json.dumps(
            {
                "documents": 64,
                "chunks": count,
                "manifest_statements": len(writes),
                "previous_per_row_statements": count * 2,
            }
        )
    )


@pytest.mark.skipif(
    not os.environ.get("KNOWLEDGE_BACKFILL_TEST_POSTGRES_DSN"),
    reason="explicit disposable PostgreSQL DSN not supplied",
)
def test_postgres_reuse_query_plan_uses_partial_hash_index():
    dsn = os.environ["KNOWLEDGE_BACKFILL_TEST_POSTGRES_DSN"]
    assert dsn.startswith("postgresql://postgres@127.0.0.1:") and dsn.endswith(
        "/knowledge_backfill_test"
    )
    db = Database(dsn)
    try:
        Migrator(db, default_migrations_dir(), migrator_build="knowledge-backfill-test").run()
        # 使用临时影子表验证生产索引形状，不创建任何来源或业务正文。
        with db.unit_of_work():
            db.execute(
                "create temporary table reuse_plan (like knowledge.vector_index_item including all)"
            )
            db.execute(
                "insert into reuse_plan(index_id,chunk_id,point_id,embedding_text_hash,state,attempt_count,created_at,updated_at) "
                "select 'synthetic-index',i::text,'point-'||i::text,md5(i::text)||md5(i::text),'INDEXED',0,'now','now' from generate_series(1,50000) i"
            )
            db.execute("analyze reuse_plan")
            plan = db.execute(
                "explain (format json) select chunk_id from reuse_plan where index_id=? and state='INDEXED' and embedding_text_hash=?",
                ("synthetic-index", "0" * 64),
            )
            rendered = json.dumps(plan)
            assert "Index Scan" in rendered or "Bitmap Index Scan" in rendered
            indexes = db.execute(
                "select indexname from pg_indexes where tablename='reuse_plan' "
                "and indexdef like ? and indexdef like ?",
                ("%embedding_text_hash%", "%WHERE%"),
            )
            assert any('"Index Name": "' + row["indexname"] + '"' in rendered for row in indexes)
    finally:
        db.close()
