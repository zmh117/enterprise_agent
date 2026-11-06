"""Explicit retirement of one unindexed v1 source's candidates; preserve source and Job audit."""

from typing import Any

from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.identity import now
from app.modules.knowledge.domain.normalization import canonical_json, digest
from app.modules.knowledge.infrastructure.code_repository import CodeRepository, decoded
from app.modules.knowledge.infrastructure.storage import source_lock, table
from app.shared.database import Database


class CodeCandidateRetirement:
    def __init__(self, database: Database) -> None:
        self.db = database

    def retire(self, source_id: str, *, expected_digest: str | None = None) -> dict[str, Any]:
        with source_lock(self.db, source_id), self.db.unit_of_work():
            binding = CodeRepository(self.db).binding(source_id)
            snapshots = self.db.execute(
                f"select id,state from {table(self.db, 'code_snapshot')} where source_id=? order by id",
                (source_id,),
            )
            builds = self.db.execute(
                f"select id,stage,active,configuration_json from {table(self.db, 'code_build')} where source_id=? order by id",
                (source_id,),
            )
            live = self.db.execute_one(
                f"select i.invocation_id from agent_runtime_invocation i join {table(self.db, 'code_unit')} u on u.job_id=i.job_id "
                f"join {table(self.db, 'code_build')} b on b.id=u.build_id where b.source_id=? "
                "and i.state<>'PREPARED' and i.execution_quiesced_at is null limit 1",
                (source_id,),
            )
            pending = self.db.execute_one(
                f"select j.id from agent_job j join {table(self.db, 'code_unit')} u on u.job_id=j.id "
                f"join {table(self.db, 'code_build')} b on b.id=u.build_id where b.source_id=? "
                "and j.status not in ('SUCCEEDED','FAILED','CANCELLED','DEAD_LETTER') limit 1",
                (source_id,),
            )
            index = self.db.execute_one(
                f"select id from {table(self.db, 'vector_index')} where knowledge_base_id=? limit 1",
                (binding["knowledge_base_id"],),
            )
            if (
                binding["active_snapshot_id"]
                or live
                or pending
                or index
                or any(s["state"] != "CANDIDATE" for s in snapshots)
                or any(
                    b["active"] or b["stage"] not in {"FAILED", "INTERRUPTED", "CANCELLED"}
                    for b in builds
                )
            ):
                raise CodeKnowledgeError("code_candidate_retirement_in_use")
            revisions = self.db.execute(
                f"select r.id,r.document_id,r.content_hash,r.attributes from {table(self.db, 'document_revision')} r "
                f"join {table(self.db, 'document')} d on d.id=r.document_id where d.source_id=? order by r.id",
                (source_id,),
            )
            documents = self.db.execute(
                f"select id,source_object_type,current_revision_id from {table(self.db, 'document')} where source_id=? order by id",
                (source_id,),
            )
            if (
                any(
                    decoded(r["attributes"]).get("contract_version") != "code-business/v1"
                    for r in revisions
                )
                or any(
                    d["source_object_type"] != "code_business" or d["current_revision_id"]
                    for d in documents
                )
                or any(
                    decoded(b["configuration_json"]).get("contract_version") != "code-business/v1"
                    for b in builds
                )
            ):
                raise CodeKnowledgeError("code_candidate_retirement_scope_invalid")
            manifest = dict(
                source_id=source_id,
                knowledge_base_id=binding["knowledge_base_id"],
                snapshots=[s["id"] for s in snapshots],
                builds=[b["id"] for b in builds],
                documents=[d["id"] for d in documents],
                revisions=[
                    {k: r[k] for k in ("id", "document_id", "content_hash")} for r in revisions
                ],
            )
            fingerprint = digest(manifest)
            if expected_digest is not None:
                if expected_digest != fingerprint:
                    raise CodeKnowledgeError("code_candidate_retirement_changed")
                for snapshot in snapshots:
                    self.db.execute(
                        f"delete from {table(self.db, 'code_relation')} where snapshot_id=?",
                        (snapshot["id"],),
                    )
                    self.db.execute(
                        f"delete from {table(self.db, 'code_member')} where snapshot_id=?",
                        (snapshot["id"],),
                    )
                    self.db.execute(
                        f"update {table(self.db, 'code_snapshot')} set state='UNAVAILABLE',validation_json=? where id=?",
                        (
                            canonical_json(
                                dict(
                                    retired_contract="code-business/v1",
                                    retirement_digest=fingerprint,
                                )
                            ),
                            snapshot["id"],
                        ),
                    )
                for revision in revisions:
                    self.db.execute(
                        f"delete from {table(self.db, 'code_dependency')} where revision_id=?",
                        (revision["id"],),
                    )
                    self.db.execute(
                        f"delete from {table(self.db, 'document_revision')} where id=?",
                        (revision["id"],),
                    )
                for document in documents:
                    self.db.execute(
                        f"delete from {table(self.db, 'knowledge_base_document')} where document_id=? and knowledge_base_id=?",
                        (document["id"], binding["knowledge_base_id"]),
                    )
                    self.db.execute(
                        f"delete from {table(self.db, 'document')} where id=? and source_id=?",
                        (document["id"], source_id),
                    )
                for build in builds:
                    self.db.execute(
                        f"update {table(self.db, 'code_unit')} set state='CANCELLED',updated_at=? where build_id=? and state in ('QUEUED','RUNNING','SUBMITTED','UNKNOWN')",
                        (now(), build["id"]),
                    )
            return dict(
                state="RETIRED" if expected_digest is not None else "ELIGIBLE",
                digest=fingerprint,
                manifest=manifest,
            )
