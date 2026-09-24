"""显式本机索引和查询编排；外部 IO 始终在数据库事务之外。"""

from collections.abc import Callable, Iterator
import time
from typing import Any

from app.modules.knowledge.domain.vector_points import batches, payload, point_id
from app.modules.knowledge.application.ports import EmbeddingPort, QdrantPort, VectorRepository
from app.modules.knowledge.domain.vector_contract import (
    MAX_BATCH_TOKENS,
    VectorError,
    fingerprint,
    validate_vector,
)
from app.modules.knowledge.application.candidates import current_documents
from app.modules.knowledge.domain.hybrid import (
    HYBRID_CONTRACT,
    hybrid_index,
    lexical_input,
    validate_sparse,
)


class VectorService:
    def __init__(
        self, repository: VectorRepository, embedding: EmbeddingPort, qdrant: QdrantPort
    ) -> None:
        self.repository = repository
        self.embedding = embedding
        self.qdrant = qdrant

    def grouped(
        self, rows: Iterator[dict[str, Any]]
    ) -> Iterator[tuple[list[dict[str, Any]], list[int]]]:
        for window in batches(rows, 8):
            counts = self.embedding.call([r["embedding_text"] for r in window])["token_counts"]
            group: list[dict[str, Any]] = []
            tokens: list[int] = []
            for row, count in zip(window, counts, strict=True):
                if tokens and sum(tokens) + count > MAX_BATCH_TOKENS:
                    yield group, tokens
                    group, tokens = [], []
                group.append(row)
                tokens.append(count)
            if group:
                yield group, tokens

    def preflight(self, snapshot: dict[str, Any], *, benchmark: bool = False) -> dict[str, Any]:
        repo = self.repository
        if snapshot["expected_chunk_count"] == 0:
            repo.assert_current(snapshot)
            return {
                "mode": "benchmark" if benchmark else "preflight",
                **snapshot,
                "profile_hash": fingerprint(repo.profile),
                "token_counts": {"total": 0, "min": 0, "max": 0, "p50": 0, "p95": 0},
                **(
                    {
                        "benchmark": {
                            "chunks": 0,
                            "seconds": 0,
                            "chunks_per_second": 0,
                            "batch_seconds_max": 0,
                            "estimated_full_seconds": 0,
                        }
                    }
                    if benchmark
                    else {}
                ),
            }
        self.embedding.check()
        lengths: list[tuple[int, str]] = []
        tokens: list[int] = []
        for rows, counts in self.grouped(
            repo.rows(snapshot["knowledge_base_id"], snapshot["chunk_profile_hash"])
        ):
            lengths.extend((r["embedding_char_count"], r["id"]) for r in rows)
            tokens.extend(counts)
        repo.assert_current(snapshot)
        if len(tokens) != snapshot["expected_chunk_count"]:
            raise VectorError("knowledge_vector_source_changed")
        ordered = sorted(tokens)
        result: dict[str, Any] = {
            "mode": "benchmark" if benchmark else "preflight",
            **snapshot,
            "profile_hash": self.embedding.profile_hash,
            "token_counts": {
                "total": sum(tokens),
                "min": min(tokens),
                "max": max(tokens),
                "p50": ordered[len(ordered) // 2],
                "p95": ordered[int(len(ordered) * 0.95)],
            },
        }
        if benchmark:
            # 按长度排序后等距分层；选点固定，不打印实际文本。
            lengths.sort()
            sample_count = min(100, len(lengths))
            selected = {
                lengths[round(i * (len(lengths) - 1) / max(1, sample_count - 1))][1]
                for i in range(sample_count)
            }
            sample = (
                r
                for r in repo.rows(snapshot["knowledge_base_id"], snapshot["chunk_profile_hash"])
                if r["id"] in selected
            )
            started = time.monotonic()
            latencies: list[float] = []
            for rows, counts in self.grouped(sample):
                tick = time.monotonic()
                value = self.embedding.call([r["embedding_text"] for r in rows], encode=True)
                if value["token_counts"] != counts:
                    raise VectorError("knowledge_embedding_result_invalid")
                latencies.append(time.monotonic() - tick)
            elapsed = time.monotonic() - started
            repo.assert_current(snapshot)
            result["benchmark"] = {
                "chunks": sample_count,
                "seconds": round(elapsed, 3),
                "chunks_per_second": round(sample_count / max(elapsed, 0.001), 3),
                "batch_seconds_max": round(max(latencies), 3),
                "estimated_full_seconds": round(elapsed / sample_count * len(tokens)),
            }
        return result

    def _verify_points(
        self, index: dict[str, Any], rows: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        points = self.qdrant.retrieve(index, [point_id(index, r) for r in rows])
        missing = []
        for row in rows:
            found = points.get(point_id(index, row))
            if found is None:
                missing.append(row)
            elif found.get("payload") != payload(index, row):
                raise VectorError("knowledge_vector_point_conflict")
            else:
                validate_vector(found.get("vector"))
                if hybrid_index(index):
                    validate_sparse(found.get("sparse_vector"))
        return missing

    def build(  # noqa: PLR0915
        self,
        code: str,
        snapshot: dict[str, Any],
        *,
        progress: Callable[[dict[str, int]], None] | None = None,
        reuse_from_code: str | None = None,
        capacity_check: Callable[[int], None] | None = None,
    ) -> dict[str, Any]:
        repo = self.repository
        if snapshot["expected_chunk_count"]:
            self.embedding.check()
        previous = self._reuse_source(snapshot, reuse_from_code)
        if previous is not None and previous["code"] == code:
            raise VectorError("knowledge_vector_reuse_invalid")
        with repo.source_lock("vector-index:" + code):
            index = repo.create(code, snapshot)
            repo.state(index, "BUILDING")
            processed, encoded, reused = 0, 0, 0
            started = time.monotonic()
            try:
                repo.manifest(index)
                if capacity_check is not None:
                    capacity_check(0)
                self.qdrant.ensure(index)
                for rows in batches(
                    repo.rows(index["knowledge_base_id"], index["chunk_profile_hash"]), 32
                ):
                    if capacity_check is not None:
                        capacity_check(
                            max(0, index["expected_chunk_count"] - self.qdrant.count(index))
                        )
                    missing = self._verify_points(index, rows)
                    reused += len(rows) - len(missing)
                    if previous is not None and missing:
                        original_missing = len(missing)
                        missing = self._copy_reusable(previous, index, missing)
                        reused += original_missing - len(missing)
                    for group, counts in self.grouped(iter(missing)):
                        repo.checkpoint(index, group, "PENDING", attempted=True)
                        try:
                            result = self.embedding.call(
                                [r["embedding_text"] for r in group], encode=True
                            )
                            if result["token_counts"] != counts:
                                raise VectorError("knowledge_embedding_result_invalid")
                            self.qdrant.upsert(
                                index,
                                [
                                    {
                                        "id": point_id(index, row),
                                        "payload": payload(index, row),
                                        "vector": vector,
                                        **lexical_input(index, row),
                                    }
                                    for row, vector in zip(group, result["vectors"], strict=True)
                                ],
                            )
                            repo.checkpoint(index, group, "INDEXED")
                            encoded += len(group)
                        except Exception:
                            repo.checkpoint(
                                index, group, "FAILED", error="knowledge_vector_batch_failed"
                            )
                            raise
                    repo.checkpoint(index, rows, "INDEXED")
                    processed += len(rows)
                    if progress:
                        progress(
                            {
                                "processed": processed,
                                "total": index["expected_chunk_count"],
                                "encoded": encoded,
                                "reused": reused,
                            }
                        )
                # 逐项核验包括已记账项；总数相同并不足以证明正确。
                verified = 0
                for rows in batches(
                    repo.rows(index["knowledge_base_id"], index["chunk_profile_hash"]), 32
                ):
                    if self._verify_points(index, rows):
                        raise VectorError("knowledge_vector_points_missing")
                    verified += len(rows)
                if (
                    verified != index["expected_chunk_count"]
                    or self.qdrant.count(index) != verified
                ):
                    raise VectorError("knowledge_vector_count_mismatch")
                repo.assert_current(index)
                repo.state(index, "READY")
                return {
                    "mode": "commit",
                    "index_id": index["id"],
                    "state": "READY",
                    "verified": verified,
                    "encoded": encoded,
                    "reused": reused,
                    "seconds": round(time.monotonic() - started, 3),
                    "corpus_hash": index["corpus_hash"],
                    "profile_hash": index["profile_hash"],
                }
            except Exception as exc:
                code = exc.code if isinstance(exc, VectorError) else "knowledge_vector_build_failed"
                repo.state(index, "FAILED", code)
                raise VectorError(code) from None

    def _reuse_source(self, snapshot: dict[str, Any], code: str | None) -> dict[str, Any] | None:
        if code is None:
            return None
        previous = self.repository.get(code)
        if (
            not previous
            or previous["state"] != "READY"
            or previous["knowledge_base_id"] != snapshot["knowledge_base_id"]
        ):
            raise VectorError("knowledge_vector_reuse_invalid")
        if fingerprint(previous["profile"]) != previous["profile_hash"]:
            raise VectorError("knowledge_vector_reuse_invalid")
        if (
            previous["profile"] != self.repository.profile
            or previous["chunk_profile_hash"] != snapshot["chunk_profile_hash"]
        ):
            # 已明确的模型或模板变化只能重新编码，不能跨配置复用数值。
            return None
        self.qdrant.check(previous)
        if self.qdrant.count(previous) != previous["expected_chunk_count"]:
            raise VectorError("knowledge_vector_reuse_invalid")
        return previous

    def verify(
        self, index: dict[str, Any], *, check_active: Callable[[], None] | None = None
    ) -> str:
        """维护接续用逐点只读验证；不编码，不修改索引状态。"""
        repo = self.repository
        if (
            index["state"] != "READY"
            or index["profile"] != repo.profile
            or index["profile_hash"] != fingerprint(repo.profile)
        ):
            raise VectorError("knowledge_vector_index_not_ready")
        repo.assert_current(index)
        if index["expected_chunk_count"]:
            self.embedding.check()
        self.qdrant.check(index)
        verified = 0
        for rows in batches(repo.rows(index["knowledge_base_id"], index["chunk_profile_hash"]), 32):
            if check_active is not None:
                check_active()
            if self._verify_points(index, rows):
                raise VectorError("knowledge_vector_points_missing")
            verified += len(rows)
        if verified != index["expected_chunk_count"] or self.qdrant.count(index) != verified:
            raise VectorError("knowledge_vector_count_mismatch")
        repo.assert_current(index)
        if check_active is not None:
            check_active()
        return fingerprint(
            {
                "index_id": index["id"],
                "profile_hash": index["profile_hash"],
                "corpus_hash": index["corpus_hash"],
                "verified_points": verified,
            }
        )

    def _copy_reusable(
        self, previous: dict[str, Any], index: dict[str, Any], rows: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        reusable = self.repository.reusable_rows(previous, [row["embedding_hash"] for row in rows])
        if not reusable:
            return rows
        points = self.qdrant.retrieve(
            previous, [point_id(previous, row) for row in reusable.values()]
        )
        vectors = {}
        for key, row in reusable.items():
            point = points.get(point_id(previous, row))
            if not point or point.get("payload") != payload(previous, row):
                raise VectorError("knowledge_vector_reuse_invalid")
            vectors[key] = validate_vector(point.get("vector"))
        copied = [row for row in rows if row["embedding_hash"] in vectors]
        self.qdrant.upsert(
            index,
            [
                {
                    "id": point_id(index, row),
                    "payload": payload(index, row),
                    "vector": vectors[row["embedding_hash"]],
                    **lexical_input(index, row),
                }
                for row in copied
            ],
        )
        self.repository.checkpoint(index, copied, "INDEXED")
        return [row for row in rows if row["embedding_hash"] not in vectors]

    def query(
        self, code: str, base_code: str, query: str, *, top_k: int = 10, mode: str = "auto"
    ) -> dict[str, Any]:
        if (
            not isinstance(query, str)
            or not query.strip()
            or len(query) > 2000
            or type(top_k) is not int
            or not 1 <= top_k <= 20
            or mode not in {"auto", "bm25", "dense", "hybrid"}
        ):
            raise VectorError("knowledge_vector_query_invalid")
        repo = self.repository
        index = repo.get(code)
        if (
            not index
            or index["state"] != "READY"
            or index["knowledge_base_id"] != repo.scope(base_code)
            or index["profile"] != self.repository.profile
            or index["profile_hash"] != fingerprint(self.repository.profile)
        ):
            raise VectorError("knowledge_vector_index_not_ready")
        if index["expected_document_count"] == 0:
            repo.assert_current(index)
            self.qdrant.check(index)
            if self.qdrant.count(index) != 0:
                raise VectorError("knowledge_vector_count_mismatch")
            return {
                "index_id": index["id"],
                "documents": [],
                "partial": False,
                "candidates": 0,
                "candidate_limit": 0,
                "bounded": False,
            }
        hybrid = hybrid_index(index)
        selected = "hybrid" if mode == "auto" and hybrid else "dense" if mode == "auto" else mode
        if not hybrid and selected != "dense":
            raise VectorError("knowledge_hybrid_index_required")
        if selected != "bm25":
            self.embedding.check()
        self.qdrant.check(index)
        vector = (
            self.embedding.call([query], encode=True)["vectors"][0] if selected != "bm25" else None
        )
        limit = 200 if hybrid else min(200, max(20, top_k * 4))
        docs: list[dict[str, Any]] = []
        candidates = []
        while True:
            if hybrid:
                candidates = self.qdrant.hybrid_search(index, vector, query, limit, mode=selected)
            else:
                assert vector is not None
                candidates = self.qdrant.search(index, vector, limit)
            docs = current_documents(repo, index, candidates)
            if len(docs) >= top_k or len(candidates) < limit or limit == 200:
                break
            limit = min(200, limit * 2)
        final_index = repo.get(code)
        if not final_index or final_index["state"] != "READY":
            raise VectorError("knowledge_vector_index_not_ready")
        results = docs[:top_k]
        return {
            "index_id": index["id"],
            "documents": results,
            "partial": len(results) < top_k,
            "candidates": len(candidates),
            "candidate_limit": limit,
            "bounded": len(candidates)
            >= (HYBRID_CONTRACT["per_route_limit"] if selected == "hybrid" else 200),
        }
