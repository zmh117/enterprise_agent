from app.modules.knowledge.infrastructure.chunk_repository import ChunkRepository
from app.modules.knowledge.infrastructure.vector_repository import VectorRepository
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import threading
import uuid

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from app.modules.knowledge.application.chunk_service import ChunkService
from app.modules.knowledge.domain.chunking import DEFAULT_PROFILE
from app.modules.knowledge.infrastructure.storage import source_lock, table
from app.modules.knowledge.infrastructure.vector_clients import (
    EmbeddingClient,
    InternalHttp,
    QdrantClient,
)
from app.modules.knowledge.domain.vector_contract import VectorError, fingerprint, validate_vector
from app.modules.knowledge.infrastructure.embedding_profile import profile
from app.modules.knowledge.domain.vector_points import payload, point_id
from app.modules.knowledge.application.vector_service import VectorService
from app.shared.database import Database, assert_external_io_allowed, default_migrations_dir
from app.shared.migrations import Migrator, deployable_migration_catalog, load_migration_catalog
from backend.tests.test_knowledge_chunks import import_rows, source_fingerprint
from backend.tests.test_knowledge_import import export_row
from services.knowledge_embedding.api import create_app
from services.knowledge_embedding.model_files import verify_file, verify_model


VECTOR = [1.0] + [0.0] * 1023


class SyntheticEmbedding:
    profile_hash = fingerprint(profile())

    def __init__(self):
        self.encoded = 0

    def check(self):
        assert_external_io_allowed("synthetic_embedding")

    def call(self, texts, *, encode=False):
        self.check()
        result = {"token_counts": [min(2000, len(t) + 2) for t in texts]}
        if encode:
            self.encoded += len(texts)
            result["vectors"] = [VECTOR[:] for _ in texts]
        return result


class SyntheticQdrant:
    def __init__(self):
        self.points = {}
        self.writes = 0
        self.search_limits = []

    def check(self, index):
        assert_external_io_allowed("synthetic_qdrant")

    ensure = check

    def retrieve(self, index, ids):
        self.check(index)
        return {key: deepcopy(self.points[key]) for key in ids if key in self.points}

    def upsert(self, index, points):
        self.check(index)
        self.writes += len(points)
        self.points.update({p["id"]: deepcopy(p) for p in points})

    def count(self, index):
        return len(self.points)

    def search(self, index, vector, limit):
        self.search_limits.append(limit)
        return [
            dict(p, score=1.0) for p in sorted(self.points.values(), key=lambda p: p["id"])[:limit]
        ]


@pytest.fixture
def prepared(tmp_path):
    db = Database("sqlite:///:memory:")
    Migrator(db, default_migrations_dir(), migrator_build="knowledge-vector-test").run()
    import_rows(db, tmp_path, [export_row(), export_row(2)])
    chunks = ChunkService(ChunkRepository(db)).run(
        knowledge_base_code="synthetic_base", expected_count=2, commit=True
    )["counts"]["chunks"]
    service = VectorService(VectorRepository(db), SyntheticEmbedding(), SyntheticQdrant())
    snapshot = service.repository.snapshot(
        service.repository.scope("synthetic_base"), DEFAULT_PROFILE.fingerprint, 2, chunks
    )
    yield db, service, snapshot
    db.close()


def test_preflight_build_replay_and_no_source_writes(prepared):
    db, service, snapshot = prepared
    before = source_fingerprint(db)
    preview = service.preflight(snapshot, benchmark=True)
    assert preview["benchmark"]["chunks"] == snapshot["expected_chunk_count"]
    assert not db.execute('select * from "knowledge.vector_index"')
    first = service.build("synthetic-v1", snapshot)
    replay = service.build("synthetic-v1", snapshot)
    assert first["encoded"] == replay["reused"] == snapshot["expected_chunk_count"]
    assert replay["encoded"] == 0
    assert source_fingerprint(db) == before
    assert not db.execute("pragma foreign_key_check")
    result = service.query("synthetic-v1", "synthetic_base", "合成查询", top_k=3)
    assert len(result["documents"]) == 2 and result["partial"]
    assert "embedding_text" not in json.dumps(result)


