"""单轮同步的分块和向量 I/O 适配；阶段决策留在 application。"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.modules.knowledge.application.chunk_service import ChunkService
from app.modules.knowledge.application.ports import EmbeddingPort, QdrantPort
from app.modules.knowledge.application.vector_service import VectorService
from app.modules.knowledge.domain.chunking import ChunkProfile
from app.modules.knowledge.domain.identity import stable_id
from app.modules.knowledge.domain.normalization import ExportValidationError
from app.modules.knowledge.domain.vector_contract import fingerprint
from app.modules.knowledge.infrastructure.candidate_corpus import (
    CandidateChunkRepository,
    CandidateVectorRepository,
)
from app.modules.knowledge.infrastructure.sync_repository import SyncRepository
from app.modules.knowledge.infrastructure.vector_capacity import VectorCapacity
from app.shared.database import Database


class ManagedSyncSteps:
    def __init__(
        self,
        database: Database,
        embedding: EmbeddingPort,
        qdrant: QdrantPort,
        capacity_path: Path,
        *,
        progress: Callable[[str, dict[str, Any]], None] | None = None,
        cancelled: Callable[[], bool] = lambda: False,
    ) -> None:
        self.database, self.embedding, self.qdrant = database, embedding, qdrant
        self.capacity = VectorCapacity(capacity_path)
        self.progress = progress
        self.cancelled = cancelled

    def _check(self, run_id: str) -> dict[str, Any]:
        if self.cancelled():
            raise ExportValidationError("knowledge_sync_cancelled")
        repo = SyncRepository(self.database)
        run = repo.run(run_id)
        repo.assert_configuration(run)
        return run

    def chunk(self, run_id: str, base_code: str, profile: ChunkProfile) -> None:
        self._check(run_id)
        base_id = stable_id("base", base_code)
        repo = CandidateChunkRepository(self.database, run_id, profile=profile)
        count = repo.corpus.count(base_id)
        if count == 0:
            return
        result = ChunkService(repo).run(
            knowledge_base_code=base_code,
            expected_count=count,
            commit=True,
            progress=lambda value: self._progress(run_id, "chunking", value),
        )
        if result["counts"]["documents"] != count:
            raise ExportValidationError("knowledge_sync_chunk_incomplete")
        self._check(run_id)

    def index(self, run_id: str, base_code: str, profile: ChunkProfile) -> None:
        run = self._check(run_id)
        base_id = stable_id("base", base_code)
        repo = CandidateVectorRepository(self.database, run_id)
        binding = SyncRepository(self.database).binding(run["binding_id"])
        pins = [
            pin
            for pin in binding["resource_pins_json"].values()
            if pin["knowledge_base_id"] == base_id
        ]
        if any(
            pin["profile_hash"] != fingerprint(repo.profile)
            or pin["chunk_profile_hash"] != profile.fingerprint
            for pin in pins
        ):
            raise ExportValidationError("knowledge_sync_resource_profile_changed")
        previous_code = None
        if pins:
            revision = self.database.execute_one(
                f"select index_id from {repo.t('retrieval_revision')} where id=?",
                (pins[0]["published_revision_id"],),
            )
            prior = self.database.execute_one(
                f"select code from {repo.t('vector_index')} where id=?",
                (revision["index_id"],) if revision else ("",),
            )
            if not prior:
                raise ExportValidationError("knowledge_sync_resource_changed")
            previous_code = prior["code"]
        documents = repo.corpus.count(base_id)
        chunks = sum(1 for _ in repo.rows(base_id, profile.fingerprint))
        snapshot = repo.snapshot(base_id, profile.fingerprint, documents, chunks)
        VectorService(repo, self.embedding, self.qdrant).build(
            repo.index_code(base_id),
            snapshot,
            reuse_from_code=previous_code,
            capacity_check=lambda remaining: self._capacity(run_id, remaining),
            progress=lambda value: self._progress(run_id, "indexing", value),
        )
        self._check(run_id)

    def _capacity(self, run_id: str, remaining: int) -> None:
        self._check(run_id)
        self.capacity.check(remaining)

    def _progress(self, run_id: str, phase: str, value: dict[str, Any]) -> None:
        self._check(run_id)
        if self.progress is not None:
            self.progress(phase, value)
