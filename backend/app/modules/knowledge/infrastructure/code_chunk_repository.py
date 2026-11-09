"""Code-specific context on the shared immutable chunk storage and vector writer."""

from collections.abc import Iterator
from typing import Any

from app.modules.knowledge.domain.chunking import CHUNK_VALUE_COLUMNS, PreparedChunks
from app.modules.knowledge.domain.code_chunks import validate_code_chunks
from app.modules.knowledge.domain.code_configuration import CODE_CHUNK_PROFILE
from app.modules.knowledge.domain.normalization import digest
from app.modules.knowledge.domain.vector_points import point_id
from app.modules.knowledge.infrastructure.chunk_repository import ChunkRepository, json_value
from app.modules.knowledge.infrastructure.incremental_repository import IncrementalVectorRepository
from app.shared.database import Database


class CodeChunkRepository(ChunkRepository):
    value_columns = (*CHUNK_VALUE_COLUMNS, "context_json")
    json_columns = ("quality_flags", "context_json")

    def __init__(self, database: Database) -> None:
        super().__init__(database, profile=CODE_CHUNK_PROFILE)

    def validate(self, prepared: PreparedChunks) -> None:
        validate_code_chunks(prepared)


class CodeVectorRepository(IncrementalVectorRepository):
    def __init__(self, database: Database, owned: dict[str, Any]) -> None:
        super().__init__(database)
        self.owned = owned

    @staticmethod
    def _code_payload(row: dict[str, Any], task_id: str, generation: int) -> dict[str, Any]:
        context = json_value(row["context_json"])
        return {
            "index_task_id": task_id,
            "index_generation": generation,
            "index_generation_key": f"{task_id}:{generation}",
            **{
                key: context[key]
                for key in (
                    "source_id",
                    "repository_uuid",
                    "branch_path",
                    "svn_revision",
                    "support_status",
                )
            },
            "visibility_scope_hash": digest(context["visibility_scope"]),
            "evidence_ids": sorted(
                {e for claim in context["claims"] for e in claim["evidence_ids"]}
            ),
        }

    def document_rows(self, revision_id: str, chunk_profile: str) -> Iterator[dict[str, Any]]:
        for row in super().document_rows(revision_id, chunk_profile):
            row["code_payload"] = self._code_payload(
                row, self.owned["id"], self.owned["claim_version"]
            )
            yield row

    def reusable_rows(self, index: dict[str, Any], hashes: list[str]) -> dict[str, dict[str, Any]]:
        # Retry reuse is bounded to this immutable revision and checked by the executor.
        return {}

    def register(self, index: dict[str, Any], rows: list[dict[str, Any]]) -> None:
        with self.database.unit_of_work():
            for row in rows:
                self.database.execute(
                    f"UPDATE {self.t('vector_index_item')} SET point_id=?,state='PENDING',error_code=NULL "
                    "WHERE index_id=? AND chunk_id=? AND point_id<>?",
                    (point_id(index, row), index["id"], row["id"], point_id(index, row)),
                )
            super().register(index, rows)
