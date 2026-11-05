"""真实数据库合同及合成向量端；不访问 ONES 或真实业务数据。"""

from copy import deepcopy
from dataclasses import replace
from datetime import date
import json
from types import SimpleNamespace

import httpx
import pytest

from app.modules.audit.application.audit_service import AuditService
from app.modules.job.infrastructure.repositories import AuditRepository
from app.modules.knowledge.application.candidates import current_documents
from app.modules.knowledge.application.incremental_sync import IncrementalSyncPipeline
from app.modules.knowledge.application.ones_collection_normalizer import OnesCollectionNormalizer
from app.modules.knowledge.application.resource_service import KnowledgeResourceService
from app.modules.knowledge.application.vector_service import VectorService
from app.modules.knowledge.application.source_service import KnowledgeAdministration
from app.modules.knowledge.domain.identity import stable_id
from app.modules.knowledge.domain.governance import KnowledgeGovernanceError
from app.modules.knowledge.domain.normalization import ExportValidationError, digest
from app.modules.knowledge.domain.vector_contract import VectorError
from app.modules.knowledge.infrastructure.governance_repository import GovernanceStore
from app.modules.knowledge.infrastructure.incremental_repository import (
    IncrementalSyncRepository,
    IncrementalVectorRepository,
)
from app.modules.knowledge.infrastructure.incremental_steps import IncrementalSyncSteps
from app.modules.knowledge.infrastructure.incremental_adoption import IncrementalAdoption
from app.modules.knowledge.infrastructure.import_repository import ImportRepository
from app.modules.knowledge.infrastructure.vector_repository import VectorRepository
from app.modules.knowledge.infrastructure.vector_clients import QdrantClient
from app.modules.knowledge.infrastructure.sync_repository import SyncRepository
from backend.tests.test_knowledge_governance import SyntheticPermission
from backend.tests.test_knowledge_import import database as database_fixture
from backend.tests.test_knowledge_keep_ids import dataset
from backend.tests.test_knowledge_ones_collection import _enabled_binding
from backend.tests.test_knowledge_replacement import HybridMemory
from backend.tests.test_knowledge_vectors import SyntheticEmbedding

database = database_fixture


class IncrementalMemory(HybridMemory):
    def __init__(self):
        super().__init__()
        self.collections = set()
        self.deleted = []

    def ensure(self, index):
        self.collections.add(index["id"])
        self.check(index)

    def set_searchable(self, index, ids, value):
        self.check(index)
        for key in ids:
            self.points[key]["payload"]["searchable"] = value

    def delete_points(self, index, ids):
        self.check(index)
        self.deleted.extend(ids)
        for key in ids:
            self.points.pop(key, None)

    def search(self, index, vector, limit):
        return [
            dict(point, score=1.0)
            for point in self.points.values()
            if point["payload"]["index_id"] == index["id"] and point["payload"].get("searchable")
        ][:limit]

    def count(self, index):
        return sum(point["payload"]["index_id"] == index["id"] for point in self.points.values())

    def hybrid_search(self, index, vector, query, limit, *, mode):
        assert mode in {"dense", "bm25", "hybrid"}
        return self.search(index, vector, limit)


class Harness:
    def __init__(self, database, tmp_path):
        _, self.binding = _enabled_binding(database)
        self.db, self.tmp_path = database, tmp_path
        self.repo = IncrementalSyncRepository(database)
        self.vectors = IncrementalVectorRepository(database)
        self.embedding, self.qdrant = SyntheticEmbedding(), IncrementalMemory()
        self.steps = IncrementalSyncSteps(
            database, self.embedding, self.qdrant, tmp_path, lambda: None
        )
        self.sequence = 0
        self.pipeline = IncrementalSyncPipeline(
            self.repo, lambda _: pytest.fail("already collected"), self.steps.process, lambda: None
        )

    def records(self, *numbers):
        template = dataset(self.tmp_path)["缺陷"]
        normalizer = OnesCollectionNormalizer(fields={}, names={})
        result = []
        for number in numbers:
            detail = {
                **template,
                "field_values": [],
                "uuid": f"synthetic_item_{number}",
                "number": number,
                "summary": f"合成缺陷 {number}",
            }
            listing = {
                "uuid": detail["uuid"],
                "number": number,
                "name": detail["summary"],
                "project": {"uuid": "project_id", "name": "合成项目"},
                "status": {"uuid": "status_id", "name": "处理中"},
                "issueType": {"uuid": "type_1", "name": "缺陷"},
                "createTime": detail["create_time"],
            }
            result.append(normalizer.normalize(listing, detail, kind="defect"))
        return result

    def stage(self, records):
        self.sequence += 1
        run = self.repo.begin_collection(
            self.binding["id"],
            f"2026-10-27T00:{self.sequence:02}:00+00:00",
            through=date(2024, 1, 1),
        )
        counts = dict.fromkeys(("defect", "ticket", "requirement"), 0)
        for record in records:
            self.repo.stage(run["id"], record)
            counts[record.document_kind] += 1
        self.repo.complete_collection_day(run["id"], date(2024, 1, 1), counts)
        self.repo.complete_collection(run["id"], counts)
        return run["id"]

    def run(self):
        return self.pipeline.run_once(self.binding["id"])

    def index(self, kind="defect"):
        base = stable_id("base", self.binding["configuration_json"]["base_codes"][kind])
        row = self.db.execute_one(
            f"select code from {self.repo.t('vector_index')} where knowledge_base_id=? and incremental=1",
            (base,),
        )
        return self.vectors.get(row["code"])


