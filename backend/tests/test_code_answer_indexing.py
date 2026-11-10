"""Real content transactions and synthetic vector I/O; no model calls or production data."""

import json

import pytest

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.infrastructure.code_index_executor import CodeIndexExecutor
from app.modules.knowledge.infrastructure.code_index_store import CodeIndexStore
from app.modules.knowledge.infrastructure.code_answer_reader import CodeAnswerReader
from backend.tests.support.code_answers import CODE_INDEX_ID
from backend.tests.test_code_answer_store import workspace as workspace_fixture, prepared, save
from backend.tests.test_knowledge_vectors import SyntheticEmbedding
from backend.tests.test_knowledge_incremental_sync import IncrementalMemory

workspace = workspace_fixture


def test_background_worker_discovers_and_indexes_queued_answer(indexing, monkeypatch, tmp_path):
    from threading import Event
    from types import SimpleNamespace
    from app.cli import code_answer_index_worker as worker

    workspace, store, _, embedding, qdrant = indexing
    ctx, analysis, result = prepared(workspace)
    saved = save(workspace[1], ctx, analysis, result)
    work = task(store, saved["revision_id"])
    stop = Event()
    monkeypatch.setattr(worker, "Database", lambda *a, **kw: store.db)
    for client in (embedding, qdrant):
        client.http = SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(worker, "EmbeddingClient", lambda: embedding)
    monkeypatch.setattr(worker, "QdrantClient", lambda: qdrant)
    monkeypatch.setenv("DATABASE_DSN", "synthetic-worker-database")
    monkeypatch.setenv("CODE_CHECKOUT_ROOT", str(tmp_path))
    monkeypatch.setattr(stop, "wait", lambda timeout: stop.set())
    with monkeypatch.context() as lifecycle:
        lifecycle.setattr(store.db, "close", lambda: None)
        worker._loop(stop)
    done = store.row("code_index_task", work["id"])
    assert done["state"] == "succeeded", done["error_code"]
    assert done["ready_at"] and qdrant.points


class CodeMemory(IncrementalMemory):
    def delete_code_generations(self, index, task_id, maximum):
        self.delete_points(
            index,
            [
                key
                for key, point in self.points.items()
                if point["payload"].get("index_task_id") == task_id
                and point["payload"]["index_generation"] <= maximum
            ],
        )


@pytest.fixture
def indexing(workspace, tmp_path):
    runtime, answers, source, checkout = workspace
    store = CodeIndexStore(runtime.database)
    embedding, qdrant = SyntheticEmbedding(), CodeMemory()
    executor = CodeIndexExecutor(
        store, embedding, qdrant, owner="index-worker", execution_root=tmp_path.resolve()
    )
    return workspace, store, executor, embedding, qdrant


def task(store, revision, action="upsert"):
    return store.db.execute_one(
        f"SELECT * FROM {store.t('code_index_task')} WHERE revision_id=? AND action=?",
        (revision, action),
    )


def test_chunks_carry_full_conditions_and_no_duplicate_encoding(indexing):
    workspace, store, executor, embedding, qdrant = indexing
    ctx, analysis, result = prepared(workspace)
    result["answer"] = "校验开启且字段 A 为空，拒绝发布；其他条件仍需满足。\n" * 100
    result["conditions"] = {"switch": True, "details": "必须全部满足" * 200}
    saved = save(workspace[1], ctx, analysis, result)
    work = task(store, saved["revision_id"])
    assert executor.execute(work["id"])
    done = store.row("code_index_task", work["id"])
    assert done["state"] == "succeeded", done["error_code"]
    assert done["expected_chunks"] > 1 and done["ready_at"]
    chunks = store.db.execute(
        f"SELECT context_json,embedding_text FROM {store.t('document_chunk')}"
    )
    assert all(json.loads(c["context_json"])["conditions"] == result["conditions"] for c in chunks)
    assert all("SVN r100" in c["embedding_text"] for c in chunks)
    assert all(
        p["payload"]["svn_revision"] == 100 and p["payload"]["searchable"]
        for p in qdrant.points.values()
    )
    assert not executor.execute(work["id"])
    encoded = embedding.encoded
    ctx, analysis, same = prepared(workspace, "same")
    same.update(answer=result["answer"], conditions=result["conditions"])
    assert save(workspace[1], ctx, analysis, same)["revision_id"] == saved["revision_id"]
    assert embedding.encoded == encoded


