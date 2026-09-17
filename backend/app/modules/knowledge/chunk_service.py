"""知识派生批处理：主键分页、来源排他锁、逐文档原子提交。"""

from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import asdict
import hashlib
import json
from typing import Any

from app.modules.knowledge.chunking import CHUNK_VALUE_COLUMNS, DEFAULT_PROFILE, ChunkProfile, PreparedChunks, prepare_chunks
from app.modules.knowledge.ones_export import ExportValidationError, canonical_json, identifier
from app.modules.knowledge.storage import insert, now, source_lock, stable_id, table
from app.shared.database import Database


def json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


class ChunkService:
    def __init__(self, database: Database, *, profile: ChunkProfile = DEFAULT_PROFILE) -> None:
        profile.validate()
        self.database = database
        self.profile = profile

    def _scope(self, code: str) -> tuple[str, str]:
        identifier(code)
        base = self.database.execute_one(f"select id,state from {table(self.database, 'knowledge_base')} where code=?", (code,))
        if not base or base["state"] != "storage_only":
            raise ExportValidationError("knowledge_chunk_base_unavailable")
        sources = self.database.execute(
            f"select distinct d.source_id from {table(self.database, 'document')} d "
            f"join {table(self.database, 'knowledge_base_document')} m on m.document_id=d.id "
            "where m.knowledge_base_id=? and m.state='included' and d.lifecycle_state='active'", (base["id"],),
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

    def _rows(self, base_id: str, source_id: str, *, metadata_only: bool = False) -> Iterator[dict[str, Any]]:
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

    @staticmethod
    def _identity(record: dict[str, Any]) -> bytes:
        return canonical_json([record["document_id"], record["revision_id"], record["content_hash"]]).encode()

    def _validate_existing(self, found: dict[str, Any], record: dict[str, Any], prepared: PreparedChunks) -> None:
        chunks = self.database.execute(
            f"select {','.join(CHUNK_VALUE_COLUMNS)} from {table(self.database, 'document_chunk')} where chunk_set_id=? order by ordinal",
            (found["id"],),
        )
        for chunk in chunks:
            chunk["quality_flags"] = json_value(chunk["quality_flags"])
        if (found["document_id"] != record["document_id"]
                or found["document_revision_id"] != record["revision_id"]
                or found["source_content_hash"] != record["content_hash"]
                or found["profile_version"] != self.profile.version
                or found["profile_hash"] != self.profile.fingerprint
                or json_value(found["profile_config"]) != asdict(self.profile)
                or found["output_hash"] != prepared.output_hash
                or found["chunk_count"] != len(prepared.chunks)
                or json_value(found["normalized_fields"]) != prepared.normalized_fields
                or json_value(found["quality"]) != prepared.quality or chunks != list(prepared.chunks)):
            raise ExportValidationError("knowledge_chunk_stored_result_conflict")

    def _save(self, record: dict[str, Any], prepared: PreparedChunks, base_id: str, source_id: str) -> str:
        with self.database.unit_of_work():
            lock = " for update of d,m" if self.database.engine == "postgres" else ""
            current = self.database.execute_one(
                f"select r.id as revision_id,r.content_hash {self._query()} and d.id=?{lock}",
                (base_id, source_id, record["document_id"]),
            )
            base = self.database.execute_one(f"select state from {table(self.database, 'knowledge_base')} where id=?", (base_id,))
            if (not current or current["revision_id"] != record["revision_id"]
                    or current["content_hash"] != record["content_hash"] or not base or base["state"] != "storage_only"):
                raise ExportValidationError("knowledge_chunk_source_changed")
            set_id = stable_id("chunk-set", record["revision_id"], self.profile.fingerprint)
            found = self.database.execute_one(f"select * from {table(self.database, 'document_chunk_set')} where id=?", (set_id,))
            if found:
                self._validate_existing(found, record, prepared)
                return "reused"
            values = {
                "id": set_id, "document_id": record["document_id"], "document_revision_id": record["revision_id"],
                "source_content_hash": record["content_hash"], "profile_version": self.profile.version,
                "profile_hash": self.profile.fingerprint, "profile_config": asdict(self.profile),
                "normalized_fields": prepared.normalized_fields, "quality": prepared.quality,
                "chunk_count": len(prepared.chunks), "output_hash": prepared.output_hash, "created_at": now(),
            }
            insert(self.database, "document_chunk_set", values)
            for chunk in prepared.chunks:
                insert(self.database, "document_chunk", {
                    "id": stable_id("chunk", set_id, str(chunk["ordinal"])), "chunk_set_id": set_id, **chunk,
                })
            self._validate_existing(values, record, prepared)
            return "created"

    def run(self, *, knowledge_base_code: str, expected_count: int, commit: bool = False,
            progress: Callable[[dict[str, int]], None] | None = None) -> dict[str, Any]:
        if not 1 <= expected_count <= 200_000:
            raise ExportValidationError("knowledge_expected_count_invalid")
        try:
            base_id, source_id = self._scope(knowledge_base_code)
            with source_lock(self.database, source_id):
                if self._scope(knowledge_base_code) != (base_id, source_id):
                    raise ExportValidationError("knowledge_chunk_source_changed")
                initial = self.database.execute_one(f"select count(*) as n {self._query()}", (base_id, source_id))
                if not initial or initial["n"] != expected_count:
                    raise ExportValidationError("knowledge_record_count_mismatch")
                counts: Counter[str] = Counter(dict.fromkeys(
                    ("documents", "chunks", "problem", "solution", "created", "reused", "previewed", "split_problem_documents"), 0,
                ))
                flags: Counter[str] = Counter()
                solutions: Counter[str] = Counter()
                histogram: Counter[str] = Counter()
                minimum, maximum, embedding_max, total_chars = self.profile.max_chars, 0, 0, 0
                input_digest = hashlib.sha256()
                output_digest = hashlib.sha256()
                for record in self._rows(base_id, source_id):
                    if record["document_kind"] != "defect":
                        raise ExportValidationError("knowledge_chunk_kind_unsupported")
                    input_digest.update(self._identity(record))
                    prepared = prepare_chunks(record, self.profile)
                    output_digest.update(prepared.output_hash.encode())
                    outcome = self._save(record, prepared, base_id, source_id) if commit else "previewed"
                    counts[outcome] += 1
                    counts["documents"] += 1
                    solutions[prepared.quality["solution_state"]] += 1
                    counts["split_problem_documents"] += sum(c["chunk_kind"] == "problem" for c in prepared.chunks) > 1
                    for chunk in prepared.chunks:
                        counts["chunks"] += 1
                        counts[chunk["chunk_kind"]] += 1
                        size = chunk["char_count"]
                        minimum, maximum = min(minimum, size), max(maximum, size)
                        embedding_max = max(embedding_max, chunk["embedding_char_count"])
                        total_chars += size
                        histogram["1-300" if size <= 300 else "301-600" if size <= 600 else "601-900" if size <= 900 else "901-1200"] += 1
                        flags.update(chunk["quality_flags"])
                    if progress and (counts["documents"] % 250 == 0 or counts["documents"] == expected_count):
                        progress({"processed": counts["documents"], "total": expected_count})
                final_digest = hashlib.sha256()
                for row in self._rows(base_id, source_id, metadata_only=True):
                    final_digest.update(self._identity(row))
                if counts["documents"] != expected_count or final_digest.digest() != input_digest.digest():
                    raise ExportValidationError("knowledge_chunk_source_changed")
                return {
                    "mode": "commit" if commit else "dry_run", "profile_version": self.profile.version,
                    "profile_hash": self.profile.fingerprint, "input_hash": input_digest.hexdigest(),
                    "output_hash": output_digest.hexdigest(), "counts": dict(counts), "failed_documents": 0,
                    "lengths": {"min": minimum, "max": maximum, "mean": round(total_chars / counts["chunks"], 2),
                                "embedding_max": embedding_max, "histogram": dict(histogram)},
                    "solution_states": dict(solutions), "chunk_quality_flags": dict(flags),
                }
        except ExportValidationError:
            raise
        except Exception:
            raise ExportValidationError("knowledge_chunk_processing_failed") from None
