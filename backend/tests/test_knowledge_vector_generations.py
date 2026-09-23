"""候选代际与跨索引复用；隔离合成 Provider 不连接真实数据。"""

from copy import deepcopy
import json

import pytest

from app.modules.knowledge.application.chunk_service import ChunkService
from app.modules.knowledge.application.vector_service import VectorService
from app.modules.knowledge.domain.chunking import DEFAULT_PROFILE, WORK_ITEM_PROFILE
from app.modules.knowledge.domain.identity import stable_id
from app.modules.knowledge.domain.vector_contract import VectorError, fingerprint
from app.modules.knowledge.domain.vector_points import payload, point_id
from app.modules.knowledge.infrastructure.candidate_corpus import (
    CandidateChunkRepository,
    CandidateVectorRepository,
)
from app.modules.knowledge.infrastructure.chunk_repository import ChunkRepository
from app.modules.knowledge.infrastructure.vector_repository import VectorRepository
from backend.tests.test_knowledge_import import (
    database as database_fixture,
    export_row,
    prepare as prepare_defect,
    run,
)
from backend.tests.test_knowledge_sync_candidates import configured
from backend.tests.test_knowledge_work_item_types import prepare, typed_row
from backend.tests.test_knowledge_vectors import SyntheticEmbedding, SyntheticQdrant

database = database_fixture


class GenerationQdrant(SyntheticQdrant):
    """按实际 collection 隔离点，区别早期仅单索引测试夹具。"""

    def __init__(self):
        super().__init__()
        self.collections = {}

    def check(self, index):
        super().check(index)
        if index["id"] not in self.collections:
            raise VectorError("knowledge_collection_conflict")

    def ensure(self, index):
        SyntheticQdrant.check(self, index)
        self.collections.setdefault(index["id"], {})

    def retrieve(self, index, ids):
        self.check(index)
        collection = self.collections[index["id"]]
        return {key: deepcopy(collection[key]) for key in ids if key in collection}

    def upsert(self, index, points):
        self.check(index)
        self.writes += len(points)
        self.collections[index["id"]].update({point["id"]: deepcopy(point) for point in points})

    def count(self, index):
        self.check(index)
        return len(self.collections[index["id"]])


def build_original(database, tmp_path):
    row = export_row()
    run(database, prepare_defect(tmp_path, [row]))
    chunks = ChunkService(ChunkRepository(database)).run(
        knowledge_base_code="synthetic_base", expected_count=1, commit=True
    )
    repository, embedding, qdrant = (
        VectorRepository(database),
        SyntheticEmbedding(),
        GenerationQdrant(),
    )
    snapshot = repository.snapshot(
        stable_id("base", "synthetic_base"),
        DEFAULT_PROFILE.fingerprint,
        1,
        chunks["counts"]["chunks"],
    )
    VectorService(repository, embedding, qdrant).build("original", snapshot)
    return row, repository.get("original"), embedding, qdrant


def candidate_index(database, tmp_path, row, *, kind="defect"):
    repo, binding, service = configured(database)
    prepared = (
        prepare_defect(tmp_path, [row]) if kind == "defect" else prepare(tmp_path, [row], kind)
    )
    staged = service.stage_exports(binding["id"], (prepared,))
    vectors = CandidateVectorRepository(database, staged["run_id"])
    profile = DEFAULT_PROFILE if kind == "defect" else WORK_ITEM_PROFILE
    base_code = binding["configuration_json"]["base_codes"][kind]
    chunks = ChunkService(
        CandidateChunkRepository(database, staged["run_id"], profile=profile)
    ).run(knowledge_base_code=base_code, expected_count=1, commit=True)
    snapshot = vectors.snapshot(
        stable_id("base", base_code), profile.fingerprint, 1, chunks["counts"]["chunks"]
    )
    return repo, staged, vectors, snapshot


