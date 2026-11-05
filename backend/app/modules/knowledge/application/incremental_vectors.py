"""固定集合的有界文档向量写入；不改变发布配置或扫描其他文档。"""

from collections.abc import Callable, Iterator
from typing import Any, Protocol

from app.modules.knowledge.application.ports import (
    EmbeddingPort,
    IncrementalQdrantPort,
    VectorRepository,
)
from app.modules.knowledge.application.vector_service import VectorService
from app.modules.knowledge.domain.hybrid import hybrid_index, lexical_input, validate_sparse
from app.modules.knowledge.domain.vector_contract import VectorError, validate_vector
from app.modules.knowledge.domain.vector_points import batches, payload, point_id


class DocumentVectorStore(VectorRepository, Protocol):
    def register(self, index: dict[str, Any], rows: list[dict[str, Any]]) -> None: ...
    def remove_items(self, index: dict[str, Any], rows: list[dict[str, Any]]) -> None: ...


class IncrementalVectorWriter:
    def __init__(
        self,
        repository: DocumentVectorStore,
        embedding: EmbeddingPort,
        qdrant: IncrementalQdrantPort,
        check_active: Callable[[], None],
    ) -> None:
        self.repository, self.embedding, self.qdrant = repository, embedding, qdrant
        self.check_active = check_active

    @staticmethod
    def _valid(index: dict[str, Any], row: dict[str, Any], point: dict[str, Any]) -> None:
        expected = payload(index, row)
        actual = point.get("payload")
        if (
            not isinstance(actual, dict)
            or type(actual.get("searchable")) is not bool
            or {**actual, "searchable": True} != expected
        ):
            raise VectorError("knowledge_vector_point_conflict")
        validate_vector(point.get("vector"))
        if hybrid_index(index):
            validate_sparse(point.get("sparse_vector"))

    def prepare(
        self,
        index: dict[str, Any],
        rows: Iterator[dict[str, Any]],
        *,
        total: int,
        capacity: Callable[[int], None] = lambda _: None,
        progress: Callable[[dict[str, int]], None] = lambda _: None,
    ) -> dict[str, int]:
        counts = {"processed": 0, "total": total, "encoded": 0, "reused": 0, "verified": 0}
        progress(dict(counts))
        self.qdrant.ensure(index)
        for batch in batches(rows, 32):
            self.check_active()
            capacity(len(batch))
            self.repository.register(index, batch)
            existing = self.qdrant.retrieve(index, [point_id(index, row) for row in batch])
            missing = []
            for row in batch:
                point = existing.get(point_id(index, row))
                if point is None:
                    missing.append(row)
                else:
                    self._valid(index, row, point)
                    counts["reused"] += 1
            missing = self._reuse(index, missing, counts)
            service = VectorService(self.repository, self.embedding, self.qdrant)
            for group, tokens in service.grouped(iter(missing)):
                self.check_active()
                self.repository.checkpoint(index, group, "PENDING", attempted=True)
                value = self.embedding.call([row["embedding_text"] for row in group], encode=True)
                if value["token_counts"] != tokens:
                    raise VectorError("knowledge_embedding_result_invalid")
                self._write(index, group, value["vectors"])
                counts["encoded"] += len(group)
            verified = self.qdrant.retrieve(index, [point_id(index, row) for row in batch])
            for row in batch:
                point = verified.get(point_id(index, row))
                if point is None:
                    raise VectorError("knowledge_vector_points_missing")
                self._valid(index, row, point)
            self.repository.checkpoint(index, batch, "INDEXED")
            counts["verified"] += len(batch)
            counts["processed"] = counts["verified"]
            progress(dict(counts))
        return counts

    def _write(
        self, index: dict[str, Any], rows: list[dict[str, Any]], vectors: list[list[float]]
    ) -> None:
        self.qdrant.upsert(
            index,
            [
                {
                    "id": point_id(index, row),
                    "payload": {**payload(index, row), "searchable": False},
                    "vector": validate_vector(vector),
                    **lexical_input(index, row),
                }
                for row, vector in zip(rows, vectors, strict=True)
            ],
        )

    def _reuse(
        self, index: dict[str, Any], rows: list[dict[str, Any]], counts: dict[str, int]
    ) -> list[dict[str, Any]]:
        reusable = self.repository.reusable_rows(index, [row["embedding_hash"] for row in rows])
        if not reusable:
            return rows
        points = self.qdrant.retrieve(index, [point_id(index, row) for row in reusable.values()])
        vectors = {}
        for key, row in reusable.items():
            point = points.get(point_id(index, row))
            if point is not None:
                self._valid(index, row, point)
                vectors[key] = point["vector"]
        copied = [row for row in rows if row["embedding_hash"] in vectors]
        if copied:
            self._write(index, copied, [vectors[row["embedding_hash"]] for row in copied])
            counts["reused"] += len(copied)
        return [row for row in rows if row["embedding_hash"] not in vectors]

    def expose(self, index: dict[str, Any], rows: Iterator[dict[str, Any]]) -> None:
        for batch in batches(rows, 32):
            self.check_active()
            ids = [point_id(index, row) for row in batch]
            points = self.qdrant.retrieve(index, ids)
            for row in batch:
                point = points.get(point_id(index, row))
                if point is None:
                    raise VectorError("knowledge_vector_points_missing")
                self._valid(index, row, point)
            self.qdrant.set_searchable(index, ids, True)

    def remove(self, index: dict[str, Any], rows: Iterator[dict[str, Any]]) -> None:
        for batch in batches(rows, 32):
            self.check_active()
            self.qdrant.delete_points(index, [point_id(index, row) for row in batch])
            self.repository.remove_items(index, batch)