@pytest.fixture
def harness(database, tmp_path):
    return Harness(database, tmp_path)


def revised(record, *, kind=None):
    values = deepcopy(record.values)
    values["title"] += " 新的业务内容"
    values["source_update_stamp_raw"] += 1000
    values["source_snapshot"]["detail"]["server_update_stamp"] = values["source_update_stamp_raw"]
    if kind:
        values["attributes"]["document_kind"] = kind
    return replace(
        record,
        values=values,
        content_hash=digest(values),
        document_kind=kind or record.document_kind,
    )


def same_stamp_revised(record):
    values = deepcopy(record.values)
    values["title"] += " 本次内容 B"
    return replace(record, values=values, content_hash=digest(values))


def test_document_progress_persists_start_and_completion_within_throttle_window(
    harness, monkeypatch
):
    from app.modules.knowledge.infrastructure import incremental_steps

    h = harness
    records = h.records(1, 2)
    values = {**records[1].values, "body_text": "合成多块文档内容。" * 300}
    records[1] = replace(records[1], values=values, content_hash=digest(values))
    run_id = h.stage(records)
    monkeypatch.setattr(incremental_steps, "time", SimpleNamespace(monotonic=lambda: 100.0))
    events = []

    def observe(event):
        persisted = h.repo.summary(run_id)["progress"]
        for key in ("processed", "total", "encoded", "reused", "verified"):
            assert persisted[key] == event[key]
        events.append(event)

    h.steps.progress = observe
    assert h.run()["content_status"] == "COMPLETED"
    assert len(events) == 4
    totals = set()
    for started, finished in zip(events[::2], events[1::2], strict=True):
        assert started["document_id"] == finished["document_id"]
        actual = h.db.execute_one(
            f"select count(*) as n from {h.repo.t('document_chunk')} c "
            f"join {h.repo.t('document_chunk_set')} s on s.id=c.chunk_set_id "
            "where s.document_id=?",
            (finished["document_id"],),
        )["n"]
        totals.add(actual)
        assert started["processed"] == started["encoded"] == started["reused"] == 0
        assert started["total"] == finished["total"] == actual
        assert finished["processed"] == finished["verified"] == actual
        assert finished["encoded"] + finished["reused"] == actual
    assert len(totals) == 2


def test_vector_progress_counts_only_verified_blocks_and_resumes_with_reuse(harness, monkeypatch):
    h = harness
    run_id = h.stage(h.records(1))
    original = h.qdrant.retrieve

    def fail_verification(index, ids):
        if h.qdrant.points:
            return {}
        return original(index, ids)

    monkeypatch.setattr(h.qdrant, "retrieve", fail_verification)
    failed = h.run()
    assert failed["content_status"] == "PARTIAL"
    assert failed["progress"]["processed"] == 0
    assert failed["progress"]["total"] == len(h.qdrant.points) > 0
    encoded = h.embedding.encoded
    monkeypatch.setattr(h.qdrant, "retrieve", original)
    completed = h.run()
    assert completed["content_status"] == "COMPLETED"
    progress = h.repo.summary(run_id)["progress"]
    assert progress["processed"] == progress["total"] == progress["reused"]
    assert progress["encoded"] == 0
    assert h.embedding.encoded == encoded


