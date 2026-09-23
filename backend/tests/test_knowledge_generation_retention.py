"""派生代际清理与容量门禁，仅使用合成存储和合成 HTTP。"""

from copy import deepcopy
from datetime import datetime, timedelta, UTC
from types import SimpleNamespace

import httpx
import pytest

from app.modules.knowledge.application.generation_retention import GenerationRetention
from app.modules.knowledge.application.sync_service import KnowledgeSyncService
from app.modules.knowledge.application.chunk_service import ChunkService
from app.modules.knowledge.application.vector_service import VectorService
from app.modules.knowledge.domain.chunking import WORK_ITEM_PROFILE
from app.modules.knowledge.domain.identity import stable_id, now
from app.modules.knowledge.domain.vector_contract import VectorError
from app.modules.knowledge.infrastructure.candidate_corpus import (
    CandidateChunkRepository,
    CandidateVectorRepository,
)
from app.modules.knowledge.infrastructure.generation_repository import GenerationRepository
from app.modules.knowledge.infrastructure.storage import insert
from app.modules.knowledge.infrastructure.vector_clients import QdrantClient
from app.modules.knowledge.infrastructure.vector_capacity import VectorCapacity
from backend.tests.test_knowledge_import import database as database_fixture
from backend.tests.test_knowledge_sync_candidates import configured
from backend.tests.test_knowledge_work_item_types import prepare, typed_row
from backend.tests.test_knowledge_vector_generations import (
    GenerationQdrant,
    build_original,
    candidate_index,
)
from backend.tests.test_knowledge_vectors import SyntheticEmbedding

database = database_fixture


class RetentionQdrant(GenerationQdrant):
    def __init__(self):
        super().__init__()
        self.deleted = []

    def delete_owned(self, index):
        assert index["sync_run_id"]
        self.collections.pop(index["id"], None)
        self.deleted.append(index["id"])


def generations(database, tmp_path, *, count=4):
    repo, binding, _ = configured(database)
    qdrant, embedding, indexes = RetentionQdrant(), SyntheticEmbedding(), []
    for number in range(count):
        row = typed_row(index=1, body=f"合成版本 {number}")
        row[0]["server_update_stamp"] += number * 100
        result = KnowledgeSyncService(repo).stage_exports(
            binding["id"], (prepare(tmp_path, [row], "requirement"),)
        )
        chunk_repo = CandidateChunkRepository(database, result["run_id"], profile=WORK_ITEM_PROFILE)
        chunks = ChunkService(chunk_repo).run(
            knowledge_base_code="synthetic_requirements", expected_count=1, commit=True
        )
        vectors = CandidateVectorRepository(database, result["run_id"])
        snapshot = vectors.snapshot(
            stable_id("base", "synthetic_requirements"),
            WORK_ITEM_PROFILE.fingerprint,
            1,
            chunks["counts"]["chunks"],
        )
        code = vectors.index_code(snapshot["knowledge_base_id"])
        VectorService(vectors, embedding, qdrant).build(code, snapshot)
        indexes.append(vectors.get(code))
        # 合成清理夹具只准备成功代际事实；不冒充内容激活的完整验收。
        database.execute(
            "update \"knowledge.sync_run\" set phase='ACTIVATED',active=0,activated_watermark=? where id=?",
            (
                (datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=number)).isoformat(),
                result["run_id"],
            ),
        )
    return repo, binding, qdrant, indexes


def test_retention_waits_ten_minutes_and_keeps_latest_two_and_all_source_rows(database, tmp_path):
    _, _, qdrant, indexes = generations(database, tmp_path)
    before = database.execute('select * from "knowledge.document_revision" order by id')
    service = GenerationRetention(GenerationRepository(database), qdrant)
    assert service.run(timestamp="2026-01-02T00:00:00+00:00")["retired"] == 0
    assert service.run(timestamp="2026-01-02T00:09:59+00:00")["retired"] == 0
    result = service.run(timestamp="2026-01-02T00:10:00+00:00")
    assert result["retired"] == 2
    assert set(qdrant.deleted) == {item["id"] for item in indexes[:2]}
    assert set(qdrant.collections) == {item["id"] for item in indexes[-2:]}
    assert database.execute('select * from "knowledge.document_revision" order by id') == before
    assert service.run(timestamp="2026-01-02T01:00:00+00:00")["retired"] == 0