def test_upsert_before_checkpoint_crash_resumes_without_reembedding(prepared, monkeypatch):
    db, service, snapshot = prepared
    original = service.repository.checkpoint

    def interrupt(index, rows, state, **kwargs):
        if state == "INDEXED":
            raise RuntimeError("synthetic hidden text")
        return original(index, rows, state, **kwargs)

    monkeypatch.setattr(service.repository, "checkpoint", interrupt)
    with pytest.raises(VectorError, match="^knowledge_vector_build_failed$"):
        service.build("synthetic-v1", snapshot)
    assert service.repository.get("synthetic-v1")["state"] == "FAILED"
    monkeypatch.setattr(service.repository, "checkpoint", original)
    resumed = service.build("synthetic-v1", snapshot)
    assert resumed["encoded"] == 0 and resumed["reused"] == snapshot["expected_chunk_count"]


def test_missing_indexed_point_repaired_but_conflicting_point_not_overwritten(prepared):
    db, service, snapshot = prepared
    service.build("synthetic-v1", snapshot)
    key = next(iter(service.qdrant.points))
    del service.qdrant.points[key]
    assert service.build("synthetic-v1", snapshot)["encoded"] == 1
    service.qdrant.points[key]["payload"]["profile_hash"] = "wrong"
    writes = service.qdrant.writes
    with pytest.raises(VectorError, match="point_conflict"):
        service.build("synthetic-v1", snapshot)
    assert service.qdrant.writes == writes


def test_extra_point_count_cannot_be_ready(prepared):
    db, service, snapshot = prepared
    service.qdrant.points[str(uuid.uuid4())] = {"id": "extra"}
    with pytest.raises(VectorError, match="count_mismatch"):
        service.build("synthetic-v1", snapshot)
    assert service.repository.get("synthetic-v1")["state"] == "FAILED"


def test_source_mutation_during_upsert_stops_ready(prepared, monkeypatch):
    db, service, snapshot = prepared
    original = service.qdrant.upsert

    def change(index, points):
        original(index, points)
        db.execute("update \"knowledge.knowledge_base_document\" set state='removed'")

    monkeypatch.setattr(service.qdrant, "upsert", change)
    with pytest.raises(VectorError):
        service.build("synthetic-v1", snapshot)
    assert service.repository.get("synthetic-v1")["state"] == "FAILED"


def test_index_identity_and_partial_manifest_conflicts(prepared):
    db, service, snapshot = prepared
    index = service.repository.create("synthetic-v1", snapshot)
    service.repository.manifest(index)
    db.execute('update "knowledge.vector_index_item" set embedding_text_hash=?', ("0" * 64,))
    with pytest.raises(VectorError, match="manifest_conflict"):
        service.build("synthetic-v1", snapshot)
    with pytest.raises(VectorError, match="index_conflict"):
        service.build("synthetic-v1", dict(snapshot, corpus_hash="0" * 64))


def test_single_writer_and_stale_membership_filter(prepared):
    db, service, snapshot = prepared
    with source_lock(db, "vector-index:synthetic-v1"):
        with pytest.raises(ValueError, match="source_import_busy"):
            service.build("synthetic-v1", snapshot)
    service.build("synthetic-v1", snapshot)
    db.execute("update \"knowledge.knowledge_base_document\" set state='removed'")
    result = service.query("synthetic-v1", "synthetic_base", "合成查询")
    assert result["documents"] == [] and result["partial"]


def test_new_revision_filters_stale_points_and_requires_new_index_version(prepared, tmp_path):
    db, service, snapshot = prepared
    service.build("synthetic-v1", snapshot)
    row = export_row()
    row[0]["desc"] += "合成新版本"
    row[0]["server_update_stamp"] += 100
    import_rows(db, tmp_path, [row, export_row(2)])
    assert len(service.query("synthetic-v1", "synthetic_base", "合成查询")["documents"]) == 1
    ChunkService(ChunkRepository(db)).run(
        knowledge_base_code="synthetic_base", expected_count=2, commit=True
    )
    current = service.repository.snapshot(
        snapshot["knowledge_base_id"],
        DEFAULT_PROFILE.fingerprint,
        2,
        snapshot["expected_chunk_count"],
    )
    with pytest.raises(VectorError, match="index_conflict"):
        service.build("synthetic-v1", current)