def test_three_new_documents_keep_collections_and_old_vectors(harness, monkeypatch):
    h = harness
    records = h.records(1, 2, 3)
    records[1] = revised(records[1], kind="ticket")
    records[2] = revised(records[2], kind="requirement")
    h.stage(records)
    assert h.run()["content_status"] == "COMPLETED"
    old = deepcopy(h.qdrant.points)
    collections = set(h.qdrant.collections)
    monkeypatch.setattr(VectorRepository, "snapshot", lambda *_: pytest.fail("full snapshot"))
    monkeypatch.setattr(VectorRepository, "rows", lambda *_: pytest.fail("full corpus rows"))
    monkeypatch.setattr(SyncRepository, "_freeze_page", lambda *_: pytest.fail("full baseline"))
    monkeypatch.setattr(h.qdrant, "count", lambda *_: pytest.fail("full collection count"))
    run_id = h.stage(h.records(4, 5, 6))
    assert h.run()["documents"] == {"total": 3, "completed": 3, "failed": 0}
    assert h.qdrant.collections == collections
    assert all(h.qdrant.points[key] == value for key, value in old.items())
    assert h.qdrant.deleted == []
    assert len(list(h.repo.candidates(run_id))) == 3
    assert h.index()["expected_document_count"] == 4
    assert h.index("ticket")["expected_document_count"] == 1


def test_no_change_has_zero_embedding_and_vector_writes(harness, monkeypatch):
    h = harness
    records = h.records(1)
    h.stage(records)
    h.run()
    before = h.embedding.encoded, h.qdrant.writes, deepcopy(h.qdrant.points)
    monkeypatch.setattr(
        h.steps.repo, "prepare_document", lambda *_: pytest.fail("unchanged chunking")
    )
    monkeypatch.setattr(
        h.steps.repo, "revision", lambda *_: pytest.fail("unchanged full body read")
    )
    h.stage(records)
    assert h.run()["content_status"] == "COMPLETED"
    assert (h.embedding.encoded, h.qdrant.writes, h.qdrant.points) == before


def test_modified_document_replaces_only_its_old_points(harness):
    h = harness
    records = h.records(1, 2)
    h.stage(records)
    h.run()
    old = deepcopy(h.qdrant.points)
    h.stage([revised(records[0])])
    assert h.run()["content_status"] == "COMPLETED"
    affected = stable_id(
        "document", h.binding["source_id"], "ones_work_item", records[0].external_id
    )
    for key, point in old.items():
        if point["payload"]["document_id"] == affected:
            assert key not in h.qdrant.points
        else:
            assert h.qdrant.points[key] == point
    index = h.index()
    hits = h.qdrant.search(index, [], 200)
    assert len(current_documents(h.vectors, index, hits)) == 2
    assert h.qdrant.count(index) == index["expected_chunk_count"]


@pytest.mark.parametrize("method", ["upsert", "set_searchable", "delete_points"])
def test_crash_after_external_write_resumes_without_encoding_again(harness, monkeypatch, method):
    h = harness
    records = h.records(1)
    h.stage(records)
    h.run()
    h.stage([revised(records[0])])
    original = getattr(h.qdrant, method)

    def crash(*args):
        original(*args)
        raise RuntimeError("synthetic crash")

    monkeypatch.setattr(h.qdrant, method, crash)
    with pytest.raises(RuntimeError, match="synthetic crash"):
        h.run()
    encoded = h.embedding.encoded
    monkeypatch.setattr(h.qdrant, method, original)
    assert h.run()["content_status"] == "COMPLETED"
    assert h.embedding.encoded == encoded
    assert h.qdrant.count(h.index()) == h.index()["expected_chunk_count"]


def test_partial_failure_keeps_success_and_retries_only_failed_document(harness, monkeypatch):
    h = harness
    records = h.records(1, 2)
    run_id = h.stage(records)
    bad = stable_id("document", h.binding["source_id"], "ones_work_item", records[0].external_id)
    original = h.steps.repo.prepare_document

    def fail(candidate, profile):
        if candidate["document_id"] == bad:
            raise VectorError("knowledge_embedding_busy")
        return original(candidate, profile)

    monkeypatch.setattr(h.steps.repo, "prepare_document", fail)
    result = h.run()
    assert result["content_status"] == "PARTIAL"
    assert result["documents"] == {"total": 2, "completed": 1, "failed": 1}
    saved = deepcopy(h.qdrant.points)
    monkeypatch.setattr(h.steps.repo, "prepare_document", original)
    assert h.run()["content_status"] == "COMPLETED"
    assert all(h.qdrant.points[key] == value for key, value in saved.items())
    assert h.repo.candidate(run_id, bad)["processing_error"] is None


