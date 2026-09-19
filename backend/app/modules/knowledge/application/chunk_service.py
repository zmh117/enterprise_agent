"""分块用例；保持原 profile、逐文档原子保存和幂等重放。"""

from collections import Counter
from collections.abc import Callable
import hashlib
from typing import Any
from app.modules.knowledge.domain.chunking import prepare_chunks
from app.modules.knowledge.domain.normalization import ExportValidationError, canonical_json
from app.modules.knowledge.application.ports import ChunkRepository


class ChunkService:
    def __init__(self, repository: ChunkRepository) -> None:
        self.repository = repository
        self.profile = repository.profile
        self.profile.validate()

    @staticmethod
    def _identity(record: dict[str, Any]) -> bytes:
        return canonical_json(
            [record["document_id"], record["revision_id"], record["content_hash"]]
        ).encode()

    def run(
        self,
        *,
        knowledge_base_code: str,
        expected_count: int,
        commit: bool = False,
        progress: Callable[[dict[str, int]], None] | None = None,
    ) -> dict[str, Any]:
        if not 1 <= expected_count <= 200_000:
            raise ExportValidationError("knowledge_expected_count_invalid")
        try:
            base_id, source_id = self.repository.scope(knowledge_base_code)
            with self.repository.source_lock(source_id):
                if self.repository.scope(knowledge_base_code) != (base_id, source_id):
                    raise ExportValidationError("knowledge_chunk_source_changed")
                if self.repository.count(base_id, source_id) != expected_count:
                    raise ExportValidationError("knowledge_record_count_mismatch")
                counts: Counter[str] = Counter(
                    dict.fromkeys(
                        (
                            "documents",
                            "chunks",
                            "problem",
                            "solution",
                            "created",
                            "reused",
                            "previewed",
                            "split_problem_documents",
                        ),
                        0,
                    )
                )
                flags: Counter[str] = Counter()
                solutions: Counter[str] = Counter()
                histogram: Counter[str] = Counter()
                minimum, maximum, embedding_max, total_chars = self.profile.max_chars, 0, 0, 0
                input_digest = hashlib.sha256()
                output_digest = hashlib.sha256()
                for record in self.repository.rows(base_id, source_id):
                    if record["document_kind"] != "defect":
                        raise ExportValidationError("knowledge_chunk_kind_unsupported")
                    input_digest.update(self._identity(record))
                    prepared = prepare_chunks(record, self.profile)
                    output_digest.update(prepared.output_hash.encode())
                    outcome = (
                        self.repository.save(record, prepared, base_id, source_id)
                        if commit
                        else "previewed"
                    )
                    counts[outcome] += 1
                    counts["documents"] += 1
                    solutions[prepared.quality["solution_state"]] += 1
                    counts["split_problem_documents"] += (
                        sum(c["chunk_kind"] == "problem" for c in prepared.chunks) > 1
                    )
                    for chunk in prepared.chunks:
                        counts["chunks"] += 1
                        counts[chunk["chunk_kind"]] += 1
                        size = chunk["char_count"]
                        minimum, maximum = min(minimum, size), max(maximum, size)
                        embedding_max = max(embedding_max, chunk["embedding_char_count"])
                        total_chars += size
                        histogram[
                            "1-300"
                            if size <= 300
                            else "301-600"
                            if size <= 600
                            else "601-900"
                            if size <= 900
                            else "901-1200"
                        ] += 1
                        flags.update(chunk["quality_flags"])
                    if progress and (
                        counts["documents"] % 250 == 0 or counts["documents"] == expected_count
                    ):
                        progress({"processed": counts["documents"], "total": expected_count})
                final_digest = hashlib.sha256()
                for row in self.repository.rows(base_id, source_id, metadata_only=True):
                    final_digest.update(self._identity(row))
                if (
                    counts["documents"] != expected_count
                    or final_digest.digest() != input_digest.digest()
                ):
                    raise ExportValidationError("knowledge_chunk_source_changed")
                return {
                    "mode": "commit" if commit else "dry_run",
                    "profile_version": self.profile.version,
                    "profile_hash": self.profile.fingerprint,
                    "input_hash": input_digest.hexdigest(),
                    "output_hash": output_digest.hexdigest(),
                    "counts": dict(counts),
                    "failed_documents": 0,
                    "lengths": {
                        "min": minimum,
                        "max": maximum,
                        "mean": round(total_chars / counts["chunks"], 2),
                        "embedding_max": embedding_max,
                        "histogram": dict(histogram),
                    },
                    "solution_states": dict(solutions),
                    "chunk_quality_flags": dict(flags),
                }
        except ExportValidationError:
            raise
        except Exception:
            raise ExportValidationError("knowledge_chunk_processing_failed") from None
