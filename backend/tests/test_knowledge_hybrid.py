"""真实协议形状由 MockTransport 验证；不把合成数据当业务召回评测。"""

import json
from copy import deepcopy
import uuid

import httpx
import pytest

from app.modules.knowledge.domain.chunking import KEEP_IDS_PROFILE
from app.modules.knowledge.domain.hybrid import BM25_OPTIONS, HYBRID_CONTRACT, validate_sparse
from app.modules.knowledge.domain.vector_contract import VectorError
from app.modules.knowledge.infrastructure.vector_clients import QdrantClient


def index():
    uid = str(uuid.uuid4())
    return {
        "id": uid,
        "knowledge_base_id": str(uuid.uuid4()),
        "collection_name": "knowledge_" + uuid.UUID(uid).hex,
        "chunk_profile_hash": KEEP_IDS_PROFILE.fingerprint,
        "profile_hash": "a" * 64,
        "corpus_hash": "b" * 64,
    }


@pytest.mark.parametrize("mode", ["hybrid", "bm25", "dense"])
def test_modes_use_same_scope_and_local_bm25(mode):
    calls = []

    def handle(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"result": {"points": []}})

    client = QdrantClient(transport=httpx.MockTransport(handle))
    value = index()
    vector = [1.0] + [0.0] * 1023
    assert client.hybrid_search(value, vector, "合成报工重复", 200, mode=mode) == []
    req = calls[0]
    assert req["filter"]["must"][0]["match"]["value"] == value["id"]
    if mode == "hybrid":
        assert req["query"] == {"fusion": "rrf"}
        assert [p["limit"] for p in req["prefetch"]] == [100, 100]
        assert all(p["filter"] == req["filter"] for p in req["prefetch"])
        lexical = req["prefetch"][1]["query"]
    elif mode == "bm25":
        lexical = req["query"]
    else:
        assert req["using"] == "dense"
        return
    assert lexical["model"] == "qdrant/bm25"
    assert lexical["options"] == BM25_OPTIONS


def test_hybrid_upsert_has_two_vectors_and_no_text_payload():
    calls = []

    def handle(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"result": {"status": "completed"}})

    client = QdrantClient(transport=httpx.MockTransport(handle))
    client.upsert(
        index(),
        [
            {
                "id": str(uuid.uuid4()),
                "payload": {"chunk_id": "synthetic"},
                "vector": [1.0] + [0.0] * 1023,
                "lexical_text": "合成中文报工",
            }
        ],
    )
    point = calls[0]["points"][0]
    assert set(point) == {"id", "payload", "vector"}
    assert set(point["vector"]) == {"dense", "bm25"}
    assert point["payload"] == {"chunk_id": "synthetic"}
    assert point["vector"]["bm25"]["options"] == BM25_OPTIONS


@pytest.mark.parametrize(
    "sparse",
    [
        None,
        {},
        {"indices": [], "values": []},
        {"indices": [1, 1], "values": [1, 1]},
        {"indices": [1], "values": [float("nan")]},
        {"indices": [-1], "values": [1]},
        {"indices": [1], "values": [0]},
    ],
)
def test_invalid_sparse_fails(sparse):
    with pytest.raises(VectorError, match="knowledge_sparse_vector_invalid"):
        validate_sparse(sparse)


def test_one_missing_route_is_not_treated_as_ready():
    point_id = str(uuid.uuid4())

    def handle(request):
        return httpx.Response(
            200,
            json={
                "result": [
                    {"id": point_id, "vector": {"dense": [1.0] + [0.0] * 1023}, "payload": {}}
                ]
            },
        )

    client = QdrantClient(transport=httpx.MockTransport(handle))
    with pytest.raises(VectorError, match="knowledge_sparse_vector_invalid"):
        client.retrieve(index(), [point_id])


@pytest.mark.parametrize("drift", ["none", "weights", "k", "corpus", "sparse", "dense"])
def test_collection_contract_pins_both_routes_and_equal_rrf(drift):
    value = index()
    config = {
        "params": {
            "vectors": {"dense": {"size": 1024, "distance": "Cosine"}},
            "sparse_vectors": {"bm25": {"modifier": "idf"}},
        },
        "metadata": {
            "owner": "enterprise-agent-knowledge/v1",
            "index_id": value["id"],
            "profile_hash": value["profile_hash"],
            "corpus_hash": value["corpus_hash"],
            "retrieval": deepcopy(HYBRID_CONTRACT),
        },
    }
    if drift == "weights":
        config["metadata"]["retrieval"]["weights"] = [2.0, 1.0]
    elif drift == "k":
        config["metadata"]["retrieval"]["k"] = 60
    elif drift == "corpus":
        config["metadata"]["corpus_hash"] = "c" * 64
    elif drift == "sparse":
        config["params"]["sparse_vectors"]["other"] = {"modifier": "idf"}
    elif drift == "dense":
        config["params"]["vectors"]["dense"]["size"] = 768
    client = QdrantClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"result": {"config": config}})
        )
    )
    if drift == "none":
        client.check(value)
    else:
        with pytest.raises(VectorError, match="knowledge_collection_conflict"):
            client.check(value)