def test_type_move_empties_old_base_without_rebuilding_it(harness):
    h = harness
    record = h.records(1)[0]
    h.stage([record])
    h.run()
    original_id = h.index()["id"]
    h.stage([revised(record, kind="ticket")])
    assert h.run()["content_status"] == "COMPLETED"
    assert h.index()["id"] == original_id
    assert h.index()["expected_document_count"] == h.qdrant.count(h.index()) == 0
    assert h.index("ticket")["expected_document_count"] == 1


def test_content_update_does_not_change_publication_or_scan_members(harness, monkeypatch):
    h = harness
    h.stage(h.records(1))
    h.run()
    store = GovernanceStore(h.db)
    resources = KnowledgeResourceService(
        KnowledgeAdministration(store, SyntheticPermission(), AuditService(AuditRepository(h.db))),
        h.vectors,
        embedding=h.embedding,
        qdrant=h.qdrant,
    )
    resource = resources.create(
        actor_id="synthetic_admin",
        knowledge_base_id=h.index()["knowledge_base_id"],
        code="incremental",
        name="合成增量库",
    )
    saved = resources.save_draft(
        actor_id="synthetic_admin",
        resource_id=resource["id"],
        expected_revision=resource["revision"],
        index_id=h.index()["id"],
    )
    verified = resources.verify_draft(
        actor_id="synthetic_admin", resource_id=resource["id"], expected_revision=saved["revision"]
    )
    resources.publish(
        actor_id="synthetic_admin",
        resource_id=resource["id"],
        expected_revision=verified["revision"],
    )
    pin = resources.resolve(h.index()["knowledge_base_id"])
    monkeypatch.setattr(store, "members", lambda *_: pytest.fail("full member scan"))
    monkeypatch.setattr(store, "member_source_items", lambda *_: pytest.fail("full source scan"))
    h.stage(h.records(2))
    h.run()
    assert resources.resolve(pin.knowledge_base_id) == pin
    resources.recheck(pin)
    resources.store.set_resource_status(resource["id"], "disabled")
    h.stage(h.records(3))
    assert h.run()["content_status"] == "COMPLETED"
    with pytest.raises(KnowledgeGovernanceError):
        resources.recheck(pin)
    assert h.index()["expected_document_count"] == 3


def test_old_active_run_requires_explicit_migration(harness):
    h = harness
    run_id = h.stage(h.records(1))
    h.db.execute('update "knowledge.sync_run" set incremental=0 where id=?', (run_id,))
    with pytest.raises(ExportValidationError, match="knowledge_sync_migration_required"):
        h.run()


def test_empty_existing_index_also_requires_explicit_adoption(harness):
    from app.modules.knowledge.domain.chunking import KEEP_IDS_PROFILE

    h = harness
    base_id = stable_id("base", h.binding["configuration_json"]["base_codes"]["defect"])
    index = h.vectors.create(
        "old-empty", h.vectors.snapshot(base_id, KEEP_IDS_PROFILE.fingerprint, 0, 0)
    )
    h.vectors.state(index, "READY")
    h.stage(h.records(1))
    with pytest.raises(VectorError, match="knowledge_sync_migration_required"):
        h.run()
    assert h.qdrant.collections == set()


def test_pending_points_are_hidden_and_partial_apply_excludes_old_revision(harness, monkeypatch):
    h = harness
    record = h.records(1)[0]
    h.stage([record])
    apply = h.steps.repo.apply_document
    monkeypatch.setattr(
        h.steps.repo, "apply_document", lambda *_: (_ for _ in ()).throw(RuntimeError("stop"))
    )
    with pytest.raises(RuntimeError):
        h.run()
    assert h.qdrant.points and h.qdrant.search(h.index(), [], 200) == []
    result = VectorService(h.vectors, h.embedding, h.qdrant).query(
        h.index()["code"], h.binding["configuration_json"]["base_codes"]["defect"], "合成"
    )
    assert result["documents"] == []
    monkeypatch.setattr(h.steps.repo, "apply_document", apply)
    h.run()
    h.stage([revised(record)])
    monkeypatch.setattr(
        h.steps.writer, "expose", lambda *_: (_ for _ in ()).throw(RuntimeError("stop"))
    )
    with pytest.raises(RuntimeError):
        h.run()
    hits = h.qdrant.search(h.index(), [], 200)
    assert hits  # 旧点尚未删除，但已不能作为当前内容返回。
    assert current_documents(h.vectors, h.index(), hits) == []