def test_recheck_protects_new_draft_reference_and_resets_grace(database, tmp_path):
    _, _, qdrant, indexes = generations(database, tmp_path, count=3)
    store = GenerationRepository(database)
    service = GenerationRetention(store, qdrant)
    service.run(timestamp="2026-01-02T00:00:00+00:00")
    index = indexes[0]
    insert(
        database,
        "retrieval_resource",
        {
            "id": "synthetic_resource",
            "knowledge_base_id": index["knowledge_base_id"],
            "code": "synthetic_resource",
            "name": "合成资源",
            "created_by": "synthetic_admin",
            "created_at": now(),
            "updated_at": now(),
        },
    )
    insert(
        database,
        "retrieval_revision",
        {
            "id": "synthetic_revision",
            "resource_id": "synthetic_resource",
            "revision": 1,
            "index_id": index["id"],
            "profile_hash": index["profile_hash"],
            "corpus_hash": index["corpus_hash"],
            "config_hash": "a" * 64,
            "created_by": "synthetic_admin",
            "created_at": now(),
        },
    )
    database.execute(
        "update \"knowledge.retrieval_resource\" set draft_revision_id='synthetic_revision'"
    )
    assert service.run(timestamp="2026-01-02T00:20:00+00:00")["retired"] == 0
    assert (
        database.execute_one(
            'select unreferenced_at from "knowledge.vector_index" where id=?', (index["id"],)
        )["unreferenced_at"]
        is None
    )


def test_active_run_and_manual_index_are_never_cleaned(database, tmp_path):
    _, previous, _, original_qdrant = build_original(database, tmp_path)
    repo, binding, service = configured(database)
    row = typed_row(index=2)
    staged = service.stage_exports(binding["id"], (prepare(tmp_path, [row], "requirement"),))
    # 显式没有同步归属的原索引不出现在 GC 候选中。
    assert list(GenerationRepository(database).candidates()) == []
    assert previous["id"] in original_qdrant.collections
    assert repo.run(staged["run_id"])["active"] == 1


def test_active_source_run_protects_all_owned_generations(database, tmp_path):
    _, _, qdrant, indexes = generations(database, tmp_path, count=3)
    database.execute(
        "update \"knowledge.sync_run\" set phase='INDEXING',active=1,activated_watermark=NULL where id=?",
        (indexes[-1]["sync_run_id"],),
    )
    service = GenerationRetention(GenerationRepository(database), qdrant)
    assert service.run(timestamp="2026-01-02T00:00:00+00:00")["retired"] == 0
    assert service.run(timestamp="2026-01-03T00:00:00+00:00")["retired"] == 0
    assert len(qdrant.collections) == 3


def test_capacity_low_pauses_build_without_removing_old_points(database, tmp_path, monkeypatch):
    row, previous, embedding, qdrant = build_original(database, tmp_path)
    before = deepcopy(qdrant.collections)
    row[0]["discussion_count"] += 1
    row[0]["server_update_stamp"] += 100
    _, _, vectors, snapshot = candidate_index(database, tmp_path, row)
    monkeypatch.setattr(
        "app.modules.knowledge.infrastructure.vector_capacity.shutil.disk_usage",
        lambda path: SimpleNamespace(free=1024),
    )
    capacity = VectorCapacity(tmp_path)
    code = vectors.index_code(snapshot["knowledge_base_id"])
    with pytest.raises(VectorError, match="knowledge_vector_capacity_low"):
        VectorService(vectors, embedding, qdrant).build(
            code, snapshot, capacity_check=capacity.check
        )
    assert vectors.get(code)["state"] == "FAILED"
    assert qdrant.collections == before and previous["id"] in qdrant.collections


def test_qdrant_delete_requires_sync_owner_and_matching_metadata():
    from app.modules.knowledge.domain.identity import stable_id
    import uuid

    run_id = stable_id("sync-run", "synthetic")
    index_id = stable_id("vector-index", "synthetic")
    index = {
        "id": index_id,
        "collection_name": "knowledge_" + uuid.UUID(index_id).hex,
        "sync_run_id": run_id,
        "profile_hash": "a" * 64,
        "corpus_hash": "b" * 64,
    }
    calls = []
    metadata = {
        "owner": "enterprise-agent-knowledge/v1",
        "index_id": index_id,
        "profile_hash": "a" * 64,
        "corpus_hash": "b" * 64,
        "sync_run_id": "wrong",
    }

    def respond(request):
        calls.append(request.method)
        return httpx.Response(
            200,
            json={
                "result": {
                    "config": {
                        "params": {"vectors": {"size": 1024, "distance": "Cosine"}},
                        "metadata": metadata,
                    }
                }
            }
            if request.method == "GET"
            else {"result": True},
        )

    client = QdrantClient(transport=httpx.MockTransport(respond))
    try:
        with pytest.raises(VectorError, match="knowledge_vector_retention_owner_invalid"):
            client.delete_owned({**index, "sync_run_id": None})
        with pytest.raises(VectorError, match="knowledge_collection_conflict"):
            client.delete_owned(index)
        assert "DELETE" not in calls
        metadata["sync_run_id"] = run_id
        client.delete_owned(index)
        assert calls[-1] == "DELETE"
    finally:
        client.http.close()
