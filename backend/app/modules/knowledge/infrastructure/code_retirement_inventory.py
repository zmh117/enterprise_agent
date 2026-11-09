"""Read-only inventory for retiring pre-extraction data, never source bytes or secrets."""

from datetime import date, datetime
from typing import Any

from app.modules.knowledge.domain.normalization import digest
from app.modules.knowledge.infrastructure.storage import table
from app.shared.database import Database


LEGACY_CODE_TABLES = (
    "code_binding",
    "code_source_snapshot",
    "code_source_file",
    "code_commit",
    "code_snapshot",
    "code_build",
    "code_unit",
    "code_member",
    "code_relation",
    "code_dependency",
    "code_history_check",
    "code_demand",
    "code_object",
    "code_machine",
    "code_event",
    "code_state",
    "code_transition",
    "code_transition_source",
    "code_transition_failure",
    "code_checkout_job",
)


class CodeRetirementInventory:
    """An allowlisted metadata inventory; no arbitrary queries or JSON payload reads."""

    def __init__(self, database: Database) -> None:
        self.db = database

    def inspect(self) -> dict[str, Any]:
        with self.db.unit_of_work():
            if self.db.engine == "postgres":
                self.db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            result = self._inspect()
        return {"manifest": result, "digest": digest(result)}

    def _inspect(self) -> dict[str, Any]:
        def t(name: str) -> str:
            return table(self.db, name)

        sources = f"select source_id from {t('code_binding')}"
        bases = f"select knowledge_base_id from {t('code_binding')}"
        documents = f"select id from {t('document')} where source_id in ({sources})"
        revisions = f"select id from {t('document_revision')} where document_id in ({documents})"
        manifests = {
            "bindings": f"select source_id,knowledge_base_id,enabled,demand_enabled,active_snapshot_id from {t('code_binding')} order by source_id",
            "documents": f"select id,source_id,source_object_type,document_kind,current_revision_id from {t('document')} where id in ({documents}) order by id",
            "revisions": f"select id,document_id,import_run_id,content_hash from {t('document_revision')} where id in ({revisions}) order by id",
            "memberships": f"select knowledge_base_id,document_id,state from {t('knowledge_base_document')} where document_id in ({documents}) order by knowledge_base_id,document_id",
            "indexes": f"select id,knowledge_base_id,source_id,state,collection_name from {t('vector_index')} where knowledge_base_id in ({bases}) or source_id in ({sources}) order by id",
            "resources": f"select id,knowledge_base_id,status,draft_revision_id,published_revision_id from {t('retrieval_resource')} where knowledge_base_id in ({bases}) order by id",
            "builds": f"select id,source_id,stage,active from {t('code_build')} order by id",
            "unit_jobs": f"select u.id as unit_id,u.job_id,u.state,j.status as job_status from {t('code_unit')} u left join agent_job j on j.id=u.job_id order by u.id",
            "invocations": f"select i.invocation_id,i.job_id,i.state,i.execution_quiesced_at from agent_runtime_invocation i join {t('code_unit')} u on u.job_id=i.job_id order by i.invocation_id",
            "checkouts": f"select id,kind,state from {t('code_checkout_job')} order by id",
            "imports": f"select id,source_id,knowledge_base_id,state from {t('import_run')} where source_id in ({sources}) order by id",
            "chunk_sets": f"select id,document_id,document_revision_id from {t('document_chunk_set')} where document_id in ({documents}) order by id",
            "chunks": f"select id,chunk_set_id from {t('document_chunk')} where chunk_set_id in (select id from {t('document_chunk_set')} where document_id in ({documents})) order by id",
            "retrieval_revisions": f"select id,resource_id from {t('retrieval_revision')} where resource_id in (select id from {t('retrieval_resource')} where knowledge_base_id in ({bases})) order by id",
        }
        rows = {key: self.db.execute(query) for key, query in manifests.items()}
        for invocation in rows["invocations"]:
            stopped = invocation["execution_quiesced_at"]
            if isinstance(stopped, (datetime, date)):
                invocation["execution_quiesced_at"] = stopped.isoformat()
        counts = {
            name: self._count(f"select count(*) as count from {t(name)}")
            for name in LEGACY_CODE_TABLES
        }
        conflicts = {
            "non_code_documents_in_code_bases": self._count(
                f"select count(*) as count from {t('knowledge_base_document')} m "
                f"where m.knowledge_base_id in ({bases}) and m.document_id not in ({documents})"
            ),
            "code_documents_in_other_bases": self._count(
                f"select count(*) as count from {t('knowledge_base_document')} m "
                f"where m.document_id in ({documents}) and m.knowledge_base_id not in ({bases})"
            ),
            "cross_source_relations": self._count(
                f"select count(*) as count from {t('document_relation')} "
                f"where evidence_revision_id not in ({revisions}) and "
                f"(from_document_id in ({documents}) or to_document_id in ({documents}))"
            ),
        }
        # Publication snapshots contain tool names, not original messages or credentials.
        publications = {}
        for name, column in (
            ("agent_publication_mcp_tool", "agent_publication_id"),
            ("business_application_publication_mcp_tool", "application_publication_id"),
        ):
            publications[name] = self.db.execute(
                f"select distinct {column} as publication_id,tool_identifier from {name} "
                "where server_code='knowledge-mcp' order by publication_id,tool_identifier"
            )
        head = self.db.execute_one("select max(version) as version from schema_migration")
        assert head is not None
        return {
            "format_version": 1,
            "schema_head": head["version"],
            "legacy_table_counts": counts,
            "objects": rows,
            "publication_tools": publications,
            "scope_conflicts": conflicts,
            "retained_other_source_document_count": self._count(
                f"select count(*) as count from {t('document')} where id not in ({documents})"
            ),
        }

    def _count(self, query: str) -> int:
        row = self.db.execute_one(query)
        assert row is not None
        return int(row["count"])