def test_disabled_run_resumes_and_cannot_cancel_pending_writes(harness, monkeypatch):
    h = harness
    run_id = h.stage(h.records(1))
    original = h.steps.writer.expose
    monkeypatch.setattr(
        h.steps.writer, "expose", lambda *_: (_ for _ in ()).throw(RuntimeError("stop"))
    )
    with pytest.raises(RuntimeError):
        h.run()
    with pytest.raises(ExportValidationError, match="knowledge_sync_resume_required"):
        h.repo.cancel(run_id)
    with pytest.raises(ExportValidationError, match="knowledge_source_import_busy"):
        h.repo.configure(
            code=h.binding["code"],
            source_code="synthetic_errors_source",
            configuration=h.binding["configuration_json"],
            expected_revision=h.binding["configuration_revision"],
        )
    revision = h.binding["configuration_revision"]
    h.repo.set_collection_enabled(h.binding["id"], enabled=False, expected_revision=revision)
    assert h.repo.run(run_id)["active"] == 1
    h.repo.set_collection_enabled(h.binding["id"], enabled=True, expected_revision=revision)
    monkeypatch.setattr(h.steps.writer, "expose", original)
    assert h.run()["content_status"] == "COMPLETED"


def test_legacy_writes_cannot_bypass_incremental_pipeline(harness):
    h = harness
    h.stage(h.records(1))
    h.run()
    with pytest.raises(ExportValidationError, match="knowledge_incremental_source_managed"):
        ImportRepository(h.db)._assert_direct_write_allowed(
            h.binding["source_id"], h.index()["knowledge_base_id"]
        )
    with pytest.raises(VectorError, match="knowledge_incremental_index_managed"):
        VectorService(h.vectors, h.embedding, h.qdrant).build(h.index()["code"], h.index())


def test_adopt_existing_vectors_is_recoverable_and_preserves_publication_state(
    harness, monkeypatch
):
    h = harness
    h.stage(h.records(1, 2))
    h.run()
    index = h.index()
    snapshot = h.vectors.snapshot(
        index["knowledge_base_id"],
        index["chunk_profile_hash"],
        index["expected_document_count"],
        index["expected_chunk_count"],
    )
    h.db.execute(
        'update "knowledge.vector_index" set incremental=0,corpus_hash=? where id=?',
        (snapshot["corpus_hash"], index["id"]),
    )
    for point in h.qdrant.points.values():
        point["payload"].pop("searchable")
    administration = KnowledgeAdministration(
        GovernanceStore(h.db), SyntheticPermission(), AuditService(AuditRepository(h.db))
    )
    resources = KnowledgeResourceService(
        administration, h.vectors, embedding=h.embedding, qdrant=h.qdrant
    )
    resource = resources.create(
        actor_id="synthetic_admin",
        knowledge_base_id=index["knowledge_base_id"],
        code="adopt",
        name="合成",
    )
    for method, extra in (
        (resources.save_draft, {"index_id": index["id"]}),
        (resources.verify_draft, {}),
        (resources.publish, {}),
    ):
        resource = method(
            actor_id="synthetic_admin",
            resource_id=resource["id"],
            expected_revision=resource["revision"],
            **extra,
        )
    old_pin = resources.resolve(index["knowledge_base_id"])
    h.repo.set_collection_enabled(
        h.binding["id"], enabled=False, expected_revision=h.binding["configuration_revision"]
    )
    adoption = IncrementalAdoption(h.db, administration, h.qdrant)
    encoded, writes = h.embedding.encoded, h.qdrant.writes
    assert (
        adoption.run(h.binding["id"], index["code"], actor_id="synthetic_admin", commit=False)[
            "mode"
        ]
        == "preflight"
    )
    original = h.qdrant.set_searchable

    def crash(*args):
        original(*args)
        raise RuntimeError("synthetic crash")

    monkeypatch.setattr(h.qdrant, "set_searchable", crash)
    with pytest.raises(RuntimeError):
        adoption.run(h.binding["id"], index["code"], actor_id="synthetic_admin", commit=True)
    assert h.vectors.get(index["code"])["incremental"] == 0
    monkeypatch.setattr(h.qdrant, "set_searchable", original)
    assert (
        adoption.run(h.binding["id"], index["code"], actor_id="synthetic_admin", commit=True)[
            "mode"
        ]
        == "adopted"
    )
    pin = resources.resolve(index["knowledge_base_id"])
    assert pin.index_id == old_pin.index_id and pin.revision_id != old_pin.revision_id
    assert (h.embedding.encoded, h.qdrant.writes) == (encoded, writes)
    assert (
        adoption.run(h.binding["id"], index["code"], actor_id="synthetic_admin", commit=True)[
            "mode"
        ]
        == "already_adopted"
    )
    assert resources.resolve(pin.knowledge_base_id) == pin


