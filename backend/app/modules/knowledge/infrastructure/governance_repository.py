"""知识治理 SQL 仓储；不执行外部请求。"""

from dataclasses import asdict
from contextlib import AbstractContextManager, contextmanager
from collections.abc import Iterator
from typing import Any
import sqlite3
from psycopg import IntegrityError as PostgresIntegrityError
from app.modules.knowledge.domain.governance import (
    KnowledgeGovernanceError,
    SourceItem,
    checked_identifier,
    checked_hash,
)
from app.modules.knowledge.domain.vector_contract import fingerprint
from app.modules.knowledge.infrastructure.storage import table, insert, source_lock
from app.modules.knowledge.domain.identity import now
from app.shared.database import Database


class GovernanceStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    def t(self, name: str) -> str:
        return table(self.database, name)

    @contextmanager
    def unit_of_work(self) -> Iterator[None]:
        try:
            with self.database.unit_of_work():
                yield
        except (sqlite3.IntegrityError, PostgresIntegrityError):
            raise KnowledgeGovernanceError("knowledge_resource_conflict") from None

    def source_lock(self, source_id: str) -> AbstractContextManager[None]:
        return source_lock(self.database, source_id)

    def add(self, name: str, values: dict[str, Any]) -> None:
        insert(self.database, name, values)

    def latest_source_revision(self, source_id: str) -> int:
        row = self.database.execute_one(
            f"select max(revision) as revision from {self.t('source_binding')} where source_id=?",
            (source_id,),
        )
        return int((row or {}).get("revision") or 0)

    def revoke_source_bindings(self, source_id: str, actor_id: str, timestamp: str) -> None:
        self.database.execute(
            f"update {self.t('source_binding')} set state='REVOKED',revoked_by=?,revoked_at=? "
            "where source_id=? and state<>'REVOKED'",
            (actor_id, timestamp, source_id),
        )

    def verify_binding(
        self, binding_id: str, digest: str, count: int, actor_id: str, job_id: str
    ) -> None:
        self.database.execute(
            f"update {self.t('source_binding')} set state='VERIFIED',verification_hash=?,"
            "checked_count=?,verified_by=?,verified_at=?,verified_job_id=? where id=?",
            (digest, count, actor_id, now(), job_id, binding_id),
        )

    def revoke_binding(self, binding_id: str, actor_id: str) -> None:
        self.database.execute(
            f"update {self.t('source_binding')} set state='REVOKED',revoked_by=?,revoked_at=? where id=?",
            (actor_id, now(), binding_id),
        )

    def members(self, base_id: str) -> list[dict[str, Any]]:
        return self.database.execute(
            f"select d.id,d.source_id from {self.t('knowledge_base_document')} m "
            f"join {self.t('document')} d on d.id=m.document_id "
            "where m.knowledge_base_id=? and m.state='included' and d.lifecycle_state='active'",
            (base_id,),
        )

    def enabled_resources(self, base_id: str, *, excluding: str = "") -> list[dict[str, Any]]:
        return self.database.execute(
            f"select * from {self.t('retrieval_resource')} "
            "where knowledge_base_id=? and status='enabled' and id<>?",
            (base_id, excluding),
        )

    def next_resource_revision(self, resource_id: str) -> int:
        row = self.database.execute_one(
            f"select max(revision) as n from {self.t('retrieval_revision')} where resource_id=?",
            (resource_id,),
        )
        return int((row or {}).get("n") or 0) + 1

    def save_draft(self, resource_id: str, revision_id: str) -> None:
        self.database.execute(
            f"update {self.t('retrieval_resource')} set draft_revision_id=?,revision=revision+1,updated_at=? where id=?",
            (revision_id, now(), resource_id),
        )

    def bump_resource_revision(self, resource_id: str) -> None:
        self.database.execute(
            f"update {self.t('retrieval_resource')} set revision=revision+1,updated_at=? where id=?",
            (now(), resource_id),
        )

    def verification(self, revision_id: str) -> dict[str, Any] | None:
        return self.database.execute_one(
            f"select * from {self.t('retrieval_verification')} where revision_id=? order by resource_revision desc limit 1",
            (revision_id,),
        )

    def publish(self, resource_id: str, revision_id: str, actor_id: str) -> None:
        self.database.execute(
            f"update {self.t('retrieval_revision')} set published_by=?,published_at=? where id=? and published_at is null",
            (actor_id, now(), revision_id),
        )
        self.database.execute(
            f"update {self.t('retrieval_resource')} set published_revision_id=?,draft_revision_id=null,"
            "revision=revision+1,updated_at=? where id=?",
            (revision_id, now(), resource_id),
        )

    def set_resource_status(self, resource_id: str, status: str) -> None:
        self.database.execute(
            f"update {self.t('retrieval_resource')} set status=?,revision=revision+1,"
            "state_revision=state_revision+1,updated_at=? where id=?",
            (status, now(), resource_id),
        )

    def current_documents(self, source_id: str, ids: tuple[str, ...]) -> dict[str, Any]:
        rows = self.database.execute(
            f"select d.id,d.external_id,d.current_revision_id,r.source_project_id "
            f"from {self.t('document')} d join {self.t('document_revision')} r "
            "on r.id=d.current_revision_id and r.document_id=d.id "
            f"where d.source_id=? and d.id in ({','.join('?' for _ in ids)})",
            (source_id, *ids),
        )
        result = {row["id"]: row for row in rows}
        if set(result) != set(ids):
            raise KnowledgeGovernanceError("knowledge_candidate_invalid")
        return result

    def source_catalog(self) -> dict[str, Any]:
        return {
            "sources": self.database.execute(
                f"select id,code,display_name,source_system,origin_state from {self.t('source')} order by id"
            ),
            "bindings": self.database.execute(
                f"select * from {self.t('source_binding')} order by source_id,revision"
            ),
        }

    def catalog(self) -> dict[str, Any]:
        return {
            "bases": self.database.execute(
                f"select id,code,display_name,state from {self.t('knowledge_base')} order by id"
            ),
            "indexes": self.database.execute(
                f"select id,code,knowledge_base_id,state,profile_hash,corpus_hash from {self.t('vector_index')} order by id"
            ),
        }

    def resource_ids(self) -> list[str]:
        return [
            row["id"]
            for row in self.database.execute(
                f"select id from {self.t('retrieval_resource')} order by id"
            )
        ]

    def get(self, name: str, identifier: str, *, lock: bool = False) -> dict[str, Any]:
        suffix = " for update" if lock and self.database.engine == "postgres" else ""
        row = self.database.execute_one(
            f"select * from {self.t(name)} where id=?{suffix}", (identifier,)
        )
        if not row:
            raise KnowledgeGovernanceError("knowledge_resource_unavailable")
        return row

    def source_items(self, source_id: str) -> tuple[SourceItem, ...]:
        source = self.get("source", source_id)
        if source["source_system"] != "ones" or source["origin_state"] != "offline_unverified":
            raise KnowledgeGovernanceError("knowledge_source_unavailable")
        rows = self.database.execute(
            f"select d.id,d.current_revision_id,d.external_id,d.source_object_type,"
            f"r.source_project_id,r.content_hash from {self.t('document')} d "
            f"left join {self.t('document_revision')} r on r.id=d.current_revision_id and r.document_id=d.id "
            "where d.source_id=? and d.lifecycle_state='active' order by d.id limit 200001",
            (source_id,),
        )
        if (
            not rows
            or len(rows) > 200_000
            or any(
                r["source_object_type"] != "ones_work_item" or r["content_hash"] is None
                for r in rows
            )
        ):
            raise KnowledgeGovernanceError("knowledge_source_unavailable")
        return tuple(
            SourceItem(
                str(r["id"]),
                str(r["current_revision_id"]),
                checked_identifier(r["external_id"]),
                checked_identifier(r["source_project_id"]),
                checked_hash(r["content_hash"]),
            )
            for r in rows
        )

    @staticmethod
    def source_hash(items: tuple[SourceItem, ...]) -> str:
        return fingerprint([asdict(item) for item in items])

    def assert_current_source(
        self,
        binding: dict[str, Any],
        *,
        instance_code: str,
        target_hash: str,
        verified: bool = True,
    ) -> tuple[SourceItem, ...]:
        if binding["instance_code"] != checked_identifier(instance_code) or binding[
            "target_hash"
        ] != checked_hash(target_hash):
            raise KnowledgeGovernanceError("knowledge_source_changed")
        if binding["state"] != ("VERIFIED" if verified else "PENDING"):
            raise KnowledgeGovernanceError("knowledge_source_unavailable")
        items = self.source_items(binding["source_id"])
        if (
            len(items) != binding["document_count"]
            or self.source_hash(items) != binding["corpus_hash"]
        ):
            raise KnowledgeGovernanceError("knowledge_source_changed")
        return items
