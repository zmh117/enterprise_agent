"""离线知识入库事务与幂等性；不包含 DDL、外部 Provider 或运行授权。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
import uuid

from app.modules.knowledge.domain.normalization import (
    ExportValidationError,
    PreparedExport,
    PreparedRecord,
)
from app.modules.knowledge.infrastructure.storage import insert, source_lock, table
from app.modules.knowledge.domain.identity import now, stable_id
from app.modules.knowledge.domain.work_items import KIND_LABELS, compare_version, document_kind
from app.modules.knowledge.infrastructure.revision_store import save_revision
from app.shared.database import Database


class ImportRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    @contextmanager
    def source_lock(self, source_id: str) -> Iterator[None]:
        with source_lock(self.database, source_id):
            yield

    def _insert(self, name: str, values: dict[str, Any], *, conflict: str = "") -> None:
        insert(self.database, name, values, conflict=conflict)

    def begin(
        self,
        prepared: PreparedExport,
        source_code: str,
        base_code: str,
        source_id: str,
        base_id: str,
        run_id: str,
        input_hash: str,
    ) -> dict[str, Any]:
        kind = document_kind(prepared.manifest.get("document_kind"))
        if any(record.document_kind != kind for record in prepared.records):
            raise ExportValidationError("knowledge_source_type_mismatch")
        with self.database.unit_of_work():
            existing = self.database.execute_one(
                f"select state,processed_count,total_count from {table(self.database, 'import_run')} where id=?",
                (run_id,),
            )
            if existing and existing["state"] == "completed":
                if existing["total_count"] != len(prepared.records):
                    raise ExportValidationError("knowledge_import_checkpoint_invalid")
                return existing
            self._assert_direct_write_allowed(source_id, base_id)
            self._insert(
                "source",
                {
                    "id": source_id,
                    "code": source_code,
                    "display_name": "ONES 离线导出（来源待确认）",
                    "source_system": "ones",
                    "origin_state": "offline_unverified",
                    "identity_metadata": {},
                    "created_at": now(),
                },
                conflict="on conflict(code) do nothing",
            )
            source = self.database.execute_one(
                f"select id,source_system,origin_state from {table(self.database, 'source')} where code=?",
                (source_code,),
            )
            if not source or source != {
                "id": source_id,
                "source_system": "ones",
                "origin_state": "offline_unverified",
            }:
                raise ExportValidationError("knowledge_source_binding_conflict")
            self._insert(
                "knowledge_base",
                {
                    "id": base_id,
                    "code": base_code,
                    "display_name": f"ONES {KIND_LABELS[kind]}知识库（离线导入）",
                    "description": f"用户指定的{KIND_LABELS[kind]}文本与关联引用；未开放 Agent 访问，附件及讨论正文未采集。",
                    "state": "storage_only",
                    "created_at": now(),
                },
                conflict="on conflict(code) do nothing",
            )
            base = self.database.execute_one(
                f"select id,state from {table(self.database, 'knowledge_base')} where code=?",
                (base_code,),
            )
            if not base or base != {"id": base_id, "state": "storage_only"}:
                raise ExportValidationError("knowledge_base_binding_conflict")
            self._insert(
                "import_run",
                {
                    "id": run_id,
                    "source_id": source_id,
                    "knowledge_base_id": base_id,
                    "input_hash": input_hash,
                    "input_manifest": prepared.manifest,
                    "state": "running",
                    "total_count": len(prepared.records),
                    "started_at": now(),
                    "updated_at": now(),
                },
                conflict="on conflict(source_id,knowledge_base_id,input_hash) do nothing",
            )
            run = self.database.execute_one(
                f"select state,processed_count,total_count from {table(self.database, 'import_run')} where id=?",
                (run_id,),
            )
            if not run or run["total_count"] != len(prepared.records):
                raise ExportValidationError("knowledge_import_checkpoint_invalid")
            if run["state"] != "completed":
                self.database.execute(
                    f"update {table(self.database, 'import_run')} "
                    "set state='running',error_code=NULL,updated_at=? where id=?",
                    (now(), run_id),
                )
            return run

    def _assert_direct_write_allowed(self, source_id: str, base_id: str) -> None:
        active = self.database.execute_one(
            f"select id from {table(self.database, 'sync_run')} where source_id=? and active=1",
            (source_id,),
        )
        if active:
            raise ExportValidationError("knowledge_source_import_busy")
        # 现有发布摘要包含整个 source；即便写另一个 KB 也不能绕过候选流程。
        published = self.database.execute_one(
            f"select r.id from {table(self.database, 'retrieval_resource')} r "
            "where r.published_revision_id is not null and (r.knowledge_base_id=? or exists("
            f"select 1 from {table(self.database, 'knowledge_base_document')} m "
            f"join {table(self.database, 'document')} d on d.id=m.document_id "
            "where m.knowledge_base_id=r.knowledge_base_id and d.source_id=?)) limit 1",
            (base_id, source_id),
        )
        if published:
            raise ExportValidationError("knowledge_published_source_requires_staging")

    def record(self, record: PreparedRecord, source_id: str, base_id: str, run_id: str) -> str:
        kind = document_kind(record.document_kind)
        self._assert_direct_write_allowed(source_id, base_id)
        document_id = stable_id("document", source_id, "ones_work_item", record.external_id)
        documents = table(self.database, "document")
        revisions = table(self.database, "document_revision")
        current = self.database.execute_one(
            f"select d.lifecycle_state,d.document_kind,r.id,r.revision_no,r.content_hash,r.source_update_stamp_raw "
            f"from {documents} d join {revisions} r on r.id=d.current_revision_id where d.id=?",
            (document_id,),
        )
        if current and current["lifecycle_state"] != "active":
            raise ExportValidationError("knowledge_document_unavailable")
        outcome = "created" if current is None else "revised"
        if current:
            outcome = compare_version(
                old_stamp=current["source_update_stamp_raw"],
                new_stamp=record.values["source_update_stamp_raw"],
                old_hash=current["content_hash"],
                new_hash=record.content_hash,
                old_kind=current["document_kind"],
                new_kind=kind,
            )
            if outcome != "stale" and current["document_kind"] != kind:
                # 跨 KB 迁移由候选激活原子处理，不由单文件导入猜测其他库成员。
                raise ExportValidationError("knowledge_type_change_requires_staging")
        if current is None:
            self._insert(
                "document",
                {
                    "id": document_id,
                    "source_id": source_id,
                    "source_object_type": "ones_work_item",
                    "external_id": record.external_id,
                    "external_number": record.external_number,
                    "document_kind": kind,
                    "lifecycle_state": "active",
                    "created_at": now(),
                    "last_seen_at": now(),
                },
            )
        if outcome in {"created", "revised"}:
            revision_id = str(uuid.uuid4())
            save_revision(
                self.database,
                record,
                source_id=source_id,
                document_id=document_id,
                revision_id=revision_id,
                import_run_id=run_id,
                revision_no=int(current["revision_no"]) + 1 if current else 1,
            )
            self.database.execute(
                f"update {documents} set current_revision_id=?,document_kind=?,external_number=? where id=?",
                (revision_id, kind, record.external_number, document_id),
            )
        self.database.execute(
            f"update {documents} set last_seen_at=? where id=?", (now(), document_id)
        )
        if outcome == "stale":
            return outcome
        self._insert(
            "knowledge_base_document",
            {
                "knowledge_base_id": base_id,
                "document_id": document_id,
                "state": "included",
                "created_at": now(),
            },
            conflict="on conflict(knowledge_base_id,document_id) do nothing",
        )
        return outcome

    def resolve_targets(self, source_id: str) -> None:
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
            "matching_input_documents": sum(
                actual.get(r.external_id) == r.content_hash for r in prepared.records
            ),
        }
        kind = prepared.manifest["document_kind"]
        if kind != "defect":
            result[f"{kind}_documents"] = sum(r["document_kind"] == kind for r in current)
        queries = {
            "source_revisions": (
                f"select count(*) as n from {revisions} r join {documents} d on d.id=r.document_id where d.source_id=?",
                (source_id,),
            ),
            "memberships": (
                f"select count(*) as n from {table(self.database, 'knowledge_base_document')} where knowledge_base_id=? and state='included'",
                (base_id,),
            ),
            "relation_observations": (
                f"select count(*) as n from {relations} where from_source_id=?",
                (source_id,),
            ),
            "resolved_relation_targets": (
                f"select count(*) as n from {relations} where from_source_id=? and to_document_id is not null",
                (source_id,),
            ),
            "unresolved_relation_targets": (
                f"select count(*) as n from {relations} where from_source_id=? and to_document_id is null",
                (source_id,),
            ),
        }
        for key, (sql, params) in queries.items():
            row = self.database.execute_one(sql, params)
            result[key] = int(row["n"]) if row else 0
        return result

    def commit_record(
        self, record: PreparedRecord, source_id: str, base_id: str, run_id: str
    ) -> None:
        with self.database.unit_of_work():
            outcome = self.record(record, source_id, base_id, run_id)
            self.database.execute(
                f"update {table(self.database, 'import_run')} set processed_count=processed_count+1, "
                f"{outcome}_count={outcome}_count+1, updated_at=? where id=?",
                (now(), run_id),
            )

    def complete(self, source_id: str, run_id: str) -> None:
        with self.database.unit_of_work():
            self.resolve_targets(source_id)
            self.database.execute(
                f"update {table(self.database, 'import_run')} set state='completed', error_code=NULL, completed_at=?, updated_at=? where id=?",
                (now(), now(), run_id),
            )

    def fail(self, run_id: str, code: str) -> None:
        with self.database.unit_of_work():
            self.database.execute(
                f"update {table(self.database, 'import_run')} set state='failed', error_code=?, updated_at=? where id=?",
                (code, now(), run_id),
            )

    def result(self, run_id: str) -> dict[str, Any]:
        result = self.database.execute_one(
            f"select state,total_count,processed_count,created_count,revised_count,unchanged_count,stale_count from {table(self.database, 'import_run')} where id=?",
            (run_id,),
        )
        assert result is not None
        return result