@pytest.mark.parametrize("mode", ["hybrid", "bm25", "dense", "legacy_dense"])
def test_incremental_query_routes_filter_pending_points(mode):
    from backend.tests.test_knowledge_hybrid import index
    from app.modules.knowledge.domain.chunking import DEFAULT_PROFILE

    calls = []

    def handle(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"result": {"points": []}})

    client = QdrantClient(transport=httpx.MockTransport(handle))
    value = {**index(), "incremental": 1}
    try:
        if mode == "legacy_dense":
            value["chunk_profile_hash"] = DEFAULT_PROFILE.fingerprint
            client.search(value, [1.0] + [0.0] * 1023, 200)
        else:
            client.hybrid_search(value, [1.0] + [0.0] * 1023, "合成", 200, mode=mode)
        requirement = {"key": "searchable", "match": {"value": True}}
        assert requirement in calls[0]["filter"]["must"]
        for route in calls[0].get("prefetch", []):
            assert requirement in route["filter"]["must"]
    finally:
        client.http.close()


def _live_provider(h):
    from app.modules.knowledge.application.ones_collection import CollectionPage
    from backend.tests.test_knowledge_ones_collection import Provider

    provider = Provider()
    template = dataset(h.tmp_path)["缺陷"]
    day = date(2024, 1, 1)
    listings = []
    for number in (1, 2):
        raw = {
            **template,
            "field_values": [],
            "project_uuid": "project-1",
            "issue_type_uuid": "defect-type",
            "uuid": f"synthetic_item_{number}",
            "number": number,
            "summary": f"合成缺陷 {number}",
        }
        provider.details[raw["uuid"]] = raw
        listings.append(
            {
                "uuid": raw["uuid"],
                "number": number,
                "name": raw["summary"],
                "project": {"uuid": "project-1", "name": "合成项目"},
                "status": {"uuid": "status_id", "name": "处理中"},
                "issueType": {"uuid": "defect-type", "name": "缺陷"},
                "createTime": raw["create_time"],
            }
        )
    provider.counts["defect-type", day, day] = 2
    provider.pages["defect-type", day, day, None] = CollectionPage(tuple(listings), 2, False, None)
    return provider, listings


