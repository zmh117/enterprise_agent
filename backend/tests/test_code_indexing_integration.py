"""Opt-in isolated Qdrant acceptance. Never use a deployment collection or endpoint."""

import os

import pytest

from app.modules.knowledge.infrastructure.code_indexing import CodeSnapshotIndexer, CodeIndexStore
from app.modules.knowledge.application.code_search import search_code
from app.modules.knowledge.infrastructure.code_build_repository import CodeBuildRepository
from app.modules.knowledge.infrastructure.code_repository import CodeRepository
from app.modules.knowledge.infrastructure.vector_clients import QdrantClient
from backend.tests.support.knowledge_reranker import SyntheticReranker
from backend.tests.test_code_knowledge import database as database_fixture
from backend.tests.test_code_indexing import candidate
from backend.tests.test_knowledge_vectors import SyntheticEmbedding, VECTOR

database = database_fixture


def test_real_qdrant_snapshot_visibility_and_content_cache(database):
    endpoint = os.environ.get("CODE_KNOWLEDGE_TEST_QDRANT_URL")
    if not endpoint:
        pytest.skip("explicit disposable Qdrant endpoint not supplied")
    qdrant = QdrantClient(endpoint=endpoint)
    embedding = SyntheticEmbedding()
    snapshots = {}
    index = None
    try:
        for revision in (100, 101, 102):
            ids, build, lease = candidate(database, revision)
            indexer = CodeSnapshotIndexer(database, embedding, qdrant)
            assert not indexer.index(build["build_id"], lease)
            assert indexer.index(build["build_id"], lease)
            CodeBuildRepository(database).finish_history(build["build_id"], lease)
            snapshots[revision] = build["snapshot_id"]
        assert embedding.encoded == 3
        index = CodeIndexStore(database).ensure(ids["source_id"])
        for revision, snapshot_id in snapshots.items():
            assert qdrant.code_count(index, snapshot_id) == 2
            points = qdrant.code_search(index, snapshot_id, VECTOR, 10)
            assert len(points) == 2
            assert points[0]["payload"]["snapshot_id"] == snapshot_id
            assert points[0]["payload"]["point_kind"] == "code_knowledge"
            result = search_code(
                store=CodeRepository(database),
                index=index,
                version={"kind": "svn", "revision": revision},
                query="a 为空工单发布",
                top_k=10,
                resource_revision_id="synthetic-publication",
                embedding=embedding,
                qdrant=qdrant,
                reranker=SyntheticReranker(),
                check=lambda: None,
            )
            assert result["documents"][0]["snapshot_id"] == snapshot_id
            assert any(row["evidence"] for row in result["documents"])
    finally:
        if index is not None:
            qdrant.http.request("DELETE", qdrant.path(index))
        qdrant.http.close()
