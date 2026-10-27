"""固定本地派生目标的文档编排接线。"""

from collections.abc import Callable
from pathlib import Path
from typing import Any
import time

from app.modules.knowledge.application.incremental_vectors import IncrementalVectorWriter
from app.modules.knowledge.application.managed_sync_pipeline import _profile
from app.modules.knowledge.application.ports import EmbeddingPort, IncrementalQdrantPort
from app.modules.knowledge.domain.chunking import (
    DEFAULT_PROFILE,
    WORK_ITEM_PROFILE,
    KEEP_IDS_PROFILE,
    ChunkProfile,
)
from app.modules.knowledge.domain.normalization import ExportValidationError
from app.modules.knowledge.infrastructure.incremental_repository import (
    IncrementalSyncRepository,
    IncrementalVectorRepository,
)
from app.modules.knowledge.infrastructure.vector_capacity import VectorCapacity
from app.shared.database import Database


class IncrementalSyncSteps:
    def __init__(
        self,
        database: Database,
        embedding: EmbeddingPort,
        qdrant: IncrementalQdrantPort,
        capacity_path: Path,
        check_active: Callable[[], None],
        progress: Callable[[dict[str, Any]], None] | None = None,
        emit: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.repo = IncrementalSyncRepository(database)
        self.vectors = IncrementalVectorRepository(database)
        self.writer = IncrementalVectorWriter(self.vectors, embedding, qdrant, check_active)
        self.capacity = VectorCapacity(capacity_path)
        self.check_active, self.progress = check_active, progress
        self.emit = emit
        self._progress_at = 0.0

    def _record_progress(self, candidate: dict[str, Any], counts: dict[str, int]) -> None:
        tick = time.monotonic()
        if tick - self._progress_at >= 15:
            self.repo.record_progress(candidate["run_id"], "indexing", counts)
            self._progress_at = tick
            if self.progress:
                self.progress(
                    {
                        "run_id": candidate["run_id"],
                        "document_id": candidate["document_id"],
                        **counts,
                    }
                )

    def profile(self, binding: dict[str, Any], base_id: str) -> ChunkProfile:
        row = self.repo.database.execute_one(
            f"select chunk_profile_hash from {self.repo.t('vector_index')} where knowledge_base_id=? and incremental=1 and state='READY'",
            (base_id,),
        )
        if row:
            for profile in (DEFAULT_PROFILE, WORK_ITEM_PROFILE, KEEP_IDS_PROFILE):
                if row["chunk_profile_hash"] == profile.fingerprint:
                    return profile
            raise ExportValidationError("knowledge_sync_resource_profile_changed")
        return _profile(binding, base_id)

    def process(self, candidate: dict[str, Any]) -> None:
        repo, vectors = self.repo, self.vectors
        self.check_active()
        run = repo.run(candidate["run_id"])
        binding = repo.assert_configuration(run)
        changed = (
            candidate["candidate_revision_id"] != candidate["baseline_revision_id"]
            or candidate["candidate_members_json"] != candidate["baseline_members_json"]
        )
        indexes = {}
        if changed:
            for base_id, state in candidate["candidate_members_json"].items():
                if (
                    state != "included"
                    and candidate["baseline_members_json"].get(base_id) != "included"
                ):
                    continue
                profile = self.profile(binding, base_id)
                index = vectors.index_for(base_id, run["source_id"], profile)
                indexes[base_id] = index
                if state == "included" and candidate["processing_step"] == "PENDING":
                    repo.prepare_document(candidate, profile)
                    self.capacity.check(0)
                    counts = self.writer.prepare(
                        index,
                        vectors.document_rows(
                            candidate["candidate_revision_id"], profile.fingerprint
                        ),
                        capacity=self.capacity.check,
                        progress=lambda value: self._record_progress(candidate, value),
                    )
                    if self.progress:
                        self.progress(
                            {"run_id": run["id"], "document_id": candidate["document_id"], **counts}
                        )
        if candidate["processing_step"] == "PENDING":
            repo.apply_document(candidate)
        for base_id, index in indexes.items():
            if candidate["candidate_members_json"].get(base_id) == "included":
                self.writer.expose(
                    index,
                    vectors.document_rows(
                        candidate["candidate_revision_id"], index["chunk_profile_hash"]
                    ),
                )
            if candidate["baseline_members_json"].get(base_id) == "included" and (
                candidate["baseline_revision_id"] != candidate["candidate_revision_id"]
                or candidate["candidate_members_json"].get(base_id) != "included"
            ):
                self.writer.remove(
                    index,
                    vectors.document_rows(
                        candidate["baseline_revision_id"], index["chunk_profile_hash"]
                    ),
                )
        repo.step(candidate, "DONE")
        if self.emit:
            event = repo.same_stamp_event(candidate, "DONE")
            if event is not None:
                self.emit("knowledge_source_same_stamp_revised", event)