def test_same_stamp_online_collection_accepts_latest_and_logs_after_commit(harness, capsys):
    from app.cli.sync_ones_knowledge import emit
    from app.modules.knowledge.application.ones_collection_service import (
        KnowledgeOnesCollectionService,
    )

    h = harness
    provider, listings = _live_provider(h)
    day = date(2024, 1, 1)
    service = KnowledgeOnesCollectionService(h.repo, lambda _: provider, emit=emit)
    h.steps.emit = emit

    def collect(binding_id):
        h.sequence += 1
        return service.collect_once(
            binding_id, scan_at=f"2026-10-27T00:{h.sequence:02}:00+00:00", through=day
        )

    h.pipeline.collect_once = collect
    assert h.run()["counts"] == {"created": 2}
    before_points = deepcopy(h.qdrant.points)
    before = h.db.execute_one(
        f"select * from {h.repo.t('document')} where external_id='synthetic_item_1'"
    )
    provider.details["synthetic_item_1"]["summary"] = listings[0]["name"] = (
        "SYNTHETIC_BUSINESS_TITLE"
    )
    provider.details["synthetic_item_1"]["desc"] = "SYNTHETIC_BUSINESS_BODY"
    result = h.run()
    assert result["phase"] == "ACTIVATED" and result["content_status"] == "COMPLETED"
    assert result["counts"] == {"revised": 1, "unchanged": 1}
    assert h.repo.active_collection(h.binding["id"]) is None
    assert len(provider.fetched) == 4  # 每轮每项一次详情；无二次复核请求。
    after = h.db.execute_one(f"select * from {h.repo.t('document')} where id=?", (before["id"],))
    assert before["current_revision_id"] != after["current_revision_id"]
    assert before["source_observed_stamp_raw"] == after["source_observed_stamp_raw"]
    old_revision = h.repo.revision(before["current_revision_id"])
    new_revision = h.repo.revision(after["current_revision_id"])
    assert old_revision["title"] == "合成缺陷 1"
    assert new_revision["title"] == "SYNTHETIC_BUSINESS_TITLE"
    assert old_revision["source_update_stamp_raw"] == new_revision["source_update_stamp_raw"]
    assert new_revision["revision_no"] == old_revision["revision_no"] + 1
    for key, point in before_points.items():
        if point["payload"]["document_id"] != before["id"]:
            assert h.qdrant.points[key] == point
    output = capsys.readouterr().out
    assert "SYNTHETIC_BUSINESS_TITLE" not in output and "SYNTHETIC_BUSINESS_BODY" not in output
    events = [json.loads(line) for line in output.splitlines()]
    assert len(events) == 2 and [e["phase"] for e in events] == ["STAGED", "DONE"]
    for event in events:
        assert event["event"] == "knowledge_source_same_stamp_revised"
        assert event["old_stamp"] == event["new_stamp"] == before["source_observed_stamp_raw"]
        assert event["old_semantic_hash"] != event["new_semantic_hash"]
        assert event["old_revision_id"] == before["current_revision_id"]
        assert event["new_revision_id"] == after["current_revision_id"]
        assert event["reason"] == "same_source_stamp_content_changed"
    encoded, writes = h.embedding.encoded, h.qdrant.writes
    assert h.run()["counts"] == {"unchanged": 2}
    assert (h.embedding.encoded, h.qdrant.writes) == (encoded, writes)
    assert capsys.readouterr().out == ""
    assert len(provider.fetched) == 6


@pytest.mark.parametrize(
    "mutation",
    [
        lambda v: v.update(normalizer_version="metadata-only/v2"),
        lambda v: v["completeness"].update(attachments="not_requested"),
        lambda v: v["source_snapshot"]["list"].update(collected=False),
        lambda v: v["source_snapshot"]["detail"].update(comments_presence="not_returned"),
        lambda v: v["attributes"].update(export_id_mapping="metadata-only/v2"),
    ],
)
def test_collection_metadata_does_not_create_revision_or_vectors(harness, mutation):
    h = harness
    original = h.records(1)[0]
    h.stage([original])
    h.run()
    before = h.embedding.encoded, h.qdrant.writes, deepcopy(h.qdrant.points)
    values = deepcopy(original.values)
    mutation(values)
    changed = replace(original, values=values, content_hash=digest(values))
    h.stage([changed])
    assert h.run()["counts"] == {"unchanged": 1}
    assert (h.embedding.encoded, h.qdrant.writes, h.qdrant.points) == before


@pytest.mark.parametrize(
    "mutation",
    [
        lambda v: v.update(source_project_name="新的项目显示名"),
        lambda v: v.update(source_status_name="新的状态显示名"),
        lambda v: v["attributes"].update(solution_text="新增处理方案"),
    ],
)
def test_same_stamp_business_changes_create_one_revision(harness, mutation):
    h = harness
    original = h.records(1)[0]
    h.stage([original])
    h.run()
    values = deepcopy(original.values)
    mutation(values)
    changed = replace(original, values=values, content_hash=digest(values))
    h.stage([changed])
    assert h.run()["counts"] == {"revised": 1}
    h.stage([changed])
    assert h.run()["counts"] == {"unchanged": 1}


def test_same_stamp_relation_changes_and_unordered_sets(harness):
    h = harness
    original = h.records(1)[0]
    values = deepcopy(original.values)
    values["attributes"]["product_ids"] = ["product_a", "product_b"]
    original = replace(original, values=values, content_hash=digest(values))
    h.stage([original])
    h.run()
    changed = replace(
        original,
        relations=(
            {
                "target_external_id": "new_target",
                "source_relation_type": "relates",
                "source_direction": "outgoing",
            },
        ),
    )
    h.stage([changed])
    assert h.run()["counts"] == {"revised": 1}
    values = deepcopy(changed.values)
    values["attributes"]["product_ids"].reverse()
    reordered = replace(
        changed,
        values=values,
        content_hash=digest(values),
        relations=changed.relations + changed.relations,
    )
    h.stage([reordered])
    assert h.run()["counts"] == {"unchanged": 1}


