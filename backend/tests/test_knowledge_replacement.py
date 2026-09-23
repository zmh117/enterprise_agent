"""显式测试快照替换，合成数据验证原子切换与已有授权边界。"""

from copy import deepcopy
import os

import pytest

from app.modules.audit.application.audit_service import AuditService
from app.modules.job.infrastructure.repositories import AuditRepository
from app.modules.knowledge.application.chunk_service import ChunkService
from app.modules.knowledge.application.resource_service import KnowledgeResourceService
from app.modules.knowledge.application.source_service import KnowledgeAdministration
from app.modules.knowledge.application.sync_service import KnowledgeSyncService
from app.modules.knowledge.application.test_snapshot_activation import TestSnapshotActivation
from app.modules.knowledge.application.vector_service import VectorService
from app.modules.knowledge.domain.chunking import DEFAULT_PROFILE, KEEP_IDS_PROFILE
from app.modules.knowledge.domain.hybrid import hybrid_index
from app.modules.knowledge.domain.identity import stable_id
from app.modules.knowledge.domain.normalization import ExportValidationError
from app.modules.knowledge.infrastructure.candidate_corpus import (
    CandidateChunkRepository,
    CandidateVectorRepository,
)
from app.modules.knowledge.infrastructure.chunk_repository import ChunkRepository
from app.modules.knowledge.infrastructure.governance_repository import GovernanceStore
from app.modules.knowledge.infrastructure.replacement_repository import ReplacementRepository
from app.modules.knowledge.infrastructure.vector_repository import VectorRepository
from app.shared.exceptions import PermissionDenied
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import Migrator
from backend.tests.test_knowledge_governance import SyntheticPermission
from backend.tests.test_knowledge_import import (
    database as database_fixture,
    export_row,
    prepare as old_prepare,
    run as old_import,
)
from backend.tests.test_knowledge_keep_ids import dataset, prepare
from backend.tests.test_knowledge_vectors import SyntheticEmbedding, SyntheticQdrant
from backend.tests.test_schema_migration_postgres_integration import (
    postgres_database_dsn as postgres_fixture,
)

database = database_fixture
postgres_database_dsn = postgres_fixture
ACTOR = "synthetic_admin"


class HybridMemory(SyntheticQdrant):
    def upsert(self, index, points):
        if hybrid_index(index):
            points = [{**p, "sparse_vector": {"indices": [1], "values": [1.0]}} for p in points]
        super().upsert(index, points)

    def count(self, index):
        return sum(p["payload"]["index_id"] == index["id"] for p in self.points.values())


