"""知识派生批处理：主键分页、来源排他锁、逐文档原子提交。"""

from collections.abc import Iterator
from contextlib import AbstractContextManager
from dataclasses import asdict
import json
from typing import Any

from app.modules.knowledge.domain.chunking import (
    CHUNK_VALUE_COLUMNS,
    DEFAULT_PROFILE,
    ChunkProfile,
    PreparedChunks,
)
from app.modules.knowledge.domain.normalization import ExportValidationError, identifier
from app.modules.knowledge.infrastructure.storage import insert, source_lock, table
from app.modules.knowledge.domain.identity import now, stable_id
from app.shared.database import Database


def json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


class ChunkRepository:
    def __init__(self, database: Database, *, profile: ChunkProfile = DEFAULT_PROFILE) -> None:
        profile.validate()
        self.database = database
        self.profile = profile

    def scope(self, code: str) -> tuple[str, str]:
        identifier(code)
        base = self.database.execute_one(
            f"select id,state from {table(self.database, 'knowledge_base')} where code=?", (code,)
        )
        if not base or base["state"] != "storage_only":
            raise ExportValidationError("knowledge_chunk_base_unavailable")
        sources = self.database.execute(
            f"select distinct d.source_id from {table(self.database, 'document')} d "
            f"join {table(self.database, 'knowledge_base_document')} m on m.document_id=d.id "
            "where m.knowledge_base_id=? and m.state='included' and d.lifecycle_state='active'",
            (base["id"],),
        )
        if len(sources) != 1:
            raise ExportValidationError("knowledge_chunk_single_source_required")
        return base["id"], sources[0]["source_id"]

    def _query(self) -> str:
        return (
            f"from {table(self.database, 'document')} d "
            f"join {table(self.database, 'document_revision')} r on r.id=d.current_revision_id and r.document_id=d.id "
            f"join {table(self.database, 'knowledge_base_document')} m on m.document_id=d.id "
            "where m.knowledge_base_id=? and m.state='included' and d.lifecycle_state='active' and d.source_id=? "
        )

    def rows(
        self, base_id: str, source_id: str, *, metadata_only: bool = False
    ) -> Iterator[dict[str, Any]]:
        cursor = ""
        columns = "d.id as document_id,r.id as revision_id,r.content_hash"
        if not metadata_only:
            columns += ",d.document_kind,r.title,r.body_text,r.source_project_name,r.normalizer_version,r.attributes,r.completeness"
        while True:
            rows = self.database.execute(
                f"select {columns} {self._query()} and d.id>? order by d.id limit 100",
                (base_id, source_id, cursor),
            )
            if not rows:
                return
            for row in rows:
                if not metadata_only:
                    row["attributes"] = json_value(row["attributes"])
                    row["completeness"] = json_value(row["completeness"])
                yield row
            cursor = rows[-1]["document_id"]

    def _validate_existing(
        self, found: dict[str, Any], record: dict[str, Any], prepared: PreparedChunks
    ) -> None:
        chunks = self.database.execute(
            f"select {','.join(CHUNK_VALUE_COLUMNS)} from {table(self.database, 'document_chunk')} where chunk_set_id=? order by ordinal",
            (found["id"],),
        )
        for chunk in chunks:
            chunk["quality_flags"] = json_value(chunk["quality_flags"])
        if (
            found["document_id"] != record["document_id"]
            or found["document_revision_id"] != record["revision_id"]
            or found["source_content_hash"] != record["content_hash"]
            or found["profile_version"] != self.profile.version
            or found["profile_hash"] != self.profile.fingerprint
            or json_value(found["profile_config"]) != asdict(self.profile)
            or found["output_hash"] != prepared.output_hash
            or found["chunk_count"] != len(prepared.chunks)
            or json_value(found["normalized_fields"]) != prepared.normalized_fields
            or json_value(found["quality"]) != prepared.quality
            or chunks != list(prepared.chunks)
        ):
            raise ExportValidationError("knowledge_chunk_stored_result_conflict")

    def save(
        self, record: dict[str, Any], prepared: PreparedChunks, base_id: str, source_id: str
    ) -> str:
        with self.database.unit_of_work():
            lock = " for update of d,m" if self.database.engine == "postgres" else ""
            current = self.database.execute_one(
                f"select r.id as revision_id,r.content_hash {self._query()} and d.id=?{lock}",
                (base_id, source_id, record["document_id"]),
            )
            base = self.database.execute_one(
                f"select state from {table(self.database, 'knowledge_base')} where id=?", (base_id,)
            )
            if (
                not current
                or current["revision_id"] != record["revision_id"]
                or current["content_hash"] != record["content_hash"]
                or not base
                or base["state"] != "storage_only"
            ):
                raise ExportValidationError("knowledge_chunk_source_changed")
            return self._save_immutable(record, prepared)

    def _save_immutable(self, record: dict[str, Any], prepared: PreparedChunks) -> str:
        # 调用方已在同一事务内校验当前成员或冻结候选；共享不可变派生保存规则。
        set_id = stable_id("chunk-set", record["revision_id"], self.profile.fingerprint)
        found = self.database.execute_one(
            f"select * from {table(self.database, 'document_chunk_set')} where id=?", (set_id,)
        )
        if found:
            self._validate_existing(found, record, prepared)
            return "reused"
        values = {
            "id": set_id,
            "document_id": record["document_id"],
            "document_revision_id": record["revision_id"],
            "source_content_hash": record["content_hash"],
            "profile_version": self.profile.version,
            "profile_hash": self.profile.fingerprint,
            "profile_config": asdict(self.profile),
            "normalized_fields": prepared.normalized_fields,
            "quality": prepared.quality,
            "chunk_count": len(prepared.chunks),
            "output_hash": prepared.output_hash,
            "created_at": now(),
        }
        insert(self.database, "document_chunk_set", values)
        for chunk in prepared.chunks:
            insert(
                self.database,
                "document_chunk",
                {
                    "id": stable_id("chunk", set_id, str(chunk["ordinal"])),
                    "chunk_set_id": set_id,
                    **chunk,
                },
            )
        self._validate_existing(values, record, prepared)
        return "created"

    def source_lock(self, source_id: str) -> AbstractContextManager[None]:
        return source_lock(self.database, source_id)

    def count(self, base_id: str, source_id: str) -> int:
        row = self.database.execute_one(
            f"select count(*) as n {self._query()}", (base_id, source_id)
        )
        return int(row["n"]) if row else 0
