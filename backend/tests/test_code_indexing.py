"""Deterministic index fault tests; no model, SVN, Qdrant server or production data."""

import json
from copy import deepcopy

import httpx
import pytest

from app.modules.knowledge.infrastructure.code_indexing import CodeIndexStore, CodeSnapshotIndexer
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.normalization import digest
from app.modules.knowledge.infrastructure.code_build_repository import CodeBuildRepository
from app.modules.knowledge.infrastructure.code_repository import CodeRepository
from app.modules.knowledge.infrastructure.storage import table
from app.modules.knowledge.infrastructure.vector_clients import QdrantClient
from backend.tests.test_code_knowledge import database as database_fixture, fixture
from backend.tests.test_knowledge_vectors import SyntheticEmbedding, SyntheticQdrant, VECTOR

database = database_fixture


class SnapshotQdrant(SyntheticQdrant):
    def code_count(self, index, snapshot_id):
        return sum(
            1
            for point in self.points.values()
            if point["payload"].get("snapshot_id") == snapshot_id
            and point["payload"]["point_kind"] == "code_knowledge"
        )


def candidate(db, revision, *, business_verified=True, source_config=None):
    repo = CodeRepository(db)
    ids = repo.register(code="indexed-code", base_code="indexed-base", config=source_config or {})
    manifest = {"files": [str(revision)]}
    source = repo.freeze_source(
        ids["source_id"],
        {
            "kind": "svn",
            "repository_uuid": "synthetic",
            "branch_path": "/trunk",
            "revision": revision,
            "manifest_hash": digest(manifest),
        },
        manifest,
    )
    build = repo.new_build(
        ids["source_id"], source, purpose="history", configuration={"version": 1}
    )
    package, _ = fixture(revision, source)
    repo.store_candidate(build["snapshot_id"], package)
    builds = CodeBuildRepository(db)
    lease = builds.claim(build["build_id"])
    for stage in ("QUEUED", "SOURCE_READY", "EXTRACTING", "VALIDATING"):
        builds.advance(build["build_id"], lease, stage)
    db.execute(
        f"update {table(db, 'code_snapshot')} set validation_json=? where id=?",
        (
            json.dumps(
                {
                    "machine_valid": True,
                    "activation_blocked": False,
                    "business_verified": business_verified,
                }
            ),
            build["snapshot_id"],
        ),
    )
    return ids, build, lease


def test_index_reuses_content_hash_but_isolates_every_snapshot(database):
    embedding, qdrant = SyntheticEmbedding(), SnapshotQdrant()
    indexer = CodeSnapshotIndexer(database, embedding, qdrant)
    point_sets = []
    for revision, expected_embeddings in ((100, 2), (101, 3), (102, 3)):
        ids, build, lease = candidate(database, revision)
        assert not indexer.index(build["build_id"], lease)
        assert (
            CodeRepository(database).resolve(
                ids["knowledge_base_id"], {"kind": "svn", "revision": revision}
            )["status"]
            == "BUILD_REQUIRED"
        )
        assert indexer.index(build["build_id"], lease)
        CodeBuildRepository(database).finish_history(build["build_id"], lease)
        assert embedding.encoded == expected_embeddings
        point_sets.append(
            {
                key
                for key, value in qdrant.points.items()
                if value["payload"].get("snapshot_id") == build["snapshot_id"]
            }
        )
    assert all(len(points) == 2 for points in point_sets)
    assert len(set.union(*point_sets)) == 6
    assert CodeRepository(database).binding(ids["source_id"])["active_snapshot_id"] is None


def test_partial_write_recovers_same_candidate_without_duplicate_embedding(database, monkeypatch):
    ids, build, lease = candidate(database, 100)
    embedding, qdrant = SyntheticEmbedding(), SnapshotQdrant()
    indexer = CodeSnapshotIndexer(database, embedding, qdrant)
    original = qdrant.upsert

    def partial(index, points):
        for point in points:
            if point["payload"]["point_kind"] == "code_embedding_cache":
                qdrant.points[point["id"]] = deepcopy(point)
        raise OSError("synthetic interrupted write")

    monkeypatch.setattr(qdrant, "upsert", partial)
    with pytest.raises(OSError):
        indexer.index(build["build_id"], lease)
    assert (
        CodeRepository(database).resolve(
            ids["knowledge_base_id"], {"kind": "svn", "revision": 100}
        )["status"]
        == "BUILD_REQUIRED"
    )
    monkeypatch.setattr(qdrant, "upsert", original)
    assert not indexer.index(build["build_id"], lease)
    assert embedding.encoded == 2
    assert indexer.index(build["build_id"], lease)


