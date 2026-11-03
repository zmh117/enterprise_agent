"""同候选离线排序对照；汇总不含查询/正文，不证明 ONES 或 Agent 验收。"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
import platform
import time
from typing import Any

from app.modules.knowledge.application.candidates import candidate_pool, retrieval_mode
from app.modules.knowledge.application.vector_service import VectorService
from app.modules.knowledge.domain.evaluation import EvaluationDataset, EvaluationError
from app.modules.knowledge.domain.vector_contract import VectorError, fingerprint


@dataclass(frozen=True)
class QueryMetrics:
    recall: float | None
    reciprocal_rank: float | None
    no_answer_candidate_returned: bool | None


def score_documents(
    relevant: frozenset[str],
    retrieved: list[str],
    *,
    visible_relevant: frozenset[str] | None = None,
    k: int = 10,
) -> QueryMetrics:
    if visible_relevant is not None:
        if not visible_relevant <= relevant:
            raise EvaluationError("knowledge_evaluation_visibility_invalid")
        relevant = visible_relevant
    ranked = list(dict.fromkeys(retrieved))[:k]
    if not relevant:
        return QueryMetrics(None, None, bool(ranked))
    matches = [rank for rank, doc in enumerate(ranked, 1) if doc in relevant]
    return QueryMetrics(len(matches) / len(relevant), 1 / matches[0] if matches else 0.0, None)


def latency_summary(values: list[float]) -> dict[str, float | None]:
    ordered = sorted(values)
    return {
        key: round(ordered[max(0, math.ceil(len(ordered) * p) - 1)], 3) if ordered else None
        for key, p in (("p50_ms", 0.5), ("p95_ms", 0.95))
    }


def _failure(exc: Exception) -> str:
    if isinstance(exc, VectorError):
        if exc.code.startswith("knowledge_rerank_"):
            return "reranking_failed"
        if exc.code in {
            "knowledge_vector_unavailable",
            "knowledge_embedding_busy",
            "knowledge_embedding_read_timeout",
        }:
            return "dependency_unavailable"
        return "retrieval_failed"
    return "internal_error"


@dataclass
class MetricSeries:
    values: dict[str, list[float]] = field(
        default_factory=lambda: {
            "recall_at_5": [],
            "recall_at_10": [],
            "recall_at_20": [],
            "mrr_at_10": [],
            "hit_at_3": [],
        }
    )
    no_answer_total: int = 0
    no_answer_completed: int = 0
    no_answer_returned: int = 0

    def add(self, relevant: frozenset[str], retrieved: list[str], *, failed: bool = False) -> None:
        if not relevant:
            self.no_answer_total += 1
            self.no_answer_completed += int(not failed)
            self.no_answer_returned += int(not failed and bool(retrieved))
            return
        ranked = [] if failed else list(dict.fromkeys(retrieved))
        for k in (5, 10, 20):
            value = score_documents(relevant, ranked, k=k).recall
            assert value is not None
            self.values[f"recall_at_{k}"].append(value)
        self.values["mrr_at_10"].append(score_documents(relevant, ranked).reciprocal_rank or 0.0)
        self.values["hit_at_3"].append(float(bool(relevant.intersection(ranked[:3]))))

    def report(self) -> dict[str, Any]:
        return {
            **{
                key: sum(values) / len(values) if values else None
                for key, values in self.values.items()
            },
            "answerable_cases": len(self.values["mrr_at_10"]),
            "no_answer": {
                "total": self.no_answer_total,
                "completed": self.no_answer_completed,
                "candidate_returns": self.no_answer_returned,
                "candidate_return_rate": self.no_answer_returned / self.no_answer_completed
                if self.no_answer_completed
                else None,
            },
        }


def _labels(
    service: VectorService, dataset: EvaluationDataset, index: dict[str, Any]
) -> tuple[dict[str, str], list[frozenset[str]]]:
    catalog = service.repository.evaluation_catalog(dataset, index)
    reverse = {external: doc for doc, external in catalog.items()}
    labels = []
    for case in dataset.cases:
        resolved = set()
        for kind, value in case.relevant:
            doc = value if kind == "document" else reverse.get(value)
            if doc not in catalog:
                raise EvaluationError("knowledge_evaluation_label_unavailable")
            resolved.add(doc)
        labels.append(frozenset(resolved))
    return catalog, labels


class OfflineEvaluation:
    def __init__(self, service: VectorService) -> None:
        self.service = service

    def run(self, dataset: EvaluationDataset, index_code: str) -> dict[str, Any]:
        repo = self.service.repository
        index = repo.get(index_code)
        if (
            not index
            or index["state"] != "READY"
            or index["knowledge_base_id"] != repo.scope(dataset.base_code)
        ):
            raise EvaluationError("knowledge_evaluation_index_invalid")
        repo.assert_current(index)
        catalog, labels = _labels(self.service, dataset, index)
        if self.service.reranker is None:
            raise EvaluationError("knowledge_evaluation_reranker_required")
        code_hash, ranking_hash = repo.implementation_hash(), self.service.reranker.profile_hash
        started = datetime.now(timezone.utc).isoformat()
        observations = self._queries(dataset, index_code, index, catalog, labels)
        self._recheck(dataset, index, catalog, observations["snapshots"], code_hash, ranking_hash)
        return {
            "contract": "knowledge-evaluation-report/v2",
            "mode": "offline_ranking_comparison",
            "retrieval_mode": retrieval_mode(index),
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
            **{
                key: index[key]
                for key in (
                    "knowledge_base_id",
                    "corpus_hash",
                    "profile_hash",
                    "chunk_profile_hash",
                )
            },
            "index_id": index["id"],
            "source_id": dataset.source_id,
            "ranking_profile_hash": ranking_hash,
            "candidate_snapshot_hash": fingerprint(
                [s["digest"] for s in observations.pop("snapshots")]
            ),
            "parameters": {
                "top_k": 20,
                "candidate_limit": 200,
                "document_limit": 50,
                "metrics_version": "document-comparison-v2",
            },
            "end_to_end_latency": None,
            **observations,
        }

    def _queries(
        self,
        dataset: EvaluationDataset,
        code: str,
        index: dict[str, Any],
        catalog: dict[str, str],
        labels: list[frozenset[str]],
    ) -> dict[str, Any]:
        baseline, reranked = MetricSeries(), MetricSeries()
        categories: dict[str, tuple[MetricSeries, MetricSeries]] = {}
        failures: Counter[str] = Counter()
        snapshots, coverage, selected_coverage = [], [], []
        timings: dict[str, list[float]] = {
            key: [] for key in ("encoding", "retrieval", "reranking", "total")
        }
        partial = bounded = cropped = selected_count = 0
        for case, relevant in zip(dataset.cases, labels, strict=True):
            category = categories.setdefault(case.category, (MetricSeries(), MetricSeries()))
            tick = time.monotonic()
            try:
                result = self.service.query(
                    code, dataset.base_code, case.query, top_k=20, compare=True
                )
                comparison = result["comparison"]
                before = [d["document_id"] for d in comparison["baseline"]]
                after = [d["document_id"] for d in result["documents"]]
                if result["index_id"] != index["id"] or any(
                    doc not in catalog for doc in comparison["candidate_document_ids"]
                ):
                    raise EvaluationError("knowledge_evaluation_corpus_changed")
                failed = comparison["ranking_failure"] is not None
                if failed:
                    failures["reranking_failed"] += 1
                baseline.add(relevant, before)
                reranked.add(relevant, after, failed=failed)
                category[0].add(relevant, before)
                category[1].add(relevant, after, failed=failed)
                snapshots.append(comparison["snapshot"])
                if relevant:
                    coverage.append(
                        len(relevant.intersection(comparison["candidate_document_ids"]))
                        / len(relevant)
                    )
                    selected_coverage.append(
                        len(relevant.intersection(comparison["selected_document_ids"]))
                        / len(relevant)
                    )
                partial += int(result["partial"])
                bounded += int(result["bounded"])
                if not failed:
                    cropped += comparison["truncated_documents"]
                    selected_count += len(comparison["selected_document_ids"])
                for key in timings:
                    timings[key].append(result["durations_ms"][key])
            except EvaluationError:
                raise
            except Exception as exc:
                if isinstance(exc, VectorError) and exc.code in {
                    "knowledge_vector_source_changed",
                    "knowledge_vector_point_conflict",
                }:
                    raise EvaluationError("knowledge_evaluation_corpus_changed") from None
                failures[_failure(exc)] += 1
                for series in (baseline, reranked, *category):
                    series.add(relevant, [], failed=True)
                if relevant:
                    coverage.append(0.0)
                    selected_coverage.append(0.0)
                timings["total"].append((time.monotonic() - tick) * 1000)
        total = len(dataset.cases)
        return {
            "cases": total,
            "baseline": baseline.report(),
            "reranked": reranked.report(),
            "categories": {
                key: {"baseline": b.report(), "reranked": r.report()}
                for key, (b, r) in sorted(categories.items())
            },
            "candidate_recall": sum(coverage) / len(coverage) if coverage else None,
            "candidate_recall_at_50": sum(selected_coverage) / len(selected_coverage)
            if selected_coverage
            else None,
            "latency": {key: latency_summary(values) for key, values in timings.items()},
            "partial_rate": partial / total,
            "bounded_rate": bounded / total,
            "truncated_document_rate": cropped / selected_count if selected_count else None,
            "failures": dict(sorted(failures.items())),
            "failed_cases": sum(failures.values()),
            "snapshots": snapshots,
        }

    def _recheck(
        self,
        dataset: EvaluationDataset,
        index: dict[str, Any],
        catalog: dict[str, str],
        snapshots: list[dict[str, Any]],
        code_hash: str,
        ranking_hash: str,
    ) -> None:
        repo = self.service.repository
        try:
            repo.assert_current(index)
            if (
                repo.get(index["code"]) != index
                or repo.evaluation_catalog(dataset, index) != catalog
            ):
                raise EvaluationError("knowledge_evaluation_corpus_changed")
            for snapshot in snapshots:
                if candidate_pool(repo, index, snapshot["points"]).digest != snapshot["digest"]:
                    raise EvaluationError("knowledge_evaluation_corpus_changed")
        except VectorError:
            raise EvaluationError("knowledge_evaluation_corpus_changed") from None
        if repo.implementation_hash() != code_hash:
            raise EvaluationError("knowledge_evaluation_code_changed")
        if self.service.reranker is None or self.service.reranker.profile_hash != ranking_hash:
            raise EvaluationError("knowledge_evaluation_profile_changed")
