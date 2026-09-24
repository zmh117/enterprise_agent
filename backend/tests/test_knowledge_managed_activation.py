"""受管同步激活的合成事务、资源冻结和幂等回归；不连接真实 ONES。"""

from copy import deepcopy
from dataclasses import replace
import json

import pytest

from app.modules.audit.application.audit_service import AuditService
from app.modules.job.infrastructure.repositories import AuditRepository
from app.modules.knowledge.application.chunk_service import ChunkService
from app.modules.knowledge.application.managed_sync_activation import ManagedSyncActivation
from app.modules.knowledge.application.resource_service import KnowledgeResourceService
from app.modules.knowledge.application.source_service import KnowledgeAdministration
from app.modules.knowledge.application.vector_service import VectorService
from app.modules.knowledge.domain.chunking import DEFAULT_PROFILE
from app.modules.knowledge.domain.governance import KnowledgeGovernanceError
from app.modules.knowledge.domain.identity import stable_id
from app.modules.knowledge.domain.normalization import ExportValidationError, digest
from app.modules.knowledge.infrastructure.candidate_corpus import (
    CandidateChunkRepository,
    CandidateVectorRepository,
)
from app.modules.knowledge.infrastructure.managed_activation_repository import (
    ManagedActivationRepository,
)
from app.modules.knowledge.infrastructure.chunk_repository import ChunkRepository
from app.modules.knowledge.infrastructure.governance_repository import GovernanceStore
from app.modules.knowledge.infrastructure.vector_repository import VectorRepository
from backend.tests.test_knowledge_governance import SyntheticPermission
from backend.tests.test_knowledge_import import (
    database as database_fixture,
    export_row,
    prepare as prepare_legacy,
    run as import_legacy,
)
from backend.tests.test_knowledge_replacement import HybridMemory
from backend.tests.test_knowledge_vectors import SyntheticEmbedding


database = database_fixture
ACTOR = "synthetic_admin"


