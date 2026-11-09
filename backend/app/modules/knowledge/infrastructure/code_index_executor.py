"""One bounded index attempt; never invokes a conversational model or takes source locks."""

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Protocol

from app.modules.knowledge.application.incremental_vectors import IncrementalVectorWriter
from app.modules.knowledge.application.ports import EmbeddingPort, IncrementalQdrantPort
from app.modules.knowledge.domain.code_chunks import prepare_code_chunks
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.infrastructure.code_chunk_repository import (
    CodeChunkRepository,
    CodeVectorRepository,
)
from app.modules.knowledge.infrastructure.code_index_store import CodeIndexStore
from app.modules.knowledge.domain.vector_points import batches, point_id, payload
from app.modules.knowledge.domain.hybrid import lexical_input
from app.modules.knowledge.infrastructure.code_executor_lock import execution_lock
from app.shared.io_deadline import io_deadline


class CodeIndexQdrant(IncrementalQdrantPort, Protocol):
    def delete_code_generations(
        self, index: dict[str, Any], task_id: str, maximum: int
    ) -> None: ...


class CodeIndexExecutor:
    def __init__(
        self,
        store: CodeIndexStore,
        embedding: EmbeddingPort,
        qdrant: CodeIndexQdrant,
        *,
        owner: str,
        execution_root: Path,
        cancelled: Callable[[], bool] = lambda: False,
    ) -> None:
        self.store, self.embedding, self.qdrant = store, embedding, qdrant
        self.owner, self.cancelled = owner, cancelled
        self.execution_root = execution_root

    def execute(self, identifier: str) -> bool:
        try:
            with execution_lock(self.execution_root, "index", identifier) as proof:
                return self._execute(identifier, proof)
        except CodeKnowledgeError as exc:
            if exc.code == "CODE_EXECUTOR_STILL_RUNNING":
                return False
            raise

    def _execute(self, identifier: str, proof: Any) -> bool:
        owned = self.store.claim(identifier, self.owner)
        if owned is None:
            return False
        proof.bind(owned)
        try:
            with io_deadline(120, cancelled=self.cancelled) as deadline:

                def active() -> None:
                    deadline.check()
                    self.store.active(owned)

                _, index = self.store.active(owned)
                vectors = CodeVectorRepository(self.store.db, owned)
                writer = IncrementalVectorWriter(vectors, self.embedding, self.qdrant, active)
                if index["profile"] != vectors.profile:
                    raise CodeKnowledgeError("CODE_INDEX_CONFIGURATION_CHANGED")
                if owned["action"] == "remove":
                    upsert = self.store.db.execute_one(
                        f"SELECT id,claim_version FROM {self.store.t('code_index_task')} "
                        "WHERE index_id=? AND revision_id=? AND action='upsert'",
                        (owned["index_id"], owned["revision_id"]),
                    )
                    if upsert is not None:
                        self.qdrant.delete_code_generations(
                            index, upsert["id"], upsert["claim_version"]
                        )
                    for batch in batches(
                        vectors.document_rows(owned["revision_id"], index["chunk_profile_hash"]), 32
                    ):
                        active()
                        vectors.remove_items(index, batch)
                    self.store.progress(owned, step="cleaned", expected=0, completed=0)
                else:
                    self._upsert(owned, index, writer, vectors, active)
                self.store.finish(owned)
        except Exception as exc:
            # Local I/O returned. Remote late writes are isolated by point generation.
            code = exc.code if isinstance(exc, CodeKnowledgeError) else "CODE_INDEX_IO_FAILED"
            self.store.stopped(owned, code)
        return True

    def _upsert(
        self,
        owned: dict[str, Any],
        index: dict[str, Any],
        writer: IncrementalVectorWriter,
        vectors: CodeVectorRepository,
        active: Callable[[], None],
    ) -> None:
        chunks = CodeChunkRepository(self.store.db)
        record = self.store.record(owned)
        prepared = chunks.reuse(record) or prepare_code_chunks(record)
        with self.store.db.unit_of_work():
            self.store._document_lock(owned["document_id"])
            active()
            chunks._save_immutable(record, prepared)
            self.store.progress(owned, step="chunked", expected=len(prepared.chunks), completed=0)

        def rows() -> Iterator[dict[str, Any]]:
            return vectors.document_rows(owned["revision_id"], index["chunk_profile_hash"])

        total = len(prepared.chunks)
        self.qdrant.ensure(index)
        self._reuse_previous(index, owned, rows(), writer, active)
        writer.prepare(
            index,
            rows(),
            total=total,
            progress=lambda counts: self.store.progress(
                owned,
                step="written",
                expected=total,
                completed=counts["verified"],
            ),
        )
        self.store.progress(owned, step="verified", expected=total, completed=total)
        writer.expose(index, rows())
        # Exposure itself can lose its response. Every retry checks exact points again.
        for batch in batches(rows(), 32):
            active()
            points = self.qdrant.retrieve(index, [point_id(index, row) for row in batch])
            for row in batch:
                point = points.get(point_id(index, row))
                if point is None or point.get("payload", {}).get("searchable") is not True:
                    raise CodeKnowledgeError("CODE_INDEX_INCOMPLETE")
                writer._valid(index, row, point)
        self.store.progress(owned, step="exposed", expected=total, completed=total)

    def _reuse_previous(
        self,
        index: dict[str, Any],
        owned: dict[str, Any],
        rows: Iterator[dict[str, Any]],
        writer: IncrementalVectorWriter,
        active: Callable[[], None],
    ) -> None:
        # Bounded recovery of immutable vectors, including a lost upsert response.
        # Skipped claim numbers (manual restart) are harmless. Older attempts may
        # be encoded again; they can never become current by arriving late.
        for batch in batches(rows, 32):
            missing = {row["id"]: row for row in batch}
            for generation in range(
                owned["claim_version"] - 1, max(0, owned["claim_version"] - 9), -1
            ):
                if not missing:
                    break
                active()
                previous = [
                    {
                        **row,
                        "code_payload": CodeVectorRepository._code_payload(
                            row, owned["id"], generation
                        ),
                    }
                    for row in missing.values()
                ]
                points = self.qdrant.retrieve(index, [point_id(index, row) for row in previous])
                copies = []
                for old in previous:
                    point = points.get(point_id(index, old))
                    if point is None:
                        continue
                    writer._valid(index, old, point)
                    current = missing.pop(old["id"])
                    copies.append(
                        {
                            "id": point_id(index, current),
                            "payload": {**payload(index, current), "searchable": False},
                            "vector": point["vector"],
                            **lexical_input(index, current),
                        }
                    )
                if copies:
                    active()
                    self.qdrant.upsert(index, copies)
