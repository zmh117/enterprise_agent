"""Synthetic ranking, window and dependency contracts; not a semantic benchmark."""

import json
import time

import httpx
import pytest

from app.modules.knowledge.application.candidates import CandidatePool
from app.modules.knowledge.application.ranking import rerank
from app.modules.knowledge.domain.rerank_contract import (
    MAX_BATCH_PAIRS,
    MAX_BATCH_TOKENS,
    MAX_DOCUMENT_TOKENS,
    MAX_PAIR_TOKENS,
    checked_request,
    checked_result,
)
from app.modules.knowledge.domain.vector_contract import DEADLINE_HEADER, VectorError, fingerprint
from app.modules.knowledge.infrastructure.reranker_client import RerankerClient
from app.shared.io_deadline import io_deadline
from backend.tests.support.knowledge_reranker import SyntheticReranker
from services.knowledge_embedding.online_queue import InferenceDeadline
from services.knowledge_reranker.engine import microbatches, prepare_pairs, window
from app.modules.knowledge.application.retrieval_timing import RetrievalTiming, retrieval_timing
from app.shared.knowledge_limits import KNOWLEDGE_REQUEST_ID_HEADER


@pytest.mark.parametrize("status", [200, 408, 429, 503])
def test_reranker_timing_crosses_success_and_failure_without_changing_result(status):
    from app.modules.knowledge.domain.rerank_contract import input_hashes
    from app.modules.knowledge.infrastructure.reranker_profile import profile

    timing = RetrievalTiming(int((time.time() + 10) * 1000))
    measured = {"queue_ms": 32.5, "compute_ms": 14.2, "state": "finished"}

    def remote(request):
        if request.url.path == "/profile":
            return httpx.Response(
                200, json={"profile": profile(), "profile_hash": fingerprint(profile())}
            )
        assert request.headers[KNOWLEDGE_REQUEST_ID_HEADER] == timing.request_id
        code = {
            408: "knowledge_rerank_read_timeout",
            429: "knowledge_rerank_busy",
            503: "knowledge_rerank_unavailable",
        }.get(status)
        value = (
            {"error_code": code}
            if code
            else {
                "profile_hash": fingerprint(profile()),
                "input_hashes": input_hashes("synthetic", [["document"]]),
                "scores": [1.0],
                "token_counts": [8],
                "truncated": [False],
            }
        )
        return httpx.Response(status, json={**value, "timing": measured})

    client = RerankerClient(transport=httpx.MockTransport(remote))
    try:
        with retrieval_timing(timing), io_deadline(10):
            if status == 200:
                assert "timing" not in client.rank("synthetic", [["document"]])
            else:
                with pytest.raises(VectorError):
                    client.rank("synthetic", [["document"]])
        assert timing.snapshot()["rerank"] == measured
    finally:
        client.http.close()


@pytest.mark.parametrize(
    "value",
    [
        None,
        {"query": "synthetic-private"},
        {"queue_ms": 1, "compute_ms": 1, "state": []},
        {"queue_ms": -1, "compute_ms": 1, "state": "finished"},
        {"queue_ms": 1, "compute_ms": float("inf"), "state": "finished"},
    ],
)
def test_untrusted_rerank_timing_is_unknown_not_copied(value):
    timing = RetrievalTiming(int((time.time() + 10) * 1000))
    timing.observe_rerank(value)
    assert timing.snapshot()["rerank"] is None
    assert "synthetic-private" not in json.dumps(timing.snapshot())


class Tokenizer:
    cls_token_id = -1
    sep_token_id = -2

    def encode(self, text, *, add_special_tokens, truncation, verbose=False):
        assert not add_special_tokens and not truncation
        return list(map(ord, text))

    def num_special_tokens_to_add(self, *, pair):
        assert pair
        return 4


def pool(count=60):
    documents, rows = [], {}
    for i in range(count):
        evidence = []
        for j in range(3):
            chunk = f"chunk-{i:03}-{j}"
            evidence.append({"chunk_id": chunk})
            rows[chunk] = {"embedding_text": f"synthetic block {i} {j}", "embedding_hash": chunk}
        documents.append(
            {"document_id": f"doc-{i:03}", "retrieval_score": 1 / (i + 1), "evidence": evidence}
        )
    return CandidatePool(documents, rows, [])