def test_changed_non_embedding_field_reuses_vectors_with_new_revision_payload(database, tmp_path):
    row, previous, embedding, qdrant = build_original(database, tmp_path)
    old_points = deepcopy(qdrant.collections[previous["id"]])
    old_encoded = embedding.encoded
    row[0]["discussion_count"] += 1  # 内容证据变化，Embedding 文本不变。
    row[0]["server_update_stamp"] += 100
    _, staged, vectors, snapshot = candidate_index(database, tmp_path, row)
    code = vectors.index_code(snapshot["knowledge_base_id"])
    built = VectorService(vectors, embedding, qdrant).build(
        code, snapshot, reuse_from_code="original"
    )
    assert built["encoded"] == 0 and built["reused"] == snapshot["expected_chunk_count"]
    assert embedding.encoded == old_encoded
    index = vectors.get(code)
    assert index["sync_run_id"] == staged["run_id"] and index["state"] == "READY"
    assert qdrant.collections[previous["id"]] == old_points
    for record in vectors.rows(snapshot["knowledge_base_id"], snapshot["chunk_profile_hash"]):
        point = qdrant.collections[index["id"]][point_id(index, record)]
        assert point["payload"] == payload(index, record)
        assert point["payload"]["revision_id"] not in {
            p["payload"]["revision_id"] for p in old_points.values()
        }
    replay = VectorService(vectors, embedding, qdrant).build(
        code, snapshot, reuse_from_code="original"
    )
    assert replay["index_id"] == built["index_id"] and replay["encoded"] == 0
    assert len(qdrant.collections) == 2


def test_changed_embedding_text_encodes_only_changed_chunks(database, tmp_path):
    row, previous, embedding, qdrant = build_original(database, tmp_path)
    row[0]["field_values"][0]["value"] = "改变后的合成解决方案"
    row[0]["server_update_stamp"] += 100
    _, _, vectors, snapshot = candidate_index(database, tmp_path, row)
    result = VectorService(vectors, embedding, qdrant).build(
        vectors.index_code(snapshot["knowledge_base_id"]), snapshot, reuse_from_code="original"
    )
    assert result["encoded"] >= 1
    assert result["reused"] >= 1  # 问题片段未变。
    assert VectorRepository(database).get("original")["state"] == "READY"
    assert previous["id"] in qdrant.collections


def test_noop_candidate_cannot_create_a_new_index(database, tmp_path):
    row, _, embedding, qdrant = build_original(database, tmp_path)
    row[0]["server_update_stamp"] += 100
    repo, staged, vectors, snapshot = candidate_index(database, tmp_path, row)
    assert repo.changed_bases(staged["run_id"]) == set()
    before = embedding.encoded
    with pytest.raises(VectorError, match="knowledge_vector_index_conflict"):
        vectors.create(vectors.index_code(snapshot["knowledge_base_id"]), snapshot)
    assert embedding.encoded == before and len(qdrant.collections) == 1
    assert database.execute_one('select count(*) as n from "knowledge.vector_index"')["n"] == 1


@pytest.mark.parametrize("corruption", ["vector", "payload", "count", "profile"])
def test_invalid_old_vector_never_reused_or_damages_old_index(database, tmp_path, corruption):
    row, previous, embedding, qdrant = build_original(database, tmp_path)
    row[0]["discussion_count"] += 1
    row[0]["server_update_stamp"] += 100
    _, _, vectors, snapshot = candidate_index(database, tmp_path, row)
    point = next(iter(qdrant.collections[previous["id"]].values()))
    if corruption == "vector":
        point["vector"] = [float("nan")] * 1024
    elif corruption == "payload":
        point["payload"]["revision_id"] = "wrong"
    elif corruption == "count":
        qdrant.collections[previous["id"]].pop(point["id"])
    else:
        database.execute(
            'update "knowledge.vector_index" set profile_hash=? where id=?',
            ("f" * 64, previous["id"]),
        )
    encoded = embedding.encoded
    with pytest.raises(VectorError):
        VectorService(vectors, embedding, qdrant).build(
            vectors.index_code(snapshot["knowledge_base_id"]), snapshot, reuse_from_code="original"
        )
    assert embedding.encoded == encoded
    assert VectorRepository(database).get("original")["state"] == "READY"


