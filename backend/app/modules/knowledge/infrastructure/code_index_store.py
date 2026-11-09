"""Durable code-answer derivation. Row leases never prove a previous worker stopped."""

from datetime import timedelta
from typing import Any

from app.modules.agent.infrastructure.runtime_pool_store import database_now, timestamp
from app.modules.knowledge.domain.code_configuration import CODE_CHUNK_PROFILE, MANAGED_CODE_STORAGE
from app.modules.knowledge.domain.code_answers import utc_time
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.identity import stable_id
from app.modules.knowledge.domain.normalization import digest
from app.modules.knowledge.infrastructure.code_checkout_store import CodeCheckoutStore, json_value
from app.modules.knowledge.infrastructure.storage import insert


def index_config_hash(index: dict[str, Any]) -> str:
    return digest(
        {
            "target": MANAGED_CODE_STORAGE,
            **{
                key: index[key]
                for key in (
                    "id",
                    "knowledge_base_id",
                    "source_id",
                    "collection_name",
                    "profile_hash",
                    "chunk_profile_hash",
                    "incremental",
                )
            },
        }
    )


class CodeIndexStore(CodeCheckoutStore):
    def _document_lock(self, document_id: str) -> None:
        suffix = " FOR UPDATE" if self.db.engine == "postgres" else ""
        if not self.db.execute_one(
            f"SELECT id FROM {self.t('document')} WHERE id=?{suffix}", (document_id,)
        ):
            raise CodeKnowledgeError("CODE_ANSWER_UNAVAILABLE")

    def enqueue(
        self,
        index: dict[str, Any],
        document_id: str,
        revision_id: str,
        action: str,
        *,
        restart: bool = False,
    ) -> None:
        if self.db.current_unit_of_work is None:
            raise RuntimeError("Index intent must commit with content or membership")
        self._document_lock(document_id)
        stamp = timestamp(database_now(self.db))
        identifier = stable_id("code-index-task", index["id"], revision_id, action)
        insert(
            self.db,
            "code_index_task",
            dict(
                id=identifier,
                index_id=index["id"],
                document_id=document_id,
                revision_id=revision_id,
                action=action,
                config_hash=index_config_hash(index),
                state="queued",
                created_at=stamp,
                updated_at=stamp,
            ),
            conflict="ON CONFLICT(index_id,revision_id,action) DO NOTHING",
        )
        row = self.row("code_index_task", identifier, lock=True)
        if row["config_hash"] != index_config_hash(index):
            raise CodeKnowledgeError("CODE_INDEX_CONFIGURATION_CHANGED")
        if restart:
            # A running call retains its generation until the executor has returned.
            # Its next gate observes membership/current revision and cannot mark stale work ready.
            self.db.execute(
                f"UPDATE {self.t('code_index_task')} SET ready_at=NULL,updated_at=? WHERE id=?",
                (stamp, identifier),
            )
            if row["state"] != "running":
                self.db.execute(
                    f"UPDATE {self.t('code_index_task')} SET state='queued',step='pending',"
                    "claim_version=claim_version+1,expected_chunks=0,completed_chunks=0,"
                    "owner_instance_id=NULL,lease_until=NULL,next_attempt_at=NULL,error_code=NULL,"
                    "attempt_count=0,finished_at=NULL WHERE id=?",
                    (identifier,),
                )

    def _current(self, row: dict[str, Any]) -> tuple[dict[str, Any], bool, bool]:
        index = self.db.execute_one(
            f"SELECT i.*,k.kind,k.code_indexing_paused FROM {self.t('vector_index')} i "
            f"JOIN {self.t('knowledge_base')} k ON k.id=i.knowledge_base_id WHERE i.id=?",
            (row["index_id"],),
        )
        if (
            not index
            or index["kind"] != "code"
            or index["incremental"] != 1
            or index["state"] != "READY"
            or index["chunk_profile_hash"] != CODE_CHUNK_PROFILE.fingerprint
            or index_config_hash(index) != row["config_hash"]
        ):
            raise CodeKnowledgeError("CODE_INDEX_CONFIGURATION_CHANGED")
        current = self.db.execute_one(
            f"SELECT d.current_revision_id,d.lifecycle_state,m.state FROM {self.t('document')} d "
            f"LEFT JOIN {self.t('knowledge_base_document')} m ON m.document_id=d.id AND m.knowledge_base_id=? "
            "WHERE d.id=? AND d.source_id=?",
            (index["knowledge_base_id"], row["document_id"], index["source_id"]),
        )
        included = bool(
            current
            and current["lifecycle_state"] == "active"
            and current["state"] == "included"
            and current["current_revision_id"] == row["revision_id"]
        )
        index["profile"] = json_value(index["profile"])
        return (
            index,
            included if row["action"] == "upsert" else not included,
            bool(index["code_indexing_paused"]),
        )

    def claim(self, identifier: str, owner: str) -> dict[str, Any] | None:
        candidate = self.row("code_index_task", identifier)
        with self.db.unit_of_work():
            self._document_lock(candidate["document_id"])
            row = self.row("code_index_task", identifier, lock=True)
            stamp = timestamp(database_now(self.db))
            if row["state"] != "queued" and not (
                row["state"] == "failed"
                and row["next_attempt_at"]
                and utc_time(row["next_attempt_at"]) <= database_now(self.db)
            ):
                return None
            if self.db.execute_one(
                f"SELECT id FROM {self.t('code_index_task')} WHERE index_id=? AND document_id=? AND state='running'",
                (row["index_id"], row["document_id"]),
            ):
                return None
            try:
                _, wanted, paused = self._current(row)
            except CodeKnowledgeError:
                self._cancel(row, "CODE_INDEX_CONFIGURATION_CHANGED")
                return None
            if not wanted:
                self._cancel(row, "CODE_INDEX_INTENT_CHANGED")
                return None
            if paused:
                return None
            lease = timestamp(database_now(self.db) + timedelta(seconds=30))
            self.db.execute(
                f"UPDATE {self.t('code_index_task')} SET state='running',owner_instance_id=?,"
                "claim_version=claim_version+1,lease_until=?,attempt_count=attempt_count+1,"
                "next_attempt_at=NULL,error_code=NULL,ready_at=NULL,finished_at=NULL,updated_at=? WHERE id=?",
                (owner, lease, stamp, identifier),
            )
            return self.row("code_index_task", identifier)

    def _cancel(self, row: dict[str, Any], code: str) -> None:
        stamp = timestamp(database_now(self.db))
        self.db.execute(
            f"UPDATE {self.t('code_index_task')} SET state='cancelled',error_code=?,ready_at=NULL,"
            "lease_until=NULL,finished_at=?,updated_at=? WHERE id=?",
            (code, stamp, stamp, row["id"]),
        )

    def active(self, owned: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        row = self.row("code_index_task", owned["id"])
        if row["state"] != "running" or any(
            row[k] != owned[k] for k in ("claim_version", "owner_instance_id")
        ):
            raise CodeKnowledgeError("CODE_INDEX_CLAIM_LOST")
        index, wanted, paused = self._current(row)
        if not wanted:
            raise CodeKnowledgeError("CODE_INDEX_INTENT_CHANGED")
        if paused:
            raise CodeKnowledgeError("CODE_INDEX_PAUSED")
        self.db.execute(
            f"UPDATE {self.t('code_index_task')} SET lease_until=?,updated_at=? WHERE id=? AND state='running' AND claim_version=? AND owner_instance_id=?",
            (
                timestamp(database_now(self.db) + timedelta(seconds=30)),
                timestamp(database_now(self.db)),
                row["id"],
                row["claim_version"],
                row["owner_instance_id"],
            ),
        )
        return row, index

    def record(self, owned: dict[str, Any]) -> dict[str, Any]:
        self.active(owned)
        row = self.db.execute_one(
            "SELECT r.id AS revision_id,r.document_id,r.content_hash,r.title,r.body_text,"
            "a.source_id,a.svn_revision,a.question_text,a.conditions_json,a.visibility_scope_json,"
            "x.claims_json,x.coverage_json,x.unknowns_json,p.repository_uuid,p.branch_path "
            f"FROM {self.t('document_revision')} r JOIN {self.t('code_answer')} a ON a.document_id=r.document_id "
            f"JOIN {self.t('code_answer_revision')} x ON x.revision_id=r.id "
            f"JOIN {self.t('code_repository')} p ON p.source_id=a.source_id WHERE r.id=? AND r.document_id=?",
            (owned["revision_id"], owned["document_id"]),
        )
        if row is None:
            raise CodeKnowledgeError("CODE_ANSWER_UNAVAILABLE")
        row["repository_uuid"] = str(row["repository_uuid"])
        return {k: json_value(v) if k.endswith("_json") else v for k, v in row.items()}

    def progress(self, owned: dict[str, Any], *, step: str, expected: int, completed: int) -> None:
        with self.db.unit_of_work():
            self._document_lock(owned["document_id"])
            row, _ = self.active(owned)
            self.db.execute(
                f"UPDATE {self.t('code_index_task')} SET step=?,expected_chunks=?,completed_chunks=? WHERE id=?",
                (step, expected, completed, row["id"]),
            )

    def finish(self, owned: dict[str, Any]) -> None:
        with self.db.unit_of_work():
            self._document_lock(owned["document_id"])
            row, _ = self.active(owned)
            if row["action"] == "upsert" and (
                row["step"] != "exposed"
                or not row["expected_chunks"]
                or row["expected_chunks"] != row["completed_chunks"]
            ):
                raise CodeKnowledgeError("CODE_INDEX_INCOMPLETE")
            stamp = timestamp(database_now(self.db))
            self.db.execute(
                f"UPDATE {self.t('code_index_task')} SET state='succeeded',step='done',ready_at=?,"
                "lease_until=NULL,finished_at=?,updated_at=? WHERE id=?",
                (stamp if row["action"] == "upsert" else None, stamp, stamp, row["id"]),
            )

    def stopped(self, owned: dict[str, Any], code: str) -> None:
        """Only the executor calls this after synchronous I/O has returned; no lease takeover."""
        with self.db.unit_of_work():
            self._document_lock(owned["document_id"])
            row = self.row("code_index_task", owned["id"], lock=True)
            if row["state"] != "running" or any(
                row[k] != owned[k] for k in ("claim_version", "owner_instance_id")
            ):
                return
            if code in {"CODE_INDEX_INTENT_CHANGED", "CODE_INDEX_CONFIGURATION_CHANGED"}:
                self._cancel(row, code)
                return
            stamp = database_now(self.db)
            next_attempt = (
                timestamp(stamp + timedelta(seconds=min(300, 2 ** row["attempt_count"])))
                if row["attempt_count"] < 8
                else None
            )
            self.db.execute(
                f"UPDATE {self.t('code_index_task')} SET state='failed',error_code=?,ready_at=NULL,"
                "lease_until=NULL,next_attempt_at=?,finished_at=?,updated_at=? WHERE id=?",
                (code, next_attempt, timestamp(stamp), timestamp(stamp), row["id"]),
            )
