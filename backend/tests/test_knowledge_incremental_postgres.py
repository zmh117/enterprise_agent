"""隔离 PostgreSQL + Qdrant 实机协议；文档和 Embedding 仍为合成输入。"""

import os

import httpx
import pytest

from app.modules.knowledge.application.candidates import current_documents
from app.modules.knowledge.domain.vector_points import point_id
from app.modules.knowledge.infrastructure.vector_clients import QdrantClient
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import Migrator
from backend.tests.test_knowledge_incremental_sync import Harness, revised, same_stamp_revised


@pytest.fixture
def incremental_services():
    dsn = os.environ["KNOWLEDGE_INCREMENTAL_TEST_POSTGRES_DSN"]
    target = os.environ["KNOWLEDGE_INCREMENTAL_TEST_QDRANT_URL"]
    assert httpx.URL(target).host == "127.0.0.1"
    assert "@127.0.0.1:" in dsn and dsn.endswith("/incremental_test")
    database = Database(dsn)
    delegate = httpx.HTTPTransport()

    def route(request):
        request.url = httpx.URL(target).copy_with(path=request.url.path, query=request.url.query)
        return delegate.handle_request(request)

    qdrant = QdrantClient(transport=httpx.MockTransport(route))
    try:
        Migrator(database, default_migrations_dir(), migrator_build="incremental-isolated").run()
        yield database, qdrant
    finally:
        qdrant.http.close()
        delegate.close()
        database.close()


@pytest.mark.skipif(
    not os.getenv("KNOWLEDGE_INCREMENTAL_TEST_POSTGRES_DSN"),
    reason="requires dedicated incremental test containers",
)
def test_postgres_qdrant_incremental_replay_and_visibility(
    tmp_path, monkeypatch, incremental_services
):
    database, qdrant = incremental_services
    h = Harness(database, tmp_path)
    h.qdrant = h.steps.writer.qdrant = qdrant
    records = h.records(1, 2)
    h.stage(records)
    assert h.run()["content_status"] == "COMPLETED"
    index = h.index()
    rows = list(h.vectors.rows(index["knowledge_base_id"], index["chunk_profile_hash"]))
    before = qdrant.retrieve(index, [point_id(index, row) for row in rows])
    original = qdrant.set_searchable

    def crash(*args):
        original(*args)
        raise RuntimeError("synthetic crash after payload commit")

    h.stage([revised(records[0])])
    monkeypatch.setattr(qdrant, "set_searchable", crash)
    with pytest.raises(RuntimeError, match="synthetic crash"):
        h.run()
    encoded = h.embedding.encoded
    monkeypatch.setattr(qdrant, "set_searchable", original)
    assert h.run()["content_status"] == "COMPLETED"
    assert h.embedding.encoded == encoded
    assert h.index()["id"] == index["id"]
    assert qdrant.count(index) == h.index()["expected_chunk_count"]
    hits = qdrant.hybrid_search(index, [1.0] + [0.0] * 1023, "合成缺陷", 200)
    assert len(current_documents(h.vectors, h.index(), hits)) == 2
    after = qdrant.retrieve(index, list(before))
    assert after and len(after) < len(before)
    assert all(point == before[key] for key, point in after.items())
    h.stage(h.records(3))
    apply = h.steps.repo.apply_document
    monkeypatch.setattr(
        h.steps.repo,
        "apply_document",
        lambda *_: (_ for _ in ()).throw(RuntimeError("pending")),
    )
    with pytest.raises(RuntimeError, match="pending"):
        h.run()
    hits = qdrant.hybrid_search(index, [1.0] + [0.0] * 1023, "合成缺陷", 200)
    assert all(point["payload"]["searchable"] is True for point in hits)
    assert len(current_documents(h.vectors, h.index(), hits)) == 2
    monkeypatch.setattr(h.steps.repo, "apply_document", apply)
    assert h.run()["documents"]["completed"] == 1
    assert h.index()["expected_document_count"] == 3

    _check_same_stamp(h)


def _check_same_stamp(h):
    changed = same_stamp_revised(h.records(3)[0])
    run_id = h.stage([changed])
    events = []
    h.steps.emit = lambda event, value: events.append((event, value))
    assert h.run()["counts"] == {"revised": 1}
    assert len(events) == 1 and events[0][1]["phase"] == "DONE"
    candidate = next(h.repo.candidates(run_id))
    before = h.repo.revision(candidate["baseline_revision_id"])
    after = h.repo.revision(candidate["candidate_revision_id"])
    assert before["source_update_stamp_raw"] == after["source_update_stamp_raw"]
    assert before["title"] != after["title"]
    encoded = h.embedding.encoded
    h.stage([changed])
    assert h.run()["counts"] == {"unchanged": 1}
    assert h.embedding.encoded == encoded
    assert h.qdrant.count(h.index()) == h.index()["expected_chunk_count"]