def test_low_retrieval_score_promoted_max50_two_blocks_and_private_projection():
    candidates, client = pool(), SyntheticReranker()
    client.scores = [0.0] * 49 + [10.0]
    observed = []
    original = client.rank

    def rank(query, documents):
        observed.extend(documents)
        return original(query, documents)

    client.rank = rank
    result = rerank(candidates, "synthetic query", client)
    assert result.documents[0]["document_id"] == "doc-049"
    assert result.documents[0]["retrieval_score"] < 0.15
    assert len(result.documents) == 50 and len(observed) == 50
    assert all(len(blocks) == 2 for blocks in observed)
    assert "synthetic" not in json.dumps(result.documents)
    assert "scores" not in json.dumps(result.documents)
    assert client.calls == 1


def test_stable_ties_and_empty_pool_does_not_call_dependency():
    candidates, client = pool(3), SyntheticReranker()
    for doc in candidates.documents:
        doc["retrieval_score"] = 0.01
    candidates.documents.reverse()
    assert [d["document_id"] for d in rerank(candidates, "query", client).documents] == [
        "doc-000",
        "doc-001",
        "doc-002",
    ]
    assert not rerank(pool(0), "query", client).documents and client.calls == 1


def test_document_window_equal_split_redistributes_and_preserves_query():
    assert window([[1, 2], list(range(10, 30))], 10, -2) == ([1, 2, -2, *range(10, 17)], True)
    query = "Q" * (MAX_PAIR_TOKENS - 15)
    pairs = prepare_pairs(Tokenizer(), query, [["a" * 30, "b" * 30]], InferenceDeadline([]))
    assert len(pairs.inputs[0]) == MAX_PAIR_TOKENS and pairs.truncated == [True]
    assert pairs.inputs[0][1 : 1 + len(query)] == [ord("Q")] * len(query)
    pairs = prepare_pairs(Tokenizer(), "Q", [["a" * 1800]], InferenceDeadline([]))
    assert len(pairs.inputs[0]) == min(MAX_DOCUMENT_TOKENS, MAX_PAIR_TOKENS - 5) + 5
    with pytest.raises(VectorError, match="input_limit"):
        prepare_pairs(Tokenizer(), "Q" * MAX_PAIR_TOKENS, [["a"]], InferenceDeadline([]))


def test_microbatch_bound_includes_padding_and_preserves_order():
    inputs = [
        [i] * n
        for i, n in enumerate(
            [5] * 10 + [MAX_PAIR_TOKENS, 50, MAX_PAIR_TOKENS, MAX_PAIR_TOKENS // 2]
        )
    ]
    batches = list(microbatches(inputs))
    assert [p for batch in batches for p in batch] == inputs
    assert all(len(b) <= MAX_BATCH_PAIRS for b in batches)
    assert all(max(map(len, b)) * len(b) <= MAX_BATCH_TOKENS for b in batches)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda v: v.update(profile_hash="different"),
        lambda v: v.update(input_hashes=["different"]),
        lambda v: v.update(scores=[]),
        lambda v: v.update(scores=[float("nan")]),
        lambda v: v.update(scores=[float("inf")]),
        lambda v: v.update(scores=[True]),
        lambda v: v.update(scores=[10**1000]),
        lambda v: v.update(token_counts=[MAX_PAIR_TOKENS + 1]),
        lambda v: v.update(truncated=[1]),
        lambda v: v.update(text="private synthetic text"),
    ],
)
def test_reject_invalid_results_without_echo(mutate):
    client = SyntheticReranker()
    value = client.rank("private synthetic query", [["private synthetic block"]])
    mutate(value)
    with pytest.raises(VectorError) as caught:
        checked_result(
            value,
            profile_hash=client.profile_hash,
            query="private synthetic query",
            documents=[["private synthetic block"]],
        )
    assert str(caught.value) == "knowledge_rerank_result_invalid"


@pytest.mark.parametrize(
    "update",
    [
        {"documents": []},
        {"documents": [["x"]] * 51},
        {"documents": [["x"] * 3]},
        {"documents": [["x" * 1801]]},
        {"query": "\ud800"},
        {"query": " "},
        {"query": "x" * 2001},
        {"profile_hash": "wrong"},
        {"extra": "private"},
    ],
)
def test_request_shape_and_text_bounds(update):
    request = {"profile_hash": "hash", "query": "query", "documents": [["block"]], **update}
    with pytest.raises(VectorError, match="knowledge_rerank_input_invalid"):
        checked_request(request, "hash")


