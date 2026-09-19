"""离线 dense 标注集评测，复用现有读取内核，不授予用户权限或写索引。"""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import math
import platform
import time
from typing import Any

from app.modules.knowledge.domain.evaluation import EvaluationDataset, EvaluationError
from app.modules.knowledge.domain.vector_contract import VectorError, fingerprint
from app.modules.knowledge.application.vector_service import VectorService


@dataclass(frozen=True)
class QueryMetrics:
    recall: float | None
    reciprocal_rank: float | None
    no_answer_false_positive: bool | None


def score_documents(
    relevant: frozenset[str],
    retrieved: list[str],
    *,
    visible_relevant: frozenset[str] | None = None,
) -> QueryMetrics:
    """Visible labels must come from a current authorization observation, never an allowlist in JSON."""
    if visible_relevant is not None:
        if not visible_relevant <= relevant:
            raise EvaluationError("knowledge_evaluation_visibility_invalid")
        relevant = visible_relevant
    ranked = list(dict.fromkeys(retrieved))[:10]
    if not relevant:
        return QueryMetrics(None, None, bool(ranked))
    matches = [rank for rank, doc in enumerate(ranked, 1) if doc in relevant]
    return QueryMetrics(len(matches) / len(relevant), 1 / matches[0] if matches else 0.0, None)


def latency_summary(values: list[float]) -> dict[str, float | None]:
    ordered = sorted(values)
    # Nearest rank, documented and deterministic for small sets too.
    return {
        key: round(ordered[max(0, math.ceil(len(ordered) * p) - 1)], 3) if ordered else None
        for key, p in (("p50_ms", 0.5), ("p95_ms", 0.95))
    }


def _failure(exc: Exception) -> str:
    # Only code-owned categories are emitted, never arbitrary exception messages/codes.
    if isinstance(exc, VectorError):
        if exc.code in {
            "knowledge_vector_source_invalid",
            "knowledge_vector_source_changed",
            "knowledge_vector_point_conflict",
            "knowledge_collection_conflict",
        }:
            return "source_or_index_changed"
        if exc.code in {"knowledge_embedding_profile_mismatch", "knowledge_vector_index_not_ready"}:
            return "index_unavailable"
        if exc.code in {
            "knowledge_vector_unavailable",
            "knowledge_embedding_busy",
            "knowledge_embedding_read_timeout",
        }:
            return "dependency_unavailable"
        return "retrieval_failed"
    return "internal_error"


class OfflineEvaluation:
    def __init__(self, service: VectorService) -> None:
        self.service = service

    def run(self, dataset: EvaluationDataset, index_code: str) -> dict[str, Any]:
        code_hash = self.service.repository.implementation_hash()
        repo = self.service.repository
        index = repo.get(index_code)
        if (
            not index
            or index["state"] != "READY"
            or index["knowledge_base_id"] != repo.scope(dataset.base_code)
        ):
            raise EvaluationError("knowledge_evaluation_index_invalid")
        repo.assert_current(index)
        catalog = self.service.repository.evaluation_catalog(dataset, index)
        reverse = {external: doc for doc, external in catalog.items()}
        labels: list[frozenset[str]] = []
        # Resolve ALL labels before the first query, so missing/retired labels cannot silently become misses.
        for case in dataset.cases:
            resolved = set()
            for kind, value in case.relevant:
                doc = value if kind == "document" else reverse.get(value)
                if doc not in catalog:
                    raise EvaluationError("knowledge_evaluation_label_unavailable")
                resolved.add(doc)
            labels.append(frozenset(resolved))
        started = datetime.now(timezone.utc).isoformat()
        durations: list[float] = []
        failures: Counter[str] = Counter()
        categories: Counter[str] = Counter()
        recalls: list[float] = []
        reciprocal: list[float] = []
        no_answer_completed = no_answer_false_positive = partial = bounded = unmatched = 0
        for case, relevant in zip(dataset.cases, labels, strict=True):
            tick = time.monotonic()
            categories[case.category] += 1
            try:
                result = self.service.query(index_code, dataset.base_code, case.query, top_k=10)
                retrieved = [str(doc["document_id"]) for doc in result["documents"]]
                if (
                    any(doc not in catalog for doc in retrieved)
                    or result["index_id"] != index["id"]
                ):
                    raise VectorError("knowledge_vector_source_changed")
                scores = score_documents(relevant, retrieved)
                partial += int(result["partial"])
                bounded += int(result["bounded"])
                if scores.recall is None:
                    no_answer_completed += 1
                    no_answer_false_positive += int(bool(scores.no_answer_false_positive))
                else:
                    recalls.append(scores.recall)
                    unmatched += int(scores.recall == 0)
                    assert scores.reciprocal_rank is not None
                    reciprocal.append(scores.reciprocal_rank)
            except Exception as exc:
                failures[_failure(exc)] += 1
                # Answerable failures count as zero, never silently disappear from the denominator.
                if relevant:
                    recalls.append(0.0)
                    reciprocal.append(0.0)
            durations.append((time.monotonic() - tick) * 1000)
        repo.assert_current(index)
        if (
            repo.get(index_code) != index
            or self.service.repository.evaluation_catalog(dataset, index) != catalog
        ):
            raise EvaluationError("knowledge_evaluation_corpus_changed")
        if self.service.repository.implementation_hash() != code_hash:
            raise EvaluationError("knowledge_evaluation_code_changed")
        total = len(dataset.cases)
        return {
            "contract": "knowledge-evaluation-report/v1",
            "mode": "offline_dense",
            "basis": dataset.basis,
            "business_acceptance": False,
            "authorization_verified": False,
            "recall_scope": "complete_labels" if dataset.labels_complete else "labeled_set_only",
            "dataset_hash": dataset.digest,
            "dataset_version_hash": fingerprint(dataset.version),
            "code_hash": code_hash,
            "started_at": started,
            "environment": {
                "python": platform.python_version(),
                "os": platform.system(),
                "arch": platform.machine(),
            },
            "index_id": index["id"],
            "knowledge_base_id": index["knowledge_base_id"],
            "source_id": dataset.source_id,
            "corpus_hash": index["corpus_hash"],
            "profile_hash": index["profile_hash"],
            "chunk_profile_hash": index["chunk_profile_hash"],
            "parameters": {"top_k": 10, "candidate_limit": 200, "metrics_version": "document-v1"},
            "cases": total,
            "categories": dict(sorted(categories.items())),
            "answerable_cases": len(recalls),
            "recall_at_10": sum(recalls) / len(recalls) if recalls else None,
            "mrr_at_10": sum(reciprocal) / len(reciprocal) if reciprocal else None,
            "no_answer": {
                "total": sum(case.no_answer for case in dataset.cases),
                "completed": no_answer_completed,
                "false_positives": no_answer_false_positive,
                "false_positive_rate": no_answer_false_positive / no_answer_completed
                if no_answer_completed
                else None,
            },
            "retrieval_latency": latency_summary(durations),
            "end_to_end_latency": None,
            "partial_rate": partial / total,
            "bounded_rate": bounded / total,
            "unmatched_answerable_cases": unmatched,
            "failures": dict(sorted(failures.items())),
            "failed_cases": sum(failures.values()),
        }