def test_index_blocks_unverified_candidate_and_missing_visible_points(database):
    _, build, lease = candidate(database, 100, business_verified=False)
    embedding, qdrant = SyntheticEmbedding(), SnapshotQdrant()
    indexer = CodeSnapshotIndexer(database, embedding, qdrant)
    with pytest.raises(CodeKnowledgeError, match="validation_incomplete"):
        indexer.index(build["build_id"], lease)
    assert not qdrant.points and embedding.encoded == 0
    database.execute(
        f"update {table(database, 'code_snapshot')} set validation_json=? where id=?",
        (
            json.dumps(
                {"machine_valid": True, "activation_blocked": False, "business_verified": True}
            ),
            build["snapshot_id"],
        ),
    )
    assert not indexer.index(build["build_id"], lease)
    point = next(key for key, value in qdrant.points.items() if value["payload"].get("snapshot_id"))
    del qdrant.points[point]
    with pytest.raises(CodeKnowledgeError, match="visibility_incomplete"):
        indexer.index(build["build_id"], lease)
    assert CodeBuildRepository(database).get(build["build_id"])["stage"] == "INDEXING"


def test_qdrant_code_search_enforces_snapshot_and_excludes_cache(database):
    ids, build, _ = candidate(database, 100)
    index = CodeIndexStore(database).ensure(ids["source_id"])
    observed = []

    def handler(request):
        observed.append(json.loads(request.content))
        return httpx.Response(200, json={"result": {"points": []}})

    client = QdrantClient(transport=httpx.MockTransport(handler))
    try:
        assert client.code_search(index, build["snapshot_id"], VECTOR, 20) == []
    finally:
        client.http.close()
    scope = {entry["key"]: entry["match"]["value"] for entry in observed[0]["filter"]["must"]}
    assert scope == {
        "index_id": index["id"],
        "knowledge_base_id": ids["knowledge_base_id"],
        "snapshot_id": build["snapshot_id"],
        "point_kind": "code_knowledge",
    }


def test_same_snapshot_builds_share_ready_content_without_second_extraction(database):
    ids, original, lease = candidate(database, 100)
    repo = CodeRepository(database)
    source_id = CodeBuildRepository(database).get(original["build_id"])["source_snapshot_id"]
    with pytest.raises(CodeKnowledgeError, match="snapshot_build_pending"):
        repo.new_build(ids["source_id"], source_id, purpose="daily", configuration={"version": 1})
    indexer = CodeSnapshotIndexer(database, SyntheticEmbedding(), SnapshotQdrant())
    assert not indexer.index(original["build_id"], lease)
    assert indexer.index(original["build_id"], lease)
    CodeBuildRepository(database).finish_history(original["build_id"], lease)
    daily = repo.new_build(
        ids["source_id"], source_id, purpose="daily", configuration={"version": 1}
    )
    assert daily["snapshot_id"] == original["snapshot_id"]
    builds = CodeBuildRepository(database)
    assert builds.get(daily["build_id"])["stage"] == "READY"
    assert repo.binding(ids["source_id"])["active_snapshot_id"] is None
    current = builds.claim(daily["build_id"])
    builds.activate(daily["build_id"], current)
    assert repo.binding(ids["source_id"])["active_snapshot_id"] == original["snapshot_id"]


def test_activation_failure_preserves_previous_query_target(database, monkeypatch):
    db = database
    repo, builds = CodeRepository(db), CodeBuildRepository(db)
    indexer = CodeSnapshotIndexer(db, SyntheticEmbedding(), SnapshotQdrant())
    snapshots = []
    for revision in (100, 101):
        ids, build, lease = candidate(db, revision)
        assert not indexer.index(build["build_id"], lease)
        assert indexer.index(build["build_id"], lease)
        db.execute(
            f"update {table(db, 'code_build')} set purpose='daily' where id=?", (build["build_id"],)
        )
        if snapshots:
            execute = db.execute

            def fail_after_pointer(sql, params=()):
                result = execute(sql, params)
                if "set active_snapshot_id=" in sql:
                    raise RuntimeError("synthetic activation commit failure")
                return result

            with monkeypatch.context() as patch:
                patch.setattr(db, "execute", fail_after_pointer)
                with pytest.raises(RuntimeError, match="activation commit failure"):
                    builds.activate(build["build_id"], lease)
            assert (
                repo.resolve(ids["knowledge_base_id"], {"kind": "latest_verified"})["snapshot_id"]
                == snapshots[0]
            )
            assert builds.get(build["build_id"])["stage"] == "READY"
        builds.activate(build["build_id"], lease)
        snapshots.append(build["snapshot_id"])
    assert (
        repo.resolve(ids["knowledge_base_id"], {"kind": "latest_verified"})["snapshot_id"]
        == snapshots[1]
    )