def test_query_deduplication_expands_until_enough_documents(prepared, monkeypatch):
    db, service, snapshot = prepared
    service.build("synthetic-v1", snapshot)
    index = service.repository.get("synthetic-v1")
    first = list(service.repository.rows(index["knowledge_base_id"], index["chunk_profile_hash"]))[
        0
    ]
    # 仅合成候选；前 80 个都定位同文档，第 81 个命中第二文档。
    second = next(
        r
        for r in service.repository.rows(index["knowledge_base_id"], index["chunk_profile_hash"])
        if r["document_id"] != first["document_id"]
    )
    candidates = []
    mapping = {}
    for i in range(81):
        row = dict(first if i < 80 else second, id=str(uuid.uuid4()))
        mapping[row["id"]] = row
        candidates.append(
            {"id": point_id(index, row), "payload": payload(index, row), "score": 1 - i * 0.001}
        )
    monkeypatch.setattr(
        service.repository, "evidence_many", lambda idx, ids: {cid: mapping[cid] for cid in ids}
    )
    calls = []

    def search(idx, vector, limit):
        calls.append(limit)
        return candidates[:limit]

    monkeypatch.setattr(service.qdrant, "search", search)
    result = service.query("synthetic-v1", "synthetic_base", "合成查询", top_k=2)
    assert calls == [20, 40, 80, 160]
    assert len(result["documents"]) == 2 and not result["partial"]
    assert len(result["documents"][0]["evidence"]) == 3


@pytest.mark.parametrize(
    "vector",
    [[0.0] * 1024, [1.0] * 1024, [float("nan")] + [0.0] * 1023, [True] + [0.0] * 1023, [1.0]],
)
def test_invalid_vectors(vector):
    with pytest.raises(VectorError):
        validate_vector(vector)


def test_client_profile_order_retry_redirect_and_transaction_boundary(monkeypatch):
    attempts = []

    def handler(request):
        attempts.append(request)
        return httpx.Response(503 if len(attempts) < 3 else 200, json={"ok": True})

    monkeypatch.setattr(
        "app.modules.knowledge.infrastructure.vector_clients.time.sleep", lambda _: None
    )
    http = InternalHttp("http://knowledge-embedding:8096", transport=httpx.MockTransport(handler))
    assert http.request("GET", "/health") == {"ok": True} and len(attempts) == 3
    http.close()
    client = EmbeddingClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200,
                json={
                    "profile_hash": fingerprint(profile()),
                    "input_hashes": ["wrong"],
                    "token_counts": [2],
                    "vectors": [VECTOR],
                },
            )
        )
    )
    with pytest.raises(VectorError, match="result_invalid"):
        client.call(["synthetic"], encode=True)
    client.http.close()
    http = InternalHttp(
        "http://knowledge-embedding:8096",
        transport=httpx.MockTransport(
            lambda r: httpx.Response(302, headers={"location": "https://example.invalid"})
        ),
    )
    with pytest.raises(VectorError, match="request_rejected"):
        http.request("GET", "/profile")
    http.close()
    with pytest.raises(VectorError, match="endpoint_invalid"):
        InternalHttp("https://example.invalid")


def test_network_io_is_rejected_inside_transaction(prepared):
    db, service, snapshot = prepared
    calls = []
    client = InternalHttp(
        "http://knowledge-embedding:8096",
        transport=httpx.MockTransport(
            lambda request: calls.append(request) or httpx.Response(200, json={})
        ),
    )
    try:
        with db.unit_of_work():
            with pytest.raises(RuntimeError, match="External I/O is not allowed"):
                client.request("GET", "/profile")
        assert calls == []
    finally:
        client.close()


@pytest.mark.parametrize(
    "value",
    [
        {"token_counts": [2, 2], "input_hashes": [fingerprint("synthetic")]},
        {"token_counts": [True], "input_hashes": [fingerprint("synthetic")]},
        {"token_counts": [2], "input_hashes": [fingerprint("synthetic")], "vectors": []},
        {"token_counts": [2], "input_hashes": [fingerprint("synthetic")], "vectors": [[0] * 1024]},
    ],
)
def test_embedding_client_rejects_malformed_counts_and_vectors(value):
    client = EmbeddingClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"profile_hash": fingerprint(profile()), **value})
        )
    )
    try:
        with pytest.raises(VectorError, match="result_invalid"):
            client.call(["synthetic"], encode=True)
    finally:
        client.http.close()


