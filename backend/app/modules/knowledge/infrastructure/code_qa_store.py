"""Private final-answer history. Call only with host-normalized business content."""

from typing import Any

from app.modules.agent.infrastructure.runtime_pool_store import database_now, timestamp
from app.modules.knowledge.domain.code_answers import (
    bounded_json,
    normalized_question,
    svn_revision,
)
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.identity import stable_id
from app.modules.knowledge.domain.normalization import canonical_json, digest
from app.modules.knowledge.infrastructure.code_checkout_store import CodeCheckoutStore, json_value


class CodeQaStore(CodeCheckoutStore):
    def record(
        self,
        *,
        job_id: str,
        result_revision: int,
        base_id: str,
        actor_id: str,
        source_id: str,
        requested_revisions: list[int],
        question: str,
        answer: str,
        support_status: str,
        answer_origin: str,
        references: list[dict[str, Any]],
    ) -> str:
        """Idempotent finalization, including cache hits; never queues indexing."""
        question = normalized_question(question)
        if (
            type(result_revision) is not int
            or result_revision < 1
            or not isinstance(answer, str)
            or not 1 <= len(answer.strip()) <= 64000
            or support_status not in {"supported", "partial", "conflicted", "unverified"}
            or answer_origin not in {"cache", "code_analysis", "mixed", "unresolved"}
            or not isinstance(requested_revisions, list)
            or not 1 <= len(requested_revisions) <= 2
        ):
            raise CodeKnowledgeError("CODE_QA_INVALID")
        revisions = [svn_revision(n) for n in requested_revisions]
        if len(set(revisions)) != len(revisions):
            raise CodeKnowledgeError("CODE_QA_INVALID")
        bounded_json(references, expected=list)
        if len(references) > 100:
            raise CodeKnowledgeError("CODE_QA_INVALID")
        identifier = stable_id("code-qa", job_id, str(result_revision), base_id)
        values = dict(
            job_id=job_id,
            result_revision=result_revision,
            knowledge_base_id=base_id,
            actor_id=actor_id,
            source_id=source_id,
            requested_revisions=revisions,
            question_text=question,
            answer_text=answer,
            support_status=support_status,
            answer_origin=answer_origin,
            references_json=references,
        )
        answer_hash = digest(values)
        with self.db.unit_of_work():
            job = self.db.execute_one("SELECT requester_id FROM agent_job WHERE id=?", (job_id,))
            if not job or job["requester_id"] != actor_id:
                raise CodeKnowledgeError("CODE_QA_OWNER_MISMATCH")
            self._references(source_id, revisions, support_status, references)
            parameters = [
                revisions
                if k == "requested_revisions" and self.db.engine == "postgres"
                else canonical_json(v)
                if isinstance(v, (list, dict))
                else v
                for k, v in values.items()
            ]
            self.db.execute(
                f"INSERT INTO {self.t('code_qa_record')} (id,{','.join(values)},answer_hash,created_at) VALUES ({','.join('?' for _ in range(len(values) + 3))}) ON CONFLICT(job_id,result_revision,knowledge_base_id) DO NOTHING",
                (identifier, *parameters, answer_hash, timestamp(database_now(self.db))),
            )
            previous = self.db.execute_one(
                f"SELECT answer_hash FROM {self.t('code_qa_record')} WHERE id=?", (identifier,)
            )
            if not previous or previous["answer_hash"] != answer_hash:
                raise CodeKnowledgeError("CODE_QA_REPLAY_CONFLICT")
        return identifier

    def _references(
        self, source: str, requested: list[int], status: str, references: list[dict[str, Any]]
    ) -> None:
        for ref in references:
            if (
                not isinstance(ref, dict)
                or set(ref) != {"document_id", "revision_id", "svn_revision", "version_mode"}
                or ref["version_mode"] not in {"exact", "next_higher_hint"}
            ):
                raise CodeKnowledgeError("CODE_QA_REFERENCE_INVALID")
            row = self.db.execute_one(
                f"SELECT a.source_id,a.svn_revision FROM {self.t('code_answer')} a JOIN {self.t('code_answer_revision')} r ON r.document_id=a.document_id WHERE a.document_id=? AND r.revision_id=?",
                (ref["document_id"], ref["revision_id"]),
            )
            if (
                not row
                or row["source_id"] != source
                or row["svn_revision"] != svn_revision(ref["svn_revision"])
            ):
                raise CodeKnowledgeError("CODE_QA_REFERENCE_INVALID")
            if ref["version_mode"] == "exact" and row["svn_revision"] not in requested:
                raise CodeKnowledgeError("CODE_QA_VERSION_MISMATCH")
            if ref["version_mode"] == "next_higher_hint" and row["svn_revision"] <= min(requested):
                raise CodeKnowledgeError("CODE_QA_VERSION_MISMATCH")
        if status == "supported" and set(requested) != {
            r["svn_revision"] for r in references if r["version_mode"] == "exact"
        }:
            raise CodeKnowledgeError("CODE_QA_TARGET_EVIDENCE_REQUIRED")

    def for_job(self, job_id: str, actor_id: str) -> list[dict[str, Any]]:
        """Never exposes private histories across actors or through knowledge search."""
        rows = self.db.execute(
            f"SELECT * FROM {self.t('code_qa_record')} WHERE job_id=? AND actor_id=? ORDER BY result_revision,id",
            (job_id, actor_id),
        )
        return [
            {
                **row,
                "requested_revisions": json_value(row["requested_revisions"]),
                "references_json": json_value(row["references_json"]),
            }
            for row in rows
        ]