@pytest.fixture
def replacement(database, tmp_path):
    old_import(database, old_prepare(tmp_path, [export_row()]))
    chunks = ChunkService(ChunkRepository(database)).run(
        knowledge_base_code="synthetic_base", expected_count=1, commit=True
    )
    vectors = VectorRepository(database)
    embedding, qdrant = SyntheticEmbedding(), HybridMemory()
    base_id = stable_id("base", "synthetic_base")
    vector = VectorService(vectors, embedding, qdrant)
    snapshot = vectors.snapshot(base_id, DEFAULT_PROFILE.fingerprint, 1, chunks["counts"]["chunks"])
    vector.build("synthetic-old", snapshot)
    permission = SyntheticPermission()
    resources = KnowledgeResourceService(
        KnowledgeAdministration(
            GovernanceStore(database), permission, AuditService(AuditRepository(database))
        ),
        vectors,
        embedding=embedding,
        qdrant=qdrant,
    )
    resource = resources.create(
        actor_id=ACTOR, knowledge_base_id=base_id, code="synthetic", name="合成测试"
    )
    saved = resources.save_draft(
        actor_id=ACTOR,
        resource_id=resource["id"],
        expected_revision=resource["revision"],
        index_id=vectors.get("synthetic-old")["id"],
    )
    verified = resources.verify_draft(
        actor_id=ACTOR, resource_id=resource["id"], expected_revision=saved["revision"]
    )
    resources.publish(
        actor_id=ACTOR, resource_id=resource["id"], expected_revision=verified["revision"]
    )
    repo = ReplacementRepository(database)
    codes = {
        "defect": "synthetic_base",
        "ticket": "synthetic_tickets",
        "requirement": "synthetic_requirements",
    }
    binding = repo.configure(
        code="synthetic_replace",
        source_code="synthetic_source",
        configuration={"base_codes": codes, "resource_ids": [resource["id"]]},
        expected_revision=0,
    )
    root = tmp_path / "new"
    dataset(root)
    exports = prepare(root)
    result = KnowledgeSyncService(repo).stage_test_replacement(binding["id"], exports)
    run_id = result["run_id"]
    repo.advance(run_id, expected_phase="STAGED", phase="CHUNKING")
    candidates = CandidateVectorRepository(database, run_id)
    for export in exports:
        code = codes[export.manifest["document_kind"]]
        n = export.manifest["record_count"]
        count = ChunkService(
            CandidateChunkRepository(database, run_id, profile=KEEP_IDS_PROFILE)
        ).run(knowledge_base_code=code, expected_count=n, commit=True)["counts"]["chunks"]
        bid = stable_id("base", code)
        VectorService(candidates, embedding, qdrant).build(
            candidates.index_code(bid),
            candidates.snapshot(bid, KEEP_IDS_PROFILE.fingerprint, n, count),
        )
    repo.advance(run_id, expected_phase="CHUNKING", phase="INDEXING")
    return database, repo, resources, candidates, run_id, resource["id"], permission


def test_atomic_replacement_preserves_publication_history_and_authorization(replacement):
    db, repo, resources, candidates, run_id, resource_id, _ = replacement
    before = deepcopy(resources.store.get("retrieval_resource", resource_id))
    previous = resources.store.get("retrieval_revision", before["published_revision_id"])
    activation = TestSnapshotActivation(repo, resources, candidates)
    result = activation.run(run_id, actor_id=ACTOR)
    assert result["phase"] == "ACTIVATED" and repo.run(run_id)["active"] == 0
    assert resources.store.get("retrieval_revision", previous["id"]) == previous
    current = resources.store.get("retrieval_resource", resource_id)
    assert current["revision"] == before["revision"] + 1
    assert current["state_revision"] == before["state_revision"]
    assert (
        resources.store.get("retrieval_revision", current["published_revision_id"])[
            "configuration_version"
        ]
        == 4
    )
    assert resources.resolve(current["knowledge_base_id"])
    assert (
        db.execute_one(
            "select count(*) as n from \"knowledge.knowledge_base_document\" where state='included'"
        )["n"]
        == 4
    )
    assert (
        db.execute_one(
            "select count(*) as n from \"knowledge.knowledge_base_document\" where state='removed'"
        )["n"]
        == 1
    )
    assert db.execute_one('select count(*) as n from "knowledge.retrieval_resource"')["n"] == 1
    assert db.execute("select * from rbac_role_application_knowledge_base") == []
    assert repo.binding(repo.run(run_id)["binding_id"])["enabled"] == 0
    assert activation.run(run_id, actor_id=ACTOR) == result
    assert resources.store.get("retrieval_resource", resource_id) == current


def test_replacement_publication_failure_rolls_back_content_and_members(replacement, monkeypatch):
    db, repo, resources, candidates, run_id, resource_id, _ = replacement
    before_docs = db.execute('select * from "knowledge.document" order by id')
    before_members = db.execute(
        'select * from "knowledge.knowledge_base_document" order by document_id'
    )
    before_resource = resources.store.get("retrieval_resource", resource_id)

    def fail(*args):
        raise RuntimeError("synthetic interruption")

    monkeypatch.setattr(resources.store, "publish", fail)
    with pytest.raises(RuntimeError, match="synthetic interruption"):
        TestSnapshotActivation(repo, resources, candidates).run(run_id, actor_id=ACTOR)
    assert db.execute('select * from "knowledge.document" order by id') == before_docs
    assert (
        db.execute('select * from "knowledge.knowledge_base_document" order by document_id')
        == before_members
    )
    assert resources.store.get("retrieval_resource", resource_id) == before_resource
    assert repo.run(run_id)["phase"] == "VERIFIED"