def test_older_content_cannot_replace_latest_same_stamp_revision(harness):
    h = harness
    a = h.records(1)[0]
    h.stage([a])
    h.run()
    b = same_stamp_revised(a)
    h.stage([b])
    h.run()
    values = deepcopy(a.values)
    values["source_update_stamp_raw"] -= 1
    old = replace(a, values=values, content_hash=digest(values), document_kind="ticket")
    before = deepcopy(h.qdrant.points)
    h.stage([old])
    assert h.run()["counts"] == {"stale": 1}
    assert h.qdrant.points == before
    current = h.db.execute_one(
        f"select current_revision_id,document_kind from {h.repo.t('document')}"
    )
    assert current["document_kind"] == "defect"
    assert h.repo.revision(current["current_revision_id"])["title"] == b.values["title"]


def test_same_stamp_page_rollback_and_replay_are_atomic(harness, monkeypatch):
    h = harness
    a, other = h.records(1, 2)
    h.stage([a, other])
    h.run()
    b = same_stamp_revised(a)
    run = h.repo.begin_collection(
        h.binding["id"], "2026-10-27T01:00:00+00:00", through=date(2024, 1, 1)
    )
    checkpoint = {
        "kind": "defect",
        "issue_type_id": "type_1",
        "first": "2024-01-01",
        "last": "2024-01-01",
        "next_cursor": None,
        "enumerated": 2,
        "expected": 2,
    }
    stage = h.repo.stage

    def fail_second(run_id, record):
        if record.external_id == other.external_id:
            raise RuntimeError("synthetic page database failure")
        return stage(run_id, record)

    monkeypatch.setattr(h.repo, "stage", fail_second)
    with pytest.raises(RuntimeError):
        h.repo.commit_collection_page(run["id"], (b, other), checkpoint)
    assert list(h.repo.candidates(run["id"])) == []
    assert h.repo.summary(run["id"])["checkpoint"] == {"processed": 0, "total": 0}
    monkeypatch.setattr(h.repo, "stage", stage)
    first = h.repo.commit_collection_page(run["id"], (b, other), checkpoint)
    second = h.repo.commit_collection_page(run["id"], (b, other), checkpoint)
    assert first == second and len(first) == 1  # 相同事件 ID 支持日志重放去重。
    assert h.repo.summary(run["id"])["checkpoint"] == {"processed": 2, "total": 2}
    document_id = first[0]["document_id"]
    revisions = h.db.execute(
        f"select id from {h.repo.t('document_revision')} where document_id=?", (document_id,)
    )
    assert len(revisions) == 2


def test_same_stamp_kind_change_moves_only_document_membership(harness):
    h = harness
    a = h.records(1)[0]
    h.stage([a])
    h.run()
    values = deepcopy(a.values)
    values["attributes"]["document_kind"] = "ticket"
    b = replace(a, values=values, content_hash=digest(values), document_kind="ticket")
    h.stage([b])
    assert h.run()["counts"] == {"revised": 1}
    assert h.index()["expected_document_count"] == 0
    assert h.index("ticket")["expected_document_count"] == 1


def test_same_incremental_index_cannot_return_ranking_after_input_revision_changes(
    harness, monkeypatch
):
    from backend.tests.support.knowledge_reranker import SyntheticReranker

    h = harness
    record = h.records(1)[0]
    h.stage([record])
    h.run()
    before = h.index()
    reranker = SyntheticReranker()
    original = reranker.rank

    def update_during_inference(query, documents):
        result = original(query, documents)
        h.stage([revised(record)])
        h.run()
        assert h.index()["id"] == before["id"]
        return result

    monkeypatch.setattr(reranker, "rank", update_during_inference)
    service = VectorService(h.vectors, h.embedding, h.qdrant, reranker=reranker)
    with pytest.raises(VectorError, match="knowledge_vector_(source_changed|point_conflict)"):
        service.query(
            before["code"],
            h.binding["configuration_json"]["base_codes"]["defect"],
            "合成",
            compare=True,
        )
