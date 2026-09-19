from app.modules.knowledge.infrastructure.vector_repository import VectorRepository
import json

import pytest

from app.modules.knowledge.domain.governance import KnowledgeGovernanceError
from app.modules.knowledge.application.resource_service import KnowledgeResourceService
from backend.tests.test_knowledge_governance import (
    governance as governance_fixture,
    prepared as prepared_fixture,
    create as create_binding,
    SyntheticVerifier,
)


governance = governance_fixture
prepared = prepared_fixture
ACTOR = "synthetic_admin"


@pytest.fixture
def resources(governance):
    db, vector, snapshot, sources, permission, _, _ = governance
    vector.build("synthetic-v1", snapshot)
    binding = None
    sources.verifier = None  # 发布本地索引不需要 ONES 来源确认或凭据。
    service = KnowledgeResourceService(
        sources,
        VectorRepository(sources.store.database),
        embedding=vector.embedding,
        qdrant=vector.qdrant,
    )
    resource = service.create(
        actor_id=ACTOR,
        knowledge_base_id=snapshot["knowledge_base_id"],
        code="synthetic",
        name="合成知识库",
    )
    return db, vector, service, resource, binding, permission


def draft(f):
    _, vector, service, resource, binding, _ = f
    current = service.view(resource["id"])
    return service.save_draft(
        actor_id=ACTOR,
        resource_id=resource["id"],
        expected_revision=current["revision"],
        index_id=vector.repository.get("synthetic-v1")["id"],
    )


def publish(f):
    _, _, service, resource, _, _ = f
    saved = draft(f)
    verified = service.verify_draft(
        actor_id=ACTOR, resource_id=resource["id"], expected_revision=saved["revision"]
    )
    return service.publish(
        actor_id=ACTOR, resource_id=resource["id"], expected_revision=verified["revision"]
    )


def test_draft_verification_publication_are_distinct_and_publication_is_immutable(resources):
    db, _, service, resource, _, _ = resources
    with pytest.raises(KnowledgeGovernanceError):
        service.resolve(resource["knowledge_base_id"])
    initial = draft(resources)
    with pytest.raises(KnowledgeGovernanceError):
        service.publish(
            actor_id=ACTOR, resource_id=resource["id"], expected_revision=initial["revision"]
        )
    verified = service.verify_draft(
        actor_id=ACTOR, resource_id=resource["id"], expected_revision=initial["revision"]
    )
    assert verified["verification"]["status"] == "VERIFIED"
    with pytest.raises(KnowledgeGovernanceError):
        service.resolve(resource["knowledge_base_id"])
    current = service.publish(
        actor_id=ACTOR, resource_id=resource["id"], expected_revision=verified["revision"]
    )
    assert current["draft"] is None and current["published"]["published_at"]
    pinned = service.resolve(resource["knowledge_base_id"])
    revision = current["published"]
    next_draft = draft(resources)
    assert next_draft["verification"] is None
    assert service.store.get("retrieval_revision", revision["id"]) == revision
    service.recheck(pinned)  # 编辑未发布草稿不改变正在使用的旧发布。
    assert db.execute("pragma foreign_key_check") == []