@pytest.mark.parametrize(
    "failure", ["busy", "timeout", "profile", "threads", "result", "unavailable"]
)
def test_client_no_retry_or_fallback_and_common_deadline(failure):
    seen = []
    client = None

    def respond(request):
        seen.append(request)
        assert DEADLINE_HEADER in request.headers
        assert request.extensions["timeout"]["read"] <= 0.5
        if failure == "profile":
            return httpx.Response(200, json={"profile": {"wrong": True}})
        if failure == "threads":
            old_profile = {**client.profile, "threads": 8}
            return httpx.Response(
                200, json={"profile": old_profile, "profile_hash": fingerprint(old_profile)}
            )
        if request.url.path == "/profile":
            return httpx.Response(
                200, json={"profile": client.profile, "profile_hash": client.profile_hash}
            )
        if failure == "timeout":
            raise httpx.ReadTimeout("private provider text")
        if failure == "busy":
            return httpx.Response(429, json={"error_code": "knowledge_rerank_busy"})
        if failure == "unavailable":
            return httpx.Response(503, text="private provider text")
        return httpx.Response(200, json={"raw": "private provider text"})

    client = RerankerClient(transport=httpx.MockTransport(respond))
    try:
        with io_deadline(0.5), pytest.raises(VectorError) as caught:
            client.rank("synthetic query", [["synthetic block"]])
        codes = {
            "busy": "busy",
            "timeout": "read_timeout",
            "profile": "profile_mismatch",
            "threads": "profile_mismatch",
            "result": "result_invalid",
            "unavailable": "unavailable",
        }
        assert caught.value.code == "knowledge_rerank_" + codes[failure]
        assert len(seen) == (1 if failure in {"profile", "threads"} else 2)
    finally:
        client.http.close()


def test_microbatch_cancellation_stops_before_next_model_call(monkeypatch):
    from contextlib import nullcontext
    import sys
    from types import SimpleNamespace
    from services.knowledge_reranker.engine import RerankerEngine

    deadline, calls = InferenceDeadline([]), []
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(inference_mode=nullcontext))
    tokenizer = Tokenizer()
    tokenizer.pad = lambda values, **kwargs: {"values": values}

    class Logits:
        def reshape(self, *args):
            return self

        def float(self):
            return self

        def tolist(self):
            return [0.0] * len(calls[-1])

    def model(**kwargs):
        calls.append(kwargs["values"])
        deadline.cancelled.set()
        return SimpleNamespace(logits=Logits())

    engine = RerankerEngine.__new__(RerankerEngine)
    engine.tokenizer, engine.model = tokenizer, model
    with pytest.raises(TimeoutError):
        engine.rank("Q", [["a" * 1800]] * 50, deadline)
    assert len(calls) == 1


def test_bounded_http_encodes_full_chinese_candidate_pool_as_utf8(monkeypatch):
    from app.modules.knowledge.infrastructure import vector_clients

    documents = [["字" * 1800, "文" * 1800]] * 50
    expected = SyntheticReranker().rank("查询", documents)
    client = RerankerClient()
    observed = []

    def request(method, url, **kwargs):
        if url.endswith("/profile"):
            value = {"profile": client.profile, "profile_hash": client.profile_hash}
        else:
            encoded = kwargs["content"]
            observed.append(len(encoded))
            assert len(encoded) < 1024 * 1024
            assert json.loads(encoded)["documents"] == documents
            value = expected
        return 200, json.dumps(value).encode()

    monkeypatch.setattr(vector_clients, "request_bytes", request)
    try:
        with io_deadline(1):
            assert client.rank("查询", documents) == expected
        assert len(observed) == 1
    finally:
        client.http.close()


def test_length_grouped_batches_restore_original_document_score_order(monkeypatch):
    from contextlib import nullcontext
    import sys
    from types import SimpleNamespace
    from services.knowledge_reranker.engine import RerankerEngine

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(inference_mode=nullcontext))
    tokenizer = Tokenizer()
    tokenizer.pad = lambda values, **kwargs: {"values": values}
    observed = []

    class Logits(list):
        def reshape(self, *args):
            return self

        def float(self):
            return self

        def tolist(self):
            return list(self)

    def model(**kwargs):
        inputs = [row["input_ids"] for row in kwargs["values"]]
        observed.extend(map(len, inputs))
        return SimpleNamespace(logits=Logits(float(ids[-2]) for ids in inputs))

    engine = RerankerEngine.__new__(RerankerEngine)
    engine.tokenizer, engine.model = tokenizer, model
    documents = [[chr(97 + i) * ((i + 1) * 150)] for i in range(12)]
    result = engine.rank("Q", documents, InferenceDeadline([]))
    assert observed == sorted(observed, reverse=True)
    assert result["scores"] == [float(97 + i) for i in range(12)]
    assert result["token_counts"] == sorted(result["token_counts"])