def _prepare_run(db, tmp_path, *, change: bool, move_to_ticket: bool = False):
    prepared = prepare_legacy(tmp_path, [export_row()])
    import_legacy(db, prepared)
    count = ChunkService(ChunkRepository(db)).run(
        knowledge_base_code="synthetic_base", expected_count=1, commit=True
    )["counts"]["chunks"]
    embedding, qdrant = SyntheticEmbedding(), HybridMemory()
    vectors = VectorRepository(db)
    base_id = stable_id("base", "synthetic_base")
    VectorService(vectors, embedding, qdrant).build(
        "synthetic-old", vectors.snapshot(base_id, DEFAULT_PROFILE.fingerprint, 1, count)
    )
    resources = KnowledgeResourceService(
        KnowledgeAdministration(
            GovernanceStore(db), SyntheticPermission(), AuditService(AuditRepository(db))
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
    repo = ManagedActivationRepository(db)
    config = {
        "base_codes": {
            "defect": "synthetic_base",
            "ticket": "synthetic_tickets",
            "requirement": "synthetic_requirements",
        },
        "resource_ids": [resource["id"]],
        "collector": {
            "provider_origin": "https://ones.example.test",
            "team_id": "synthetic-team",
            "project_ids": [prepared.records[0].values["source_project_id"]],
            "issue_types": {
                "defect": ["synthetic-defect-type"],
                "ticket": ["synthetic-ticket-type"],
                "requirement": ["synthetic-story-type"],
            },
            "child_type_ids": ["synthetic-child-type"],
            "first_date": "2024-01-01",
            "credential_ref": "secret://platform/synthetic-collector",
        },
    }
    binding = repo.configure(
        code="synthetic_managed",
        source_code="synthetic_source",
        configuration=config,
        expected_revision=0,
    )
    binding = repo.set_collection_enabled(
        binding["id"], enabled=True, expected_revision=binding["configuration_revision"]
    )
    run = repo.begin_collection(binding["id"], "2026-09-24T00:00:00+00:00")
    row = prepared.records[0]
    if change or move_to_ticket:
        values = deepcopy(row.values)
        if change:
            values["title"] += " 合成更新"
        values["source_update_stamp_raw"] += 100
        values["source_snapshot"]["detail"]["server_update_stamp"] = values[
            "source_update_stamp_raw"
        ]
        row = replace(
            row,
            document_kind="ticket" if move_to_ticket else row.document_kind,
            values=values,
            content_hash=digest(values),
        )
    repo.stage(run["id"], row)
    repo.complete_collection(
        run["id"],
        {
            "defect": 0 if move_to_ticket else 1,
            "ticket": 1 if move_to_ticket else 0,
            "requirement": 0,
        },
    )
    repo.advance(run["id"], expected_phase="STAGED", phase="CHUNKING")
    vectors = CandidateVectorRepository(db, run["id"])
    for base_id in repo.changed_bases(run["id"]):
        code = next(
            code
            for code in binding["configuration_json"]["base_codes"].values()
            if stable_id("base", code) == base_id
        )
        count = vectors.corpus.count(base_id)
        chunks = (
            ChunkService(CandidateChunkRepository(db, run["id"], profile=DEFAULT_PROFILE)).run(
                knowledge_base_code=code, expected_count=count, commit=True
            )["counts"]["chunks"]
            if count
            else 0
        )
        VectorService(vectors, resources.embedding, resources.qdrant).build(
            vectors.index_code(base_id),
            vectors.snapshot(base_id, DEFAULT_PROFILE.fingerprint, count, chunks),
        )
    repo.advance(run["id"], expected_phase="CHUNKING", phase="INDEXING")
    return repo, resources, vectors, run["id"], resource["id"], binding


def test_managed_activation_switches_content_and_publication_once(database, tmp_path):
    repo, resources, vectors, run_id, resource_id, _ = _prepare_run(database, tmp_path, change=True)
    before = resources.store.get("retrieval_resource", resource_id)
    pinned = resources.resolve(before["knowledge_base_id"])
    result = ManagedSyncActivation(repo, resources, vectors).run(run_id)
    assert result["phase"] == "ACTIVATED"
    after = resources.store.get("retrieval_resource", resource_id)
    assert after["published_revision_id"] != before["published_revision_id"]
    assert after["state_revision"] == before["state_revision"]
    assert resources.resolve(after["knowledge_base_id"])
    with pytest.raises(KnowledgeGovernanceError, match="knowledge_resource_changed"):
        resources.recheck(pinned)
    assert (
        repo.binding(repo.run(run_id)["binding_id"])["resource_pins_json"][resource_id][
            "published_revision_id"
        ]
        == after["published_revision_id"]
    )
    assert ManagedSyncActivation(repo, resources, vectors).run(run_id) == result
    assert resources.store.get("retrieval_resource", resource_id) == after


def test_type_move_activates_empty_old_base_with_new_ticket_base(database, tmp_path):
    repo, resources, vectors, run_id, resource_id, _ = _prepare_run(
        database, tmp_path, change=False, move_to_ticket=True
    )
    defect_id = resources.store.get("retrieval_resource", resource_id)["knowledge_base_id"]
    index = repo.indexes(run_id)[defect_id]
    assert index["expected_document_count"] == index["expected_chunk_count"] == 0
    result = ManagedSyncActivation(repo, resources, vectors).run(run_id)
    assert result["phase"] == "ACTIVATED"
    assert resources.resolve(defect_id)
    assert (
        database.execute_one(
            'select count(*) as n from "knowledge.knowledge_base_document" where knowledge_base_id=? and state=?',
            (defect_id, "included"),
        )["n"]
        == 0
    )
    ticket_id = stable_id("base", "synthetic_tickets")
    assert (
        database.execute_one(
            'select count(*) as n from "knowledge.knowledge_base_document" where knowledge_base_id=? and state=?',
            (ticket_id, "included"),
        )["n"]
        == 1
    )
    assert (
        database.execute_one(
            'select count(*) as n from "knowledge.retrieval_resource" where knowledge_base_id=?',
            (ticket_id,),
        )["n"]
        == 0
    )


def test_no_change_run_advances_watermark_without_index_or_publication(database, tmp_path):
    repo, resources, vectors, run_id, resource_id, _ = _prepare_run(
        database, tmp_path, change=False
    )
    before = resources.store.get("retrieval_resource", resource_id)
    assert repo.changed_bases(run_id) == set()
    result = ManagedSyncActivation(repo, resources, vectors).run(run_id)
    assert result["phase"] == "ACTIVATED"
    assert resources.store.get("retrieval_resource", resource_id) == before
    assert repo.run(run_id)["activated_watermark"] is not None


def test_post_commit_interruption_replays_without_second_publication(
    database, tmp_path, monkeypatch
):
    repo, resources, vectors, run_id, resource_id, _ = _prepare_run(database, tmp_path, change=True)
    original_summary = repo.summary
    interrupted = False

    def lost_reply(identifier):
        nonlocal interrupted
        if not interrupted and repo.run(identifier)["phase"] == "ACTIVATED":
            interrupted = True
            raise RuntimeError("synthetic lost reply")
        return original_summary(identifier)

    monkeypatch.setattr(repo, "summary", lost_reply)
    with pytest.raises(RuntimeError, match="synthetic lost reply"):
        ManagedSyncActivation(repo, resources, vectors).run(run_id)
    after = resources.store.get("retrieval_resource", resource_id)
    assert repo.run(run_id)["phase"] == "ACTIVATED"
    assert ManagedSyncActivation(repo, resources, vectors).run(run_id)["phase"] == "ACTIVATED"
    assert resources.store.get("retrieval_resource", resource_id) == after


def test_managed_publication_failure_rolls_back_all_current_facts(database, tmp_path, monkeypatch):
    repo, resources, vectors, run_id, resource_id, _ = _prepare_run(database, tmp_path, change=True)
    db = database
    before_doc = db.execute('select * from "knowledge.document" order by id')
    before_resource = resources.store.get("retrieval_resource", resource_id)

    def interrupt(*args):
        raise RuntimeError("synthetic commit interruption")

    monkeypatch.setattr(resources.store, "publish", interrupt)
    with pytest.raises(RuntimeError, match="synthetic commit interruption"):
        ManagedSyncActivation(repo, resources, vectors).run(run_id)
    assert db.execute('select * from "knowledge.document" order by id') == before_doc
    assert resources.store.get("retrieval_resource", resource_id) == before_resource
    assert repo.run(run_id)["phase"] == "VERIFIED"


def test_managed_activation_rejects_admin_draft_and_disabled_binding(database, tmp_path):
    repo, resources, vectors, run_id, resource_id, binding = _prepare_run(
        database, tmp_path, change=True
    )
    before = resources.store.get("retrieval_resource", resource_id)
    resources.save_draft(
        actor_id=ACTOR,
        resource_id=resource_id,
        expected_revision=before["revision"],
        index_id=resources.vectors.get("synthetic-old")["id"],
    )
    with pytest.raises(ExportValidationError, match="knowledge_sync_resource_changed"):
        ManagedSyncActivation(repo, resources, vectors).run(run_id)
    assert repo.run(run_id)["phase"] == "INDEXING"
    repo.set_collection_enabled(
        binding["id"], enabled=False, expected_revision=binding["configuration_revision"]
    )
    with pytest.raises(ExportValidationError, match="knowledge_collection_disabled"):
        ManagedSyncActivation(repo, resources, vectors).run(run_id)


def test_external_content_binding_cannot_be_enabled(database, tmp_path):
    repo, resources, _, run_id, resource_id, binding = _prepare_run(
        database, tmp_path, change=False
    )
    repo.set_collection_enabled(
        binding["id"], enabled=False, expected_revision=binding["configuration_revision"]
    )
    repo.cancel(run_id)
    revision_id = resources.store.get("retrieval_resource", resource_id)["published_revision_id"]
    external = {
        "postgres": {
            "mode": "external",
            "host": "db.example.test",
            "port": 5432,
            "database": "synthetic",
            "username": "reader",
            "password_ref": "secret://platform/synthetic-db",
            "sslmode": "require",
        },
        "qdrant": {"url": "http://knowledge-qdrant:6333", "api_key_ref": ""},
    }
    database.execute(
        'update "knowledge.retrieval_revision" set storage_config_json=? where id=?',
        (json.dumps(external), revision_id),
    )
    with pytest.raises(ExportValidationError, match="knowledge_sync_external_content_unsupported"):
        repo.set_collection_enabled(
            binding["id"], enabled=True, expected_revision=binding["configuration_revision"]
        )