def test_paged_manifest_covers_more_than_32_rows(tmp_path):
    db = Database("sqlite:///:memory:")
    try:
        Migrator(db, default_migrations_dir(), migrator_build="knowledge-vector-pages").run()
        import_rows(db, tmp_path, [export_row(i) for i in range(1, 36)])
        count = ChunkService(ChunkRepository(db)).run(
            knowledge_base_code="synthetic_base", expected_count=35, commit=True
        )["counts"]["chunks"]
        service = VectorService(VectorRepository(db), SyntheticEmbedding(), SyntheticQdrant())
        snapshot = service.repository.snapshot(
            service.repository.scope("synthetic_base"), DEFAULT_PROFILE.fingerprint, 35, count
        )
        assert count > 32
        result = service.build("synthetic-pages", snapshot)
        assert result["verified"] == count
        assert service.build("synthetic-pages", snapshot)["reused"] == count
    finally:
        db.close()


def test_safe_token_limit_code_is_preserved_without_remote_details():
    client = EmbeddingClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                422,
                json={
                    "error_code": "knowledge_embedding_token_limit",
                    "input": "hidden synthetic text",
                },
            )
        )
    )
    try:
        with pytest.raises(VectorError, match="^knowledge_embedding_token_limit$"):
            client.call(["synthetic"])
    finally:
        client.http.close()


def test_qdrant_ownership_conflict_and_unconfirmed_write():
    index = {"id": str(uuid.uuid4()), "profile_hash": "a" * 64, "corpus_hash": "b" * 64}
    index["collection_name"] = "knowledge_" + uuid.UUID(index["id"]).hex
    client = QdrantClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"result": {"status": "acknowledged"}})
        )
    )
    with pytest.raises(VectorError, match="collection_conflict"):
        client.ensure(index)
    with pytest.raises(VectorError, match="write_unconfirmed"):
        client.upsert(index, [])
    client.http.close()


class SyntheticEngine:
    def count(self, texts):
        return [len(t) + 2 for t in texts]

    def encode(self, texts):
        return [VECTOR[:] for t in texts]


def test_embedding_api_limits_safe_errors_and_fingerprint():
    with TestClient(create_app(SyntheticEngine())) as client:

        def post(texts, **kw):
            return client.post(
                "/embed", json={"texts": texts, "profile_hash": fingerprint(profile()), **kw}
            )

        assert client.get("/ready").status_code == 200
        assert post(["合成测试"]).json()["vectors"] == [VECTOR]
        for values in ([], [""], [42], ["secret synthetic" * 2000], ["x"] * 9):
            response = post(values)
            assert response.status_code == 422 and "synthetic" not in response.text
        assert post(["x"], profile_hash="wrong").status_code == 422
        assert post(["x" * 4095]).json()["error_code"] == "knowledge_embedding_token_limit"
        assert post(["x" * 2000] * 5).json()["error_code"] == "knowledge_embedding_batch_limit"
        assert (
            client.post(
                "/tokenize",
                json={"texts": ["x" * 2000] * 5, "profile_hash": fingerprint(profile())},
            ).status_code
            == 200
        )
        assert client.post("/embed", content=b"x" * (256 * 1024 + 1)).status_code == 413
        assert client.post("/embed", content=b"{broken-secret").status_code == 422


def test_embedding_api_busy_and_engine_error_do_not_echo():
    entered, release = threading.Event(), threading.Event()

    class Blocked(SyntheticEngine):
        def encode(self, texts):
            entered.set()
            release.wait(5)
            raise RuntimeError("hidden synthetic text")

    with TestClient(create_app(Blocked())) as client:
        request = {"texts": ["synthetic"], "profile_hash": fingerprint(profile())}
        responses = []
        thread = threading.Thread(
            target=lambda: responses.append(client.post("/embed", json=request))
        )
        thread.start()
        assert entered.wait(3)
        try:
            assert client.post("/embed", json=request).status_code == 429
        finally:
            release.set()
            thread.join(5)
        assert responses[0].status_code == 500 and "hidden" not in responses[0].text


def test_model_file_hash_symlink_missing_and_engine_unavailable(tmp_path, monkeypatch):
    file = tmp_path / "synthetic.bin"
    file.write_bytes(b"synthetic")
    expected = {"size": 9, "sha256": hashlib.sha256(b"synthetic").hexdigest()}
    verify_file(file, expected)
    with pytest.raises(VectorError):
        verify_file(file, dict(expected, sha256="0" * 64))
    link = tmp_path / "link"
    link.symlink_to(file)
    with pytest.raises(VectorError):
        verify_file(link, expected)
    with pytest.raises(VectorError):
        verify_model(tmp_path / "missing")
    monkeypatch.setattr(
        "services.knowledge_embedding.engine.EmbeddingEngine",
        lambda: (_ for _ in ()).throw(RuntimeError("hidden")),
    )
    with TestClient(create_app()) as client:
        assert client.get("/ready").status_code == 503
        assert client.post("/embed", json={}).status_code == 503


