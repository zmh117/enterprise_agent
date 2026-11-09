"""Version and visibility selection from PostgreSQL; vectors are never the authority."""

from typing import Any

from app.modules.knowledge.domain.code_answers import code_path, path_in_scope, svn_revision
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.infrastructure.code_checkout_store import CodeCheckoutStore, json_value
from app.modules.knowledge.domain.normalization import digest
from app.modules.knowledge.domain.vector_points import payload, point_id
from app.modules.knowledge.infrastructure.code_chunk_repository import CodeVectorRepository
from app.modules.knowledge.infrastructure.code_index_store import index_config_hash


class CodeAnswerReader(CodeCheckoutStore):
    def _query(self, *, metadata_only: bool = False) -> str:
        columns = "d.id AS document_id,a.svn_revision,a.visibility_scope_json,t.id AS index_task_id,t.claim_version"
        if not metadata_only:
            columns = (
                "d.id AS document_id,d.source_id,d.current_revision_id AS revision_id,"
                "a.svn_revision,a.question_text,a.conditions_json,a.visibility_scope_json,"
                "r.title,r.body_text,r.content_hash,x.claims_json,x.coverage_json,x.unknowns_json"
            )
        return (
            f"SELECT {columns} "
            f"FROM {self.t('document')} d "
            f"JOIN {self.t('code_answer')} a ON a.document_id=d.id "
            f"JOIN {self.t('document_revision')} r ON r.id=d.current_revision_id "
            f"JOIN {self.t('code_answer_revision')} x ON x.revision_id=r.id "
            f"JOIN {self.t('knowledge_base_document')} m ON m.document_id=d.id "
            f"JOIN {self.t('code_index_task')} t ON t.document_id=d.id AND t.revision_id=r.id "
            f"JOIN {self.t('vector_index')} i ON i.id=t.index_id AND i.knowledge_base_id=m.knowledge_base_id "
            "WHERE m.knowledge_base_id=? AND d.source_id=? AND i.id=? AND i.source_id=d.source_id "
            "AND d.lifecycle_state='active' AND m.state='included' AND i.state='READY' "
            "AND i.incremental=1 AND t.action='upsert' AND t.state='succeeded' AND t.ready_at IS NOT NULL "
            "AND t.expected_chunks>0 AND t.expected_chunks=t.completed_chunks AND t.config_hash=? "
        )

    def _config_hash(self, index_id: str) -> str:
        row = self.db.execute_one(f"SELECT * FROM {self.t('vector_index')} WHERE id=?", (index_id,))
        if row is None:
            raise CodeKnowledgeError("CODE_INDEX_CONFIGURATION_CHANGED")
        return index_config_hash(row)

    @staticmethod
    def _scope(paths: list[str]) -> list[str]:
        if not isinstance(paths, list) or not 1 <= len(paths) <= 100:
            raise CodeKnowledgeError("CODE_SCOPE_INVALID")
        return [code_path(p, root=True) for p in paths]

    @staticmethod
    def _visible(row: dict[str, Any], paths: list[str]) -> bool:
        scope = json_value(row["visibility_scope_json"])
        return (
            isinstance(scope, dict)
            and set(scope) == {"paths"}
            and isinstance(scope["paths"], list)
            and bool(scope["paths"])
            and all(isinstance(p, str) and path_in_scope(p, paths) for p in scope["paths"])
        )

    def select_version(
        self,
        *,
        base_id: str,
        source_id: str,
        index_id: str,
        revision: int,
        mode: str,
        allowed_paths: list[str],
    ) -> dict[str, Any]:
        """Choose the nearest higher *eligible* version before semantic retrieval.

        A bounded scan cannot prove absence: overflow fails instead of silently
        choosing a farther version or triggering source analysis on a false miss.
        """
        revision = svn_revision(revision)
        paths = self._scope(allowed_paths)
        if mode not in {"exact", "next_higher_hint"}:
            raise CodeKnowledgeError("CODE_VERSION_MODE_INVALID")
        operator = "=" if mode == "exact" else ">"
        rows = self.db.execute(
            self._query(metadata_only=True)
            + f"AND a.svn_revision{operator}? ORDER BY a.svn_revision,d.id LIMIT 2001",
            (base_id, source_id, index_id, self._config_hash(index_id), revision),
        )
        visible = [row for row in rows[:2000] if self._visible(row, paths)]
        selected = visible[0]["svn_revision"] if visible else None
        if len(rows) > 2000 and (selected is None or rows[2000]["svn_revision"] == selected):
            raise CodeKnowledgeError("CODE_VERSION_SELECTION_LIMIT")
        return dict(
            requested_revision=revision,
            matched_revision=selected,
            version_mode=mode,
            requires_code_verification=mode == "next_higher_hint",
            document_ids=[row["document_id"] for row in visible if row["svn_revision"] == selected],
            generation_keys=[
                f"{row['index_task_id']}:{row['claim_version']}"
                for row in visible
                if row["svn_revision"] == selected
            ],
        )

    def get(
        self,
        *,
        base_id: str,
        source_id: str,
        index_id: str,
        document_id: str,
        revision_id: str,
        allowed_paths: list[str],
    ) -> dict[str, Any]:
        rows = self.db.execute(
            self._query() + "AND d.id=? AND d.current_revision_id=?",
            (base_id, source_id, index_id, self._config_hash(index_id), document_id, revision_id),
        )
        if len(rows) != 1 or not self._visible(rows[0], self._scope(allowed_paths)):
            raise CodeKnowledgeError("CODE_ANSWER_UNAVAILABLE")
        result = dict(rows[0])
        for key in (
            "conditions_json",
            "visibility_scope_json",
            "claims_json",
            "coverage_json",
            "unknowns_json",
        ):
            result[key.removesuffix("_json")] = json_value(result.pop(key))
        return {**result, "content_scope": "full_answer", "support_status": "supported"}

    def chunk(
        self, *, index: dict[str, Any], point: dict[str, Any], allowed_paths: list[str]
    ) -> dict[str, Any] | None:
        received = point.get("payload", {})
        if not isinstance(received, dict) or not isinstance(received.get("chunk_id"), str):
            raise CodeKnowledgeError("CODE_SEARCH_CANDIDATE_INVALID")
        row = self.db.execute_one(
            "SELECT c.*,s.document_id,s.document_revision_id,s.source_content_hash,r.content_hash,"
            "t.id AS index_task_id,t.claim_version,v.point_id AS registered_point "
            f"FROM {self.t('document_chunk')} c JOIN {self.t('document_chunk_set')} s ON s.id=c.chunk_set_id "
            f"JOIN {self.t('document_revision')} r ON r.id=s.document_revision_id "
            f"JOIN {self.t('vector_index_item')} v ON v.chunk_id=c.id AND v.index_id=? "
            f"JOIN {self.t('code_index_task')} t ON t.index_id=v.index_id AND t.revision_id=r.id "
            "AND t.action='upsert' AND t.state='succeeded' AND t.ready_at IS NOT NULL "
            "WHERE c.id=? AND s.profile_hash=? AND v.state='INDEXED' AND v.embedding_text_hash=c.embedding_hash",
            (index["id"], received["chunk_id"], index["chunk_profile_hash"]),
        )
        if row is None:
            return None
        if (
            row["source_content_hash"] != row["content_hash"]
            or row["evidence_hash"] != digest(row["evidence_text"])
            or row["embedding_hash"] != digest(row["embedding_text"])
        ):
            raise CodeKnowledgeError("CODE_SEARCH_CANDIDATE_INVALID")
        row["code_payload"] = CodeVectorRepository._code_payload(
            row, row["index_task_id"], row["claim_version"]
        )
        if received.get("index_generation_key") != row["code_payload"]["index_generation_key"]:
            return None  # A correction/reinclude can commit after vector recall.
        if row["registered_point"] != point_id(index, row):
            raise CodeKnowledgeError("CODE_SEARCH_CANDIDATE_INVALID")
        if point.get("id") != point_id(index, row) or received != payload(index, row):
            raise CodeKnowledgeError("CODE_SEARCH_CANDIDATE_INVALID")
        try:
            answer = self.get(
                base_id=index["knowledge_base_id"],
                source_id=index["source_id"],
                index_id=index["id"],
                document_id=row["document_id"],
                revision_id=row["document_revision_id"],
                allowed_paths=allowed_paths,
            )
        except CodeKnowledgeError as exc:
            if exc.code == "CODE_ANSWER_UNAVAILABLE":
                return None  # Membership/current revision may change after vector recall.
            raise
        return {
            "answer": answer,
            "ranking_text": row["embedding_text"],
            "chunk": {
                "chunk_id": row["id"],
                "text": row["evidence_text"],
                "source_start": row["source_start"],
                "source_end": row["source_end"],
                "evidence_hash": row["evidence_hash"],
            },
        }