@pytest.mark.parametrize("conflict", ["permission", "draft", "membership", "extra_resource"])
def test_replacement_conflicts_do_not_activate(replacement, conflict):
    db, repo, resources, candidates, run_id, resource_id, permission = replacement
    if conflict == "permission":
        permission.allowed = False
    elif conflict == "draft":
        old = resources.store.get("retrieval_resource", resource_id)
        resources.save_draft(
            actor_id=ACTOR,
            resource_id=resource_id,
            expected_revision=old["revision"],
            index_id=resources.vectors.get("synthetic-old")["id"],
        )
    elif conflict == "membership":
        db.execute("update \"knowledge.knowledge_base_document\" set state='removed'")
    else:
        db.execute("update \"knowledge.retrieval_resource\" set status='disabled'")
    before = db.execute('select * from "knowledge.document" order by id')
    with pytest.raises((ExportValidationError, PermissionDenied)):
        TestSnapshotActivation(repo, resources, candidates).run(run_id, actor_id=ACTOR)
    assert db.execute('select * from "knowledge.document" order by id') == before
    assert repo.run(run_id)["phase"] != "ACTIVATED"


@pytest.mark.skipif(not os.getenv("MIGRATION_POSTGRES_DSN"), reason="isolated PostgreSQL only")
def test_replacement_postgres_transaction_and_same_cluster_identity(
    postgres_database_dsn, tmp_path
):
    db = Database(postgres_database_dsn)
    other = Database(postgres_database_dsn)
    try:
        Migrator(db, default_migrations_dir(), migrator_build="synthetic-replacement").run()
        _, repo, resources, candidates, run_id, resource_id, _ = replacement.__wrapped__(
            db, tmp_path
        )
        repo.assert_same_content(GovernanceStore(other))
        result = TestSnapshotActivation(repo, resources, candidates).run(run_id, actor_id=ACTOR)
        assert result["phase"] == "ACTIVATED"
        assert (
            db.execute_one(
                "select count(*) as n from knowledge.knowledge_base_document where state='included'"
            )["n"]
            == 4
        )
        assert resources.resolve(
            resources.store.get("retrieval_resource", resource_id)["knowledge_base_id"]
        )
    finally:
        other.close()
        db.close()


@pytest.mark.parametrize("failure", [False, True])
def test_three_route_evaluation_outputs_only_aggregate_and_fails_on_io_error(
    replacement, monkeypatch, capsys, failure
):
    from app.cli.replace_ones_knowledge import evaluate
    from app.modules.knowledge.domain.vector_contract import VectorError

    db, repo, resources, candidates, run_id, _, _ = replacement
    TestSnapshotActivation(repo, resources, candidates).run(run_id, actor_id=ACTOR)
    modes = []

    def query(self, code, base, text, *, mode, top_k):
        modes.append(mode)
        if failure:
            raise VectorError("knowledge_vector_response_invalid")
        return {"documents": []}

    monkeypatch.setattr(VectorService, "query", query)
    args = (
        db,
        repo.run(run_id),
        repo.binding(repo.run(run_id)["binding_id"]),
        resources.embedding,
        resources.qdrant,
    )
    if failure:
        with pytest.raises(ExportValidationError, match="knowledge_hybrid_evaluation_incomplete"):
            evaluate(*args)
    else:
        evaluate(*args)
    output = capsys.readouterr().out
    assert output.count('"event": "knowledge_hybrid_self_evaluation"') == 18
    assert set(modes) == {"bm25", "dense", "hybrid"}
    assert "合成报工重复提交" not in output
    assert "合成问题" not in output
    assert "self_item_only_not_human_relevance_or_real_ones_acceptance" in output
