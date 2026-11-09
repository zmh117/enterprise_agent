"""Explicit, manifest-bound retirement at schema 159. Never run during normal startup.

The operator must stop old containers first. PostgreSQL locks and invocation
quiescence are additional checks, not proof that Docker processes have stopped.
No filesystem deletion and no unscoped CASCADE are permitted here.
"""

from typing import Any

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.normalization import digest
from app.modules.knowledge.infrastructure.code_retirement_inventory import (
    CodeRetirementInventory,
    LEGACY_CODE_TABLES,
)
from app.modules.knowledge.infrastructure.storage import table
from app.shared.database import Database


class CodeRetirement:
    def __init__(self, database: Database) -> None:
        self.db = database

    def retire(self, expected_digest: str) -> dict[str, Any]:
        def t(name: str) -> str:
            return table(self.db, name)

        with self.db.unit_of_work():
            head = self.db.execute_one("SELECT max(version) AS version FROM schema_migration")
            if not head or head["version"] != "159":
                raise CodeKnowledgeError("CODE_RETIREMENT_SCHEMA_MISMATCH")
            if self.db.engine == "postgres":
                self.db.execute("SET LOCAL lock_timeout='3s'")
                # All legacy writers and mutable content are fenced for this transaction.
                names = (
                    *LEGACY_CODE_TABLES,
                    "document",
                    "document_revision",
                    "knowledge_base_document",
                    "document_relation",
                    "document_chunk_set",
                    "document_chunk",
                    "vector_index_item",
                    "vector_index",
                    "import_run",
                    "retrieval_resource",
                    "retrieval_revision",
                    "retrieval_verification",
                )
                self.db.execute(
                    "LOCK TABLE " + ",".join(t(n) for n in names) + " IN SHARE ROW EXCLUSIVE MODE"
                )
            before = CodeRetirementInventory(self.db)._inspect()
            if digest(before) != expected_digest:
                raise CodeKnowledgeError("CODE_RETIREMENT_INVENTORY_CHANGED")
            objects = before["objects"]
            if any(before["scope_conflicts"].values()):
                raise CodeKnowledgeError("CODE_RETIREMENT_MIXED_SCOPE")
            # Current accepted inventory has no legacy code vector index. Refuse an
            # unexpected remote deletion; it needs its own exact collection plan.
            if objects["indexes"]:
                raise CodeKnowledgeError("CODE_RETIREMENT_VECTOR_PLAN_REQUIRED")
            if any(i["execution_quiesced_at"] is None for i in objects["invocations"]):
                raise CodeKnowledgeError("CODE_RETIREMENT_RUNTIME_NOT_STOPPED")
            if any(c["state"] in {"QUEUED", "RUNNING"} for c in objects["checkouts"]):
                raise CodeKnowledgeError("CODE_RETIREMENT_SVN_NOT_STOPPED")
            source_ids = [b["source_id"] for b in objects["bindings"]]
            if not source_ids:
                return {"inventory_digest": expected_digest, "retired_documents": 0}
            marks = ",".join("?" for _ in source_ids)
            sources = f"({marks})"
            documents = f"SELECT id FROM {t('document')} WHERE source_id IN {sources}"
            revisions = (
                f"SELECT id FROM {t('document_revision')} WHERE document_id IN ({documents})"
            )
            chunks = f"SELECT id FROM {t('document_chunk')} WHERE chunk_set_id IN (SELECT id FROM {t('document_chunk_set')} WHERE document_id IN ({documents}))"
            bases = (
                f"SELECT knowledge_base_id FROM {t('code_binding')} WHERE source_id IN {sources}"
            )
            resources = (
                f"SELECT id FROM {t('retrieval_resource')} WHERE knowledge_base_id IN ({bases})"
            )
            args = tuple(source_ids)
            self.db.execute(
                f"UPDATE {t('code_binding')} SET enabled=0,demand_enabled=0,active_snapshot_id=NULL WHERE source_id IN {sources}",
                args,
            )
            self.db.execute(
                f"UPDATE {t('retrieval_resource')} SET status='disabled',published_revision_id=NULL,draft_revision_id=NULL,state_revision=state_revision+1 WHERE id IN ({resources})",
                args,
            )
            self.db.execute(
                f"DELETE FROM {t('retrieval_verification')} WHERE resource_id IN ({resources})",
                args,
            )
            self.db.execute(
                f"DELETE FROM {t('retrieval_revision')} WHERE resource_id IN ({resources})", args
            )
            # Dedicated legacy tables are fully enumerated in the exact inventory.
            for name in (
                "code_transition_failure",
                "code_transition_source",
                "code_transition",
                "code_state",
                "code_event",
                "code_machine",
                "code_object",
                "code_history_check",
                "code_relation",
                "code_member",
                "code_dependency",
                "code_demand",
                "code_unit",
                "code_build",
                "code_snapshot",
                "code_commit",
                "code_source_file",
                "code_source_snapshot",
            ):
                self.db.execute(f"DELETE FROM {t(name)}")
            for name, predicate in (
                ("vector_index_item", f"chunk_id IN ({chunks})"),
                ("document_chunk", f"id IN ({chunks})"),
                ("document_chunk_set", f"document_id IN ({documents})"),
                ("document_relation", f"evidence_revision_id IN ({revisions})"),
                ("knowledge_base_document", f"document_id IN ({documents})"),
            ):
                self.db.execute(f"DELETE FROM {t(name)} WHERE {predicate}", args)
            self.db.execute(
                f"UPDATE {t('document')} SET current_revision_id=NULL WHERE source_id IN {sources}",
                args,
            )
            self.db.execute(
                f"DELETE FROM {t('document_revision')} WHERE document_id IN ({documents})", args
            )
            self.db.execute(f"DELETE FROM {t('document')} WHERE source_id IN {sources}", args)
            self.db.execute(f"DELETE FROM {t('import_run')} WHERE source_id IN {sources}", args)
            after = CodeRetirementInventory(self.db)._inspect()
            if (
                after["retained_other_source_document_count"]
                != before["retained_other_source_document_count"]
                or after["objects"]["checkouts"] != objects["checkouts"]
                or after["objects"]["invocations"]
            ):
                raise CodeKnowledgeError("CODE_RETIREMENT_PRESERVATION_FAILED")
            return {
                "inventory_digest": expected_digest,
                "retired_documents": len(objects["documents"]),
                "retained_other_documents": after["retained_other_source_document_count"],
                "retained_checkout_records": len(objects["checkouts"]),
                "after_digest": digest(after),
            }
