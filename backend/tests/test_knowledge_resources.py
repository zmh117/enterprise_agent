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


def legacy_publication(fixture, *, explicit_storage=False):
    """合成旧摘要发布，不能用来改写正式发布。"""
    from backend.tests.test_knowledge_storage_connections import connection, SyntheticContentAccess

    db, vector, service, resource, _, _ = fixture
    if explicit_storage:
        service.content_access = SyntheticContentAccess(db, vector)
        saved = service.save_draft(
            actor_id=ACTOR,
            resource_id=resource["id"],
            expected_revision=service.view(resource["id"])["revision"],
            index_id=vector.repository.get("synthetic-v1")["id"],
            storage=connection(),
        )
        verified = service.verify_draft(
            actor_id=ACTOR, resource_id=resource["id"], expected_revision=saved["revision"]
        )
        current = service.publish(
            actor_id=ACTOR, resource_id=resource["id"], expected_revision=verified["revision"]
        )
    else:
        current = publish(fixture)
    old_config, source, _ = service._configuration(
        current,
        current["published"]["index_id"],
        storage=connection() if explicit_storage else None,
        version=0,
    )
    db.execute(
        'update "knowledge.retrieval_revision" set config_hash=?,configuration_version=0 where id=?',
        (old_config["config_hash"], current["published"]["id"]),
    )
    db.execute(
        'update "knowledge.retrieval_verification" set config_hash=? where revision_id=?',
        (old_config["config_hash"], current["published"]["id"]),
    )
    return service.view(resource["id"]), source["id"]


@pytest.mark.parametrize("explicit_storage", [False, True])
def test_explicit_scope_upgrade_preserves_old_revision_index_and_connection(
    resources, explicit_storage
):
    from copy import deepcopy
    from app.modules.knowledge.application.scope_upgrade import KnowledgeScopeUpgrade

    db, vector, service, resource, _, _ = resources
    current, source_id = legacy_publication(resources, explicit_storage=explicit_storage)
    old_revision = deepcopy(current["published"])
    old_proof = deepcopy(service.store.verification(old_revision["id"]))
    old_points, encoded = deepcopy(vector.qdrant.points), vector.embedding.encoded
    result = KnowledgeScopeUpgrade(service).run(
        actor_id=ACTOR, source_id=source_id, expected_resources={current["id"]: current["revision"]}
    )
    assert result == {"checked": 1, "upgraded": 1}
    after = service.view(resource["id"])
    assert after["draft"] is None and after["published"]["configuration_version"] == 4
    assert after["published"]["index_id"] == old_revision["index_id"]
    assert after["published"]["storage_config_json"] == old_revision["storage_config_json"]
    stored_old = service.store.get("retrieval_revision", old_revision["id"])
    old_revision.pop("storage", None)  # view 的非持久投影。
    assert stored_old == old_revision
    assert service.store.verification(old_revision["id"]) == old_proof
    assert service.store.verification(after["published"]["id"])["id"] != old_proof["id"]
    assert vector.qdrant.points == old_points and vector.embedding.encoded == encoded
    assert service.resolve(resource["knowledge_base_id"])
    assert KnowledgeScopeUpgrade(service).run(
        actor_id=ACTOR, source_id=source_id, expected_resources={after["id"]: after["revision"]}
    ) == {"checked": 1, "upgraded": 0}
    assert db.execute("select * from rbac_role_application_knowledge_base") == []


@pytest.mark.parametrize("conflict", ["scope", "draft", "disabled", "point", "unknown_hash"])
def test_scope_upgrade_fails_without_changing_publication(resources, conflict):
    from app.modules.knowledge.application.scope_upgrade import KnowledgeScopeUpgrade

    db, vector, service, resource, _, _ = resources
    current, source_id = legacy_publication(resources)
    expected = {current["id"]: current["revision"]}
    if conflict == "scope":
        expected["not_in_scope"] = 1
    elif conflict == "draft":
        draft(resources)
    elif conflict == "disabled":
        service.set_status(
            actor_id=ACTOR,
            resource_id=current["id"],
            expected_revision=current["revision"],
            status="disabled",
        )
    elif conflict == "point":
        next(iter(vector.qdrant.points.values()))["payload"]["revision_id"] = (
            "synthetic_bad_revision"
        )
    else:
        db.execute(
            'update "knowledge.retrieval_revision" set config_hash=? where id=?',
            ("f" * 64, current["published"]["id"]),
        )
    before = service.view(resource["id"])
    with pytest.raises(KnowledgeGovernanceError):
        KnowledgeScopeUpgrade(service).run(
            actor_id=ACTOR, source_id=source_id, expected_resources=expected
        )
    assert service.view(resource["id"]) == before


def test_scoped_publication_ignores_other_kb_changes_but_checks_own_kind(resources, tmp_path):
    from app.modules.knowledge.application.import_service import KnowledgeImportService
    from app.modules.knowledge.infrastructure.import_repository import ImportRepository
    from backend.tests.test_knowledge_work_item_types import prepare, typed_row

    db, _, service, resource, _, _ = resources
    KnowledgeImportService(ImportRepository(db)).import_export(
        prepare(tmp_path, [typed_row("ticket", index=3)], "ticket"),
        source_code="synthetic_source",
        knowledge_base_code="synthetic_tickets",
    )
    published = publish(resources)
    assert published["published"]["configuration_version"] == 4
    pin = service.resolve(resource["knowledge_base_id"])
    db.execute(
        'update "knowledge.document_revision" set content_hash=? where document_id in (select id from "knowledge.document" where external_id=?)',
        ("b" * 64, "synthetic_item_3"),
    )
    service.recheck(pin)
    db.execute(
        "update \"knowledge.document\" set document_kind='ticket' where external_id=?",
        ("synthetic_item_1",),
    )
    with pytest.raises(KnowledgeGovernanceError):
        service.recheck(pin)


def test_draft_mutation_obeys_same_source_lock_as_import_and_retention(resources):
    db, vector, service, resource, _, _ = resources
    source_id = db.execute_one('select id from "knowledge.source"')["id"]
    before = service.view(resource["id"])
    with service.store.source_lock(source_id):
        with pytest.raises(KnowledgeGovernanceError, match="knowledge_verification_busy"):
            service.save_draft(
                actor_id=ACTOR,
                resource_id=resource["id"],
                expected_revision=before["revision"],
                index_id=vector.repository.get("synthetic-v1")["id"],
            )
    assert service.view(resource["id"]) == before


def test_scope_upgrade_rejects_concurrent_disable_after_independent_verification(
    resources, monkeypatch
):
    from app.modules.knowledge.application.scope_upgrade import KnowledgeScopeUpgrade

    _, vector, service, resource, _, _ = resources
    before, source_id = legacy_publication(resources)
    check, interrupted = vector.qdrant.check, False

    def disable_once(index):
        nonlocal interrupted
        check(index)
        if not interrupted:
            interrupted = True
            service.set_status(
                actor_id=ACTOR,
                resource_id=resource["id"],
                expected_revision=before["revision"],
                status="disabled",
            )

    monkeypatch.setattr(vector.qdrant, "check", disable_once)
    with pytest.raises(KnowledgeGovernanceError, match="knowledge_revision_conflict"):
        KnowledgeScopeUpgrade(service).run(
            actor_id=ACTOR,
            source_id=source_id,
            expected_resources={before["id"]: before["revision"]},
        )
    after = service.view(resource["id"])
    assert after["status"] == "disabled" and after["published"] == before["published"]


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