def test_lost_vector_response_retries_without_encoding_again(indexing, monkeypatch):
    workspace, store, executor, embedding, qdrant = indexing
    ctx, analysis, result = prepared(workspace)
    saved = save(workspace[1], ctx, analysis, result)
    work = task(store, saved["revision_id"])
    original = qdrant.upsert

    def response_lost(index, points):
        original(index, points)
        raise TimeoutError

    monkeypatch.setattr(qdrant, "upsert", response_lost)
    executor.execute(work["id"])
    failed = store.row("code_index_task", work["id"])
    assert failed["state"] == "failed" and failed["ready_at"] is None
    assert all(p["payload"]["searchable"] is False for p in qdrant.points.values())
    monkeypatch.setattr(qdrant, "upsert", original)
    with store.db.unit_of_work():
        index, _, _ = store._current(failed)
        store.enqueue(index, work["document_id"], work["revision_id"], "upsert", restart=True)
    encoded = embedding.encoded
    executor.execute(work["id"])
    assert store.row("code_index_task", work["id"])["state"] == "succeeded"
    assert embedding.encoded == encoded


def test_expired_claim_is_not_takeover_and_corrected_answer_is_not_visible(indexing):
    workspace, store, executor, _, _ = indexing
    ctx, analysis, result = prepared(workspace)
    first = save(workspace[1], ctx, analysis, result)
    work = task(store, first["revision_id"])
    owned = store.claim(work["id"], "previous-owner")
    store.db.execute(
        f"UPDATE {store.t('code_index_task')} SET lease_until='2000-01-01T00:00:00+00:00'"
    )
    assert store.claim(work["id"], "replacement") is None
    ctx, analysis, corrected = prepared(workspace, "correction")
    corrected.update(answer="A 字段不需要填写。", expected_current_revision_id=first["revision_id"])
    second = save(workspace[1], ctx, analysis, corrected)
    next_work = task(store, second["revision_id"])
    assert executor.execute(next_work["id"]) is False
    with pytest.raises(CodeKnowledgeError, match="CODE_INDEX_INTENT_CHANGED"):
        store.active(owned)
    store.stopped(owned, "CODE_INDEX_INTENT_CHANGED")
    assert executor.execute(next_work["id"])
    selected = CodeAnswerReader(store.db).select_version(
        base_id=ctx.knowledge_base_id,
        environment_id=ctx.environment_id,
        source_id=ctx.source_id,
        index_id=CODE_INDEX_ID,
        revision=100,
        mode="exact",
        allowed_paths=["set_server"],
    )
    assert selected["document_ids"] == [next_work["document_id"]]
    assert store.row("code_index_task", work["id"])["ready_at"] is None


def test_pause_then_remove_and_reinclude_same_revision(indexing):
    workspace, store, executor, embedding, qdrant = indexing
    ctx, analysis, result = prepared(workspace)
    first = save(workspace[1], ctx, analysis, result)
    work = task(store, first["revision_id"])
    store.db.execute(f"UPDATE {store.t('knowledge_base')} SET code_indexing_paused=1")
    assert not executor.execute(work["id"]) and embedding.encoded == 0
    store.db.execute(f"UPDATE {store.t('knowledge_base')} SET code_indexing_paused=0")
    assert executor.execute(work["id"])
    with store.db.unit_of_work():
        index, _, _ = store._current(work)
        store.db.execute(f"UPDATE {store.t('knowledge_base_document')} SET state='removed'")
        store.enqueue(index, work["document_id"], work["revision_id"], "remove")
    assert executor.execute(task(store, first["revision_id"], "remove")["id"])
    assert not qdrant.points
    ctx, analysis, result = prepared(workspace, "reinclude")
    assert save(workspace[1], ctx, analysis, result)["revision_id"] == first["revision_id"]
    restarted = store.row("code_index_task", work["id"])
    assert restarted["state"] == "queued" and restarted["ready_at"] is None
    assert executor.execute(work["id"])
    assert qdrant.points and store.row("code_index_task", work["id"])["state"] == "succeeded"