def test_compose_runtime_isolation_and_valid_tmpfs():
    config = yaml.load(
        (Path(__file__).resolve().parents[2] / "knowledge/compose.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    services = config["services"]
    assert config["networks"]["knowledge-internal"]["internal"] == "true"
    for name in ("knowledge-embedding", "knowledge-qdrant", "knowledge-ops"):
        assert services[name]["networks"] == ["knowledge-internal"]
        assert not services[name].get("ports")
    for name in ("knowledge-embedding", "knowledge-model-prepare", "knowledge-ops"):
        assert len(services[name]["tmpfs"]) == 1
        assert services[name]["tmpfs"][0].startswith("/tmp:")
    assert services["knowledge-model-prepare"]["networks"] == ["provider-egress"]
    assert not services["knowledge-model-prepare"].get("secrets")
    assert not services["knowledge-model-prepare"].get("environment")
    assert services["knowledge-embedding"]["volumes"] == ["knowledge-models:/models:ro"]
    assert not services["knowledge-ops"].get("secrets")


@pytest.mark.skipif(
    not os.getenv("KNOWLEDGE_TEST_POSTGRES_DSN") or not os.getenv("KNOWLEDGE_TEST_QDRANT_URL"),
    reason="requires isolated PostgreSQL and Qdrant",
)
def test_real_postgres_qdrant_replay_constraints_and_repair(tmp_path):
    db = Database(os.environ["KNOWLEDGE_TEST_POSTGRES_DSN"])
    target = os.environ["KNOWLEDGE_TEST_QDRANT_URL"]
    assert httpx.URL(target).host in {"127.0.0.1", "knowledge-qdrant-test"}
    delegate = httpx.HTTPTransport()

    def route(request):
        request.url = httpx.URL(target).copy_with(path=request.url.path, query=request.url.query)
        return delegate.handle_request(request)

    qdrant = QdrantClient(transport=httpx.MockTransport(route))
    try:
        catalog = deployable_migration_catalog(load_migration_catalog(default_migrations_dir()))
        migrated = Migrator(
            db, default_migrations_dir(), migrator_build="knowledge-vector-isolated"
        ).run()
        assert migrated.head == catalog[-1].version
        code = "synthetic_" + uuid.uuid4().hex
        import_rows(db, tmp_path, [export_row(), export_row(2)], source=code, base=code)
        count = ChunkService(ChunkRepository(db)).run(
            knowledge_base_code=code, expected_count=2, commit=True
        )["counts"]["chunks"]
        service = VectorService(VectorRepository(db), SyntheticEmbedding(), qdrant)
        snapshot = service.repository.snapshot(
            service.repository.scope(code), DEFAULT_PROFILE.fingerprint, 2, count
        )
        competitor = Database(os.environ["KNOWLEDGE_TEST_POSTGRES_DSN"])
        try:
            with source_lock(db, "vector-index:" + code):
                with pytest.raises(ValueError, match="source_import_busy"):
                    VectorService(VectorRepository(competitor), SyntheticEmbedding(), qdrant).build(
                        code, snapshot
                    )
        finally:
            competitor.close()
        assert service.build(code, snapshot)["encoded"] == count
        assert service.build(code, snapshot)["encoded"] == 0
        index = service.repository.get(code)
        assert isinstance(index["profile"], dict)
        row = next(service.repository.rows(index["knowledge_base_id"], index["chunk_profile_hash"]))
        qdrant.http.request(
            "POST",
            qdrant.path(index) + "/points/delete?wait=true",
            {"points": [point_id(index, row)]},
        )
        assert service.build(code, snapshot)["encoded"] == 1
        assert len(service.query(code, code, "synthetic", top_k=2)["documents"]) == 2
        with pytest.raises(Exception):
            with db.unit_of_work():
                db.execute(
                    f"update {table(db, 'vector_index')} set state='INVALID' where id=?",
                    (index["id"],),
                )
        with pytest.raises(Exception):
            with db.unit_of_work():
                db.execute(
                    f"update {table(db, 'vector_index_item')} set chunk_id='missing' where index_id=?",
                    (index["id"],),
                )
    finally:
        qdrant.http.close()
        delegate.close()
        db.close()