def test_wrong_knowledge_base_cannot_be_reuse_source(database, tmp_path):
    _, _, embedding, qdrant = build_original(database, tmp_path)
    _, _, vectors, snapshot = candidate_index(
        database, tmp_path, typed_row("ticket", index=2), kind="ticket"
    )
    with pytest.raises(VectorError, match="knowledge_vector_reuse_invalid"):
        VectorService(vectors, embedding, qdrant).build(
            vectors.index_code(snapshot["knowledge_base_id"]), snapshot, reuse_from_code="original"
        )


def test_different_model_profile_reencodes_without_reusing_old_values(database, tmp_path):
    row, previous, embedding, qdrant = build_original(database, tmp_path)
    row[0]["discussion_count"] += 1
    row[0]["server_update_stamp"] += 100
    _, _, vectors, snapshot = candidate_index(database, tmp_path, row)
    other_profile = {**previous["profile"], "synthetic_variant": "another-model"}
    database.execute(
        'update "knowledge.vector_index" set profile=?,profile_hash=? where id=?',
        (json.dumps(other_profile), fingerprint(other_profile), previous["id"]),
    )
    result = VectorService(vectors, embedding, qdrant).build(
        vectors.index_code(snapshot["knowledge_base_id"]), snapshot, reuse_from_code="original"
    )
    assert result["encoded"] == snapshot["expected_chunk_count"] and result["reused"] == 0


def test_failure_after_qdrant_write_resumes_same_generation(database, tmp_path, monkeypatch):
    row, previous, embedding, qdrant = build_original(database, tmp_path)
    row[0]["discussion_count"] += 1
    row[0]["server_update_stamp"] += 100
    _, _, vectors, snapshot = candidate_index(database, tmp_path, row)
    old_points = deepcopy(qdrant.collections[previous["id"]])
    write = qdrant.upsert
    failed = False

    def interrupted(index, points):
        nonlocal failed
        write(index, points)
        if not failed:
            failed = True
            raise RuntimeError("synthetic interrupted after confirmed write")

    monkeypatch.setattr(qdrant, "upsert", interrupted)
    service = VectorService(vectors, embedding, qdrant)
    code = vectors.index_code(snapshot["knowledge_base_id"])
    with pytest.raises(VectorError):
        service.build(code, snapshot, reuse_from_code="original")
    assert vectors.get(code)["state"] == "FAILED"
    result = service.build(code, snapshot, reuse_from_code="original")
    assert result["state"] == "READY" and result["encoded"] == 0
    assert len(qdrant.collections) == 2 and qdrant.collections[previous["id"]] == old_points


def test_empty_generation_has_zero_points_and_never_calls_embedding(database, tmp_path):
    _, previous, _, qdrant = build_original(database, tmp_path)
    row = typed_row("ticket")
    row[0]["server_update_stamp"] += 100
    repo, staged, vectors, _ = candidate_index(database, tmp_path, row, kind="ticket")
    empty_base = stable_id("base", "synthetic_base")
    assert empty_base in repo.changed_bases(staged["run_id"])
    snapshot = vectors.snapshot(empty_base, DEFAULT_PROFILE.fingerprint, 0, 0)

    class NoEmbedding:
        def __getattr__(self, key):
            raise AssertionError("empty generations must not call Embedding")

    service = VectorService(vectors, NoEmbedding(), qdrant)
    assert service.preflight(snapshot, benchmark=True)["token_counts"]["total"] == 0
    result = service.build(vectors.index_code(empty_base), snapshot, reuse_from_code="original")
    assert result["state"] == "READY" and result["encoded"] == result["verified"] == 0
    assert qdrant.collections[result["index_id"]] == {}
    assert qdrant.collections[previous["id"]]