def test_late_upsert_cannot_replace_new_ready_generation(indexing, monkeypatch):
    from copy import deepcopy
    from backend.tests.test_code_answer_search import search

    workspace, store, executor, _, qdrant = indexing
    ctx, analysis, result = prepared(workspace)
    saved = save(workspace[1], ctx, analysis, result)
    work = task(store, saved["revision_id"])
    original = qdrant.upsert
    delayed = []

    def timeout(index, points):
        delayed.append((deepcopy(index), deepcopy(points)))
        raise TimeoutError

    monkeypatch.setattr(qdrant, "upsert", timeout)
    executor.execute(work["id"])
    monkeypatch.setattr(qdrant, "upsert", original)
    with store.db.unit_of_work():
        index, _, _ = store._current(work)
        store.enqueue(index, work["document_id"], work["revision_id"], "upsert", restart=True)
    executor.execute(work["id"])
    generation = store.row("code_index_task", work["id"])["claim_version"]
    # The server can receive the timed-out write after the new claim is ready.
    for index, points in delayed:
        original(index, points)
    assert any(p["payload"]["index_generation"] < generation for p in qdrant.points.values())
    assert len(search(indexing)["documents"]) == 1
    reader = CodeAnswerReader(store.db)
    old = delayed[0][1][0]
    assert (
        reader.chunk(
            index=index, point=old, allowed_paths=["set_server"], environment_id=ctx.environment_id
        )
        is None
    )


def test_late_remove_cannot_delete_reincluded_generation(indexing, monkeypatch):
    from backend.tests.test_code_answer_search import search

    workspace, store, executor, _, qdrant = indexing
    ctx, analysis, result = prepared(workspace)
    saved = save(workspace[1], ctx, analysis, result)
    work = task(store, saved["revision_id"])
    executor.execute(work["id"])
    original = qdrant.delete_code_generations
    delayed = []

    def timeout(index, identifier, maximum):
        delayed.append((index, identifier, maximum))
        raise TimeoutError

    with store.db.unit_of_work():
        index, _, _ = store._current(work)
        store.db.execute(f"UPDATE {store.t('knowledge_base_document')} SET state='removed'")
        store.enqueue(index, work["document_id"], work["revision_id"], "remove")
    monkeypatch.setattr(qdrant, "delete_code_generations", timeout)
    executor.execute(task(store, saved["revision_id"], "remove")["id"])
    monkeypatch.setattr(qdrant, "delete_code_generations", original)
    ctx, analysis, result = prepared(workspace, "reinclude")
    save(workspace[1], ctx, analysis, result)
    executor.execute(work["id"])
    for args in delayed:
        original(*args)
    assert len(search(indexing)["documents"]) == 1


def test_index_worker_recovery_requires_local_stop_proof(indexing):
    from app.cli.code_answer_index_worker import recover_stopped_indexing
    from app.modules.knowledge.infrastructure.code_executor_lock import execution_lock

    workspace, store, executor, _, _ = indexing
    ctx, analysis, result = prepared(workspace)
    saved = save(workspace[1], ctx, analysis, result)
    work = task(store, saved["revision_id"])
    owned = store.claim(work["id"], "previous-worker")
    store.db.execute(
        f"UPDATE {store.t('code_index_task')} SET lease_until='2000-01-01T00:00:00+00:00'"
    )
    recover_stopped_indexing(store, executor.execution_root)
    assert store.row("code_index_task", work["id"])["state"] == "running"
    with execution_lock(executor.execution_root, "index", work["id"]) as proof:
        proof.bind(owned)
        recover_stopped_indexing(store, executor.execution_root)
        assert store.row("code_index_task", work["id"])["state"] == "running"
    recover_stopped_indexing(store, executor.execution_root)
    assert store.row("code_index_task", work["id"])["error_code"] == "CODE_INDEX_WORKER_STOPPED"