@pytest.mark.parametrize(
    "change",
    [
        "disabled",
        "archived",
        "source",
        "index",
        "profile",
        "membership",
        "republish",
        "disable_enable",
        "chunk_profile",
        "collection",
        "index_version",
    ],
)
def test_pinned_calls_reject_revocation_or_version_change_without_fallback(resources, change):
    db, _, service, resource, binding, _ = resources
    current = publish(resources)
    pinned = service.resolve(resource["knowledge_base_id"])
    if change in {"disabled", "archived"}:
        service.set_status(
            actor_id=ACTOR,
            resource_id=resource["id"],
            expected_revision=current["revision"],
            status=change,
        )
    elif change == "source":
        db.execute('update "knowledge.document_revision" set source_project_id=?', ("changed",))
    elif change == "index":
        db.execute("update \"knowledge.vector_index\" set state='FAILED'")
    elif change == "profile":
        db.execute('update "knowledge.vector_index" set profile_hash=?', ("f" * 64,))
    elif change == "membership":
        db.execute("update \"knowledge.knowledge_base_document\" set state='removed'")
    elif change == "disable_enable":
        disabled = service.set_status(
            actor_id=ACTOR,
            resource_id=resource["id"],
            expected_revision=current["revision"],
            status="disabled",
        )
        service.set_status(
            actor_id=ACTOR,
            resource_id=resource["id"],
            expected_revision=disabled["revision"],
            status="enabled",
        )
        assert service.resolve(resource["knowledge_base_id"]) != pinned
    elif change == "chunk_profile":
        db.execute('update "knowledge.vector_index" set chunk_profile_hash=?', ("e" * 64,))
    elif change == "collection":
        db.execute(
            'update "knowledge.vector_index" set collection_name=?', ("synthetic_wrong_collection",)
        )
    elif change == "index_version":
        db.execute(
            'update "knowledge.vector_index" set updated_at=?', ("2000-01-01T00:00:00+00:00",)
        )
    else:
        publish(resources)
    with pytest.raises(KnowledgeGovernanceError):
        service.recheck(pinned)


def test_only_one_enabled_resource_and_archived_cannot_be_reenabled(resources):
    _, _, service, resource, _, _ = resources
    with pytest.raises(KnowledgeGovernanceError, match="knowledge_resource_conflict"):
        service.create(
            actor_id=ACTOR,
            knowledge_base_id=resource["knowledge_base_id"],
            code="other",
            name="合成其他",
        )
    disabled = service.set_status(
        actor_id=ACTOR, resource_id=resource["id"], expected_revision=1, status="disabled"
    )
    other = service.create(
        actor_id=ACTOR,
        knowledge_base_id=resource["knowledge_base_id"],
        code="other",
        name="合成其他",
    )
    with pytest.raises(KnowledgeGovernanceError, match="knowledge_resource_conflict"):
        service.set_status(
            actor_id=ACTOR,
            resource_id=resource["id"],
            expected_revision=disabled["revision"],
            status="enabled",
        )
    archived = service.set_status(
        actor_id=ACTOR, resource_id=other["id"], expected_revision=1, status="archived"
    )
    with pytest.raises(KnowledgeGovernanceError, match="knowledge_resource_unavailable"):
        service.set_status(
            actor_id=ACTOR,
            resource_id=other["id"],
            expected_revision=archived["revision"],
            status="enabled",
        )


def test_stale_revision_and_edit_after_verify_require_fresh_verification(resources):
    _, _, service, resource, _, _ = resources
    saved = draft(resources)
    verified = service.verify_draft(
        actor_id=ACTOR, resource_id=resource["id"], expected_revision=saved["revision"]
    )
    edited = draft(resources)
    with pytest.raises(KnowledgeGovernanceError, match="knowledge_revision_conflict"):
        service.publish(
            actor_id=ACTOR, resource_id=resource["id"], expected_revision=verified["revision"]
        )
    with pytest.raises(KnowledgeGovernanceError, match="knowledge_resource_unavailable"):
        service.publish(
            actor_id=ACTOR, resource_id=resource["id"], expected_revision=edited["revision"]
        )


@pytest.mark.parametrize("change", ["draft", "source", "status", "index", "permission"])
def test_validation_external_io_has_no_transaction_and_changes_are_rechecked(resources, change):
    db, vector, service, resource, binding, permission = resources
    saved = draft(resources)
    original = vector.embedding.check

    def mutate():
        original()
        if change == "draft":
            draft(resources)
        elif change == "source":
            db.execute('update "knowledge.document_revision" set source_project_id=?', ("changed",))
        elif change == "status":
            service.set_status(
                actor_id=ACTOR,
                resource_id=resource["id"],
                expected_revision=saved["revision"],
                status="disabled",
            )
        elif change == "index":
            db.execute("update \"knowledge.vector_index\" set state='FAILED'")
        else:
            permission.allowed = False

    vector.embedding.check = mutate
    from app.shared.exceptions import PermissionDenied

    with pytest.raises((KnowledgeGovernanceError, PermissionDenied)):
        service.verify_draft(
            actor_id=ACTOR, resource_id=resource["id"], expected_revision=saved["revision"]
        )
    assert not db.execute('select * from "knowledge.retrieval_verification"')


