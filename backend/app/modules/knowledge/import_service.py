"""离线知识入库事务与幂等性；不包含 DDL、外部 Provider 或运行授权。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
import uuid

from app.modules.knowledge.ones_export import (
    ExportValidationError, PreparedExport, PreparedRecord, digest, identifier,
)
from app.modules.knowledge.storage import insert, now, source_lock, stable_id, table
from app.shared.database import Database


class KnowledgeImportService:
    def __init__(self, database: Database) -> None:
        self.database = database

    @contextmanager
    def _source_lock(self, source_id: str) -> Iterator[None]:
        with source_lock(self.database, source_id):
            yield

    def _insert(self, name: str, values: dict[str, Any], *, conflict: str = "") -> None:
        insert(self.database, name, values, conflict=conflict)

    def import_export(
        self, prepared: PreparedExport, *, source_code: str, knowledge_base_code: str,
        progress: Callable[[dict[str, int]], None] | None = None,
    ) -> dict[str, Any]:
        identifier(source_code)
        identifier(knowledge_base_code)
        source_id = stable_id("source", source_code)
        base_id = stable_id("base", knowledge_base_code)
        input_hash = digest(prepared.manifest)
        run_id = stable_id("import", source_id, base_id, input_hash)
        with self._source_lock(source_id):
            run = self._begin(prepared, source_code, knowledge_base_code, source_id, base_id, run_id, input_hash)
            replayed = run["state"] == "completed"
            if not replayed:
                try:
                    start = int(run["processed_count"])
                    for index in range(start, len(prepared.records)):
                        with self.database.unit_of_work():
                            outcome = self._record(prepared.records[index], source_id, base_id, run_id)
                            self.database.execute(
                                f"update {table(self.database, 'import_run')} set processed_count=processed_count+1, "
                                f"{outcome}_count={outcome}_count+1, updated_at=? where id=?",
                                (now(), run_id),
                            )
                        if progress and ((index + 1) % 250 == 0 or index + 1 == len(prepared.records)):
                            progress({"processed": index + 1, "total": len(prepared.records)})
                    with self.database.unit_of_work():
                        self._resolve_targets(source_id)
                        self.database.execute(
                            f"update {table(self.database, 'import_run')} "
                            "set state='completed', error_code=NULL, completed_at=?, updated_at=? where id=?",
                            (now(), now(), run_id),
                        )
                except Exception as exc:
                    code = exc.code if isinstance(exc, ExportValidationError) else "knowledge_import_failed"
                    with self.database.unit_of_work():
                        self.database.execute(
                            f"update {table(self.database, 'import_run')} "
                            "set state='failed', error_code=?, updated_at=? where id=?",
                            (code, now(), run_id),
                        )
                    raise ExportValidationError(code) from None
            result = self.database.execute_one(
                f"select state,total_count,processed_count,created_count,revised_count,unchanged_count,stale_count "
                f"from {table(self.database, 'import_run')} where id=?", (run_id,),
            )
            assert result is not None
            return {**result, "run_id": run_id, "replayed": replayed,
                    "verification": self.verify(prepared, source_id=source_id, base_id=base_id)}

    def _begin(
        self, prepared: PreparedExport, source_code: str, base_code: str,
        source_id: str, base_id: str, run_id: str, input_hash: str,
    ) -> dict[str, Any]:
        with self.database.unit_of_work():
            self._insert("source", {
                "id": source_id, "code": source_code, "display_name": "ONES 离线导出（来源待确认）",
                "source_system": "ones", "origin_state": "offline_unverified",
                "identity_metadata": {}, "created_at": now(),
            }, conflict="on conflict(code) do nothing")
            source = self.database.execute_one(
                f"select id,source_system,origin_state from {table(self.database, 'source')} where code=?",
                (source_code,),
            )
            if not source or source != {"id": source_id, "source_system": "ones", "origin_state": "offline_unverified"}:
                raise ExportValidationError("knowledge_source_binding_conflict")
            self._insert("knowledge_base", {
                "id": base_id, "code": base_code, "display_name": "ONES 缺陷知识库（离线导入）",
                "description": "用户指定的缺陷文本与关联引用；未开放 Agent 访问，附件及讨论正文未采集。",
                "state": "storage_only", "created_at": now(),
            }, conflict="on conflict(code) do nothing")
            base = self.database.execute_one(
                f"select id,state from {table(self.database, 'knowledge_base')} where code=?", (base_code,),
            )
            if not base or base != {"id": base_id, "state": "storage_only"}:
                raise ExportValidationError("knowledge_base_binding_conflict")
            self._insert("import_run", {
                "id": run_id, "source_id": source_id, "knowledge_base_id": base_id,
                "input_hash": input_hash, "input_manifest": prepared.manifest, "state": "running",
                "total_count": len(prepared.records), "started_at": now(), "updated_at": now(),
            }, conflict="on conflict(source_id,knowledge_base_id,input_hash) do nothing")
            run = self.database.execute_one(
                f"select state,processed_count,total_count from {table(self.database, 'import_run')} where id=?",
                (run_id,),
            )
            if not run or run["total_count"] != len(prepared.records):
                raise ExportValidationError("knowledge_import_checkpoint_invalid")
            if run["state"] != "completed":
                self.database.execute(
                    f"update {table(self.database, 'import_run')} "
                    "set state='running',error_code=NULL,updated_at=? where id=?", (now(), run_id),
                )
            return run

    def _record(self, record: PreparedRecord, source_id: str, base_id: str, run_id: str) -> str:
        document_id = stable_id("document", source_id, "ones_work_item", record.external_id)
        documents = table(self.database, "document")
        revisions = table(self.database, "document_revision")
        current = self.database.execute_one(
            f"select d.lifecycle_state,r.id,r.revision_no,r.content_hash,r.source_update_stamp_raw "
            f"from {documents} d join {revisions} r on r.id=d.current_revision_id where d.id=?",
            (document_id,),
        )
        if current and current["lifecycle_state"] != "active":
            raise ExportValidationError("knowledge_document_unavailable")
        outcome = "created" if current is None else "revised"
        if current and current["content_hash"] == record.content_hash:
            outcome = "unchanged"
        elif current:
            old_stamp = current["source_update_stamp_raw"]
            new_stamp = record.values["source_update_stamp_raw"]
            if old_stamp is not None and (new_stamp is None or new_stamp < old_stamp):
                outcome = "stale"
            elif old_stamp == new_stamp:
                # 同一来源时间不同内容可能是输入冲突，不能靠导入先后猜测更新顺序。
                raise ExportValidationError("knowledge_source_version_conflict")
        if current is None:
            self._insert("document", {
                "id": document_id, "source_id": source_id, "source_object_type": "ones_work_item",
                "external_id": record.external_id, "external_number": record.external_number,
                "document_kind": "defect", "lifecycle_state": "active", "created_at": now(), "last_seen_at": now(),
            })
        if outcome in {"created", "revised"}:
            revision_id = str(uuid.uuid4())
            self._insert("document_revision", {
                "id": revision_id, "document_id": document_id,
                "revision_no": int(current["revision_no"]) + 1 if current else 1,
                "import_run_id": run_id, **record.values, "content_hash": record.content_hash, "ingested_at": now(),
            })
            self.database.execute(
                f"update {documents} set current_revision_id=?,document_kind='defect',external_number=? where id=?",
                (revision_id, record.external_number, document_id),
            )
            for relation in record.relations:
                key = digest({"owner": record.external_id, **relation})
                target = self.database.execute_one(
                    f"select id from {documents} where source_id=? and source_object_type='ones_work_item' and external_id=?",
                    (source_id, relation["target_external_id"]),
                )
                self._insert("document_relation", {
                    "id": stable_id("relation", revision_id, key), "evidence_document_id": document_id,
                    "evidence_revision_id": revision_id, "relation_key": key,
                    "from_source_id": source_id, "from_object_type": "ones_work_item",
                    "from_external_id": record.external_id, "from_document_id": document_id,
                    "to_source_id": source_id, "to_object_type": "ones_work_item",
                    "to_external_id": relation["target_external_id"], "to_document_id": target["id"] if target else None,
                    "source_relation_type": relation["source_relation_type"], "source_direction": relation["source_direction"],
                    "mapping_state": "unmapped", "observed_at": now(),
                })
        self.database.execute(f"update {documents} set last_seen_at=? where id=?", (now(), document_id))
        self._insert("knowledge_base_document", {
            "knowledge_base_id": base_id, "document_id": document_id, "state": "included", "created_at": now(),
        }, conflict="on conflict(knowledge_base_id,document_id) do nothing")
        return outcome

    def _resolve_targets(self, source_id: str) -> None:
        relations = table(self.database, "document_relation")
        documents = table(self.database, "document")
        self.database.execute(
            f"update {relations} as r set to_document_id=(select d.id from {documents} d "
            "where d.source_id=r.to_source_id and d.source_object_type=r.to_object_type "
            "and d.external_id=r.to_external_id) where r.to_source_id=? and r.to_document_id is null",
            (source_id,),
        )

    def verify(self, prepared: PreparedExport, *, source_id: str, base_id: str) -> dict[str, int]:
        documents = table(self.database, "document")
        revisions = table(self.database, "document_revision")
        relations = table(self.database, "document_relation")
        current = self.database.execute(
            f"select d.external_id,d.document_kind,r.content_hash from {documents} d "
            f"join {revisions} r on r.id=d.current_revision_id and r.document_id=d.id where d.source_id=?",
            (source_id,),
        )
        actual = {r["external_id"]: r["content_hash"] for r in current}
        result = {
            "source_documents": len(current),
            "defect_documents": sum(r["document_kind"] == "defect" for r in current),
            "matching_input_documents": sum(actual.get(r.external_id) == r.content_hash for r in prepared.records),
        }
        queries = {
            "source_revisions": (f"select count(*) as n from {revisions} r join {documents} d on d.id=r.document_id where d.source_id=?", (source_id,)),
            "memberships": (f"select count(*) as n from {table(self.database, 'knowledge_base_document')} where knowledge_base_id=? and state='included'", (base_id,)),
            "relation_observations": (f"select count(*) as n from {relations} where from_source_id=?", (source_id,)),
            "resolved_relation_targets": (f"select count(*) as n from {relations} where from_source_id=? and to_document_id is not null", (source_id,)),
            "unresolved_relation_targets": (f"select count(*) as n from {relations} where from_source_id=? and to_document_id is null", (source_id,)),
        }
        for key, (sql, params) in queries.items():
            row = self.database.execute_one(sql, params)
            result[key] = int(row["n"]) if row else 0
        return result