def test_later_failed_verification_cannot_reuse_earlier_success_even_when_clock_moves_back(
    resources, monkeypatch
):
    db, vector, service, resource, _, _ = resources
    saved = draft(resources)
    verified = service.verify_draft(
        actor_id=ACTOR, resource_id=resource["id"], expected_revision=saved["revision"]
    )
    monkeypatch.setattr(
        "app.modules.knowledge.application.resource_service.now",
        lambda: "2000-01-01T00:00:00+00:00",
    )

    def fail():
        raise RuntimeError("synthetic hidden provider body")

    vector.embedding.check = fail
    with pytest.raises(KnowledgeGovernanceError, match="knowledge_verification_failed"):
        service.verify_draft(
            actor_id=ACTOR, resource_id=resource["id"], expected_revision=verified["revision"]
        )
    current = service.view(resource["id"])
    assert current["verification"]["status"] == "FAILED"
    with pytest.raises(KnowledgeGovernanceError):
        service.publish(
            actor_id=ACTOR, resource_id=resource["id"], expected_revision=current["revision"]
        )
    stored = json.dumps(db.execute('select * from "knowledge.retrieval_verification"'), default=str)
    assert "hidden provider" not in stored


def test_no_ones_binding_required_and_no_source_or_vector_rewrites(resources):
    from copy import deepcopy
    from backend.tests.test_knowledge_chunks import source_fingerprint

    db, vector, service, resource, _, _ = resources
    before = source_fingerprint(db)
    points = deepcopy(vector.qdrant.points)
    current = publish(resources)
    pin = service.resolve(resource["knowledge_base_id"])
    assert current["published"]["binding_id"] is None
    assert pin.source_id == db.execute_one('select id from "knowledge.source"')["id"]
    assert db.execute('select * from "knowledge.source_binding"') == []
    assert source_fingerprint(db) == before and vector.qdrant.points == points


@pytest.mark.parametrize("dependency", ["embedding", "qdrant", "point_count"])
def test_no_binding_does_not_bypass_technical_validation(resources, dependency, monkeypatch):
    _, vector, service, resource, _, _ = resources
    saved = draft(resources)

    def unavailable(*args):
        raise RuntimeError("synthetic private dependency detail")

    if dependency == "point_count":
        monkeypatch.setattr(vector.qdrant, "count", lambda _: 0)
    else:
        monkeypatch.setattr(getattr(vector, dependency), "check", unavailable)
    with pytest.raises(KnowledgeGovernanceError, match="knowledge_verification_failed"):
        service.verify_draft(
            actor_id=ACTOR, resource_id=resource["id"], expected_revision=saved["revision"]
        )
    current = service.view(resource["id"])
    assert current["verification"]["status"] == "FAILED"
    with pytest.raises(KnowledgeGovernanceError):
        service.publish(
            actor_id=ACTOR, resource_id=resource["id"], expected_revision=current["revision"]
        )


def test_legacy_binding_publication_requires_explicit_resave_without_rewriting_history(
    resources, governance
):
    db, _, service, resource, _, _ = resources
    governance[3].verifier = SyntheticVerifier()
    binding = create_binding(governance)
    current = publish(resources)
    # 模拟迁移保留的旧版本：binding_id 非空，不可借用旧验证自动切换规则。
    db.execute(
        'update "knowledge.retrieval_revision" set binding_id=? where id=?',
        (binding["id"], current["published"]["id"]),
    )
    old = service.view(resource["id"])["published"]
    with pytest.raises(KnowledgeGovernanceError, match="knowledge_resource_unavailable"):
        service.resolve(resource["knowledge_base_id"])
    updated = publish(resources)
    assert updated["published"]["binding_id"] is None
    assert updated["published"]["id"] != old["id"]
    assert service.store.get("retrieval_revision", old["id"]) == old
    assert service.resolve(resource["knowledge_base_id"])
