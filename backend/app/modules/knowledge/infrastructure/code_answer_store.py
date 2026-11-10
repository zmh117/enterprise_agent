"""Versioned code answers and durable index work; this store never calls a model or Qdrant."""

from typing import Any

from app.modules.agent.infrastructure.runtime_pool_store import database_now, timestamp
from app.modules.knowledge.domain.code_answers import (
    CODE_ANSWER_CONTRACT,
    CodeAnalysisContext,
    answer_identity,
    bounded_json,
    normalized_question,
    path_in_scope,
    utc_time,
)
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.identity import stable_id
from app.modules.knowledge.domain.normalization import canonical_json, digest
from app.modules.knowledge.infrastructure.code_analysis_store import CodeAnalysisStore
from app.modules.knowledge.infrastructure.code_checkout_store import json_value
from app.modules.knowledge.infrastructure.storage import insert


class CodeAnswerStore(CodeAnalysisStore):
    def finalizing(self, context: CodeAnalysisContext, analysis_id: str) -> dict[str, Any]:
        """Only the authenticated Runtime calls this after draining its file reads."""
        with self.db.unit_of_work():
            self._owner(context)
            self._configuration(context)
            self.row("code_checkout", context.checkout_id, lock=True)
            analysis = self.row("code_analysis", analysis_id, lock=True)
            self._bound(context, analysis)
            if (
                analysis["state"] in {"validating", "completed", "partial", "conflicted"}
                and analysis["reads_quiesced_at"] is not None
            ):
                return analysis
            analysis = self.require_reader(context, analysis_id)
            active = self.db.execute_one(
                f"SELECT id FROM {self.t('code_svn_operation')} WHERE analysis_id=? AND state IN ('queued','running') LIMIT 1",
                (analysis_id,),
            )
            if active:
                return {**analysis, "state": "draining"}
            stamp = timestamp(database_now(self.db))
            self.db.execute(
                f"UPDATE {self.t('code_analysis')} SET state='validating',read_revoked_at=?,reads_quiesced_at=?,updated_at=? WHERE id=?",
                (stamp, stamp, stamp, analysis_id),
            )
            return self.row("code_analysis", analysis["id"])

    def save(
        self,
        context: CodeAnalysisContext,
        analysis_id: str,
        *,
        question: str,
        visibility_scope: dict[str, Any],
        result: dict[str, Any],
        request_key: str,
    ) -> dict[str, Any]:
        question = normalized_question(question)
        if digest(question) != context.question_hash:
            raise CodeKnowledgeError("CODE_QUESTION_MISMATCH")
        self._result(result)
        request_hash = digest([request_key, question, visibility_scope, result])
        with self.db.unit_of_work():
            self._owner(context)
            self._configuration(context)
            checkout = self.row("code_checkout", context.checkout_id, lock=True)
            analysis = self.row("code_analysis", analysis_id, lock=True)
            self._bound(context, analysis)
            if analysis["save_request_hash"] is not None:
                if analysis["save_request_hash"] != request_hash:
                    raise CodeKnowledgeError("CODE_IDEMPOTENCY_CONFLICT")
                return self._saved(analysis)
            self._saving(context, analysis, checkout)
            supported = result["support_status"] == "supported"
            evidence = self._evidence(analysis, result, visibility_scope) if supported else {}
            revision_id = (
                self._persist(context, analysis, question, visibility_scope, result, evidence)
                if supported
                else None
            )
            stamp = timestamp(database_now(self.db))
            self.db.execute(
                f"UPDATE {self.t('code_analysis')} SET state=?,saved_revision_id=?,save_request_hash=?,report_json=?,read_released_at=?,closed_at=?,updated_at=? WHERE id=?",
                (
                    "completed" if supported else result["support_status"],
                    revision_id,
                    request_hash,
                    canonical_json(
                        {
                            "coverage": result["coverage"],
                            "unknowns": result["unknowns"],
                            "answer": result["answer"],
                        }
                    ),
                    stamp,
                    stamp,
                    stamp,
                    analysis_id,
                ),
            )
            return self._saved(self.row("code_analysis", analysis_id))

    @staticmethod
    def _result(result: dict[str, Any]) -> None:
        bounded_json(result, expected=dict, limit=128 * 1024)
        required = {
            "title",
            "answer",
            "conditions",
            "claims",
            "coverage",
            "unknowns",
            "support_status",
        }
        if not required <= set(result) or set(result) - required - {
            "document_id",
            "expected_current_revision_id",
        }:
            raise CodeKnowledgeError("CODE_ANSWER_INVALID")
        if result["support_status"] not in {"supported", "partial", "conflicted"}:
            raise CodeKnowledgeError("CODE_ANSWER_INVALID")
        for key, limit in (("title", 2000), ("answer", 64000)):
            if not isinstance(result[key], str) or not 1 <= len(result[key].strip()) <= limit:
                raise CodeKnowledgeError("CODE_ANSWER_INVALID")
        for key, kind in (
            ("conditions", dict),
            ("claims", list),
            ("coverage", dict),
            ("unknowns", list),
        ):
            bounded_json(result[key], expected=kind)
        if len(result["claims"]) > 100 or len(result["unknowns"]) > 100:
            raise CodeKnowledgeError("CODE_ANSWER_INVALID")
        if result["support_status"] == "supported" and (
            not result["claims"]
            or any(not isinstance(v, dict) or v.get("critical", True) for v in result["unknowns"])
        ):
            raise CodeKnowledgeError("CODE_CRITICAL_DEPENDENCY_UNKNOWN")

    def _saving(
        self, context: CodeAnalysisContext, analysis: dict[str, Any], checkout: dict[str, Any]
    ) -> None:
        if (
            analysis["state"] != "validating"
            or analysis["reads_quiesced_at"] is None
            or analysis["read_released_at"] is not None
            or analysis["lease_until"] is None
            or utc_time(analysis["lease_until"]) <= database_now(self.db)
            or checkout["state"] != "ready"
            or checkout["writer_operation_id"] is not None
            or checkout["generation"] != analysis["generation"]
            or checkout["verified_revision"] != context.revision
        ):
            raise CodeKnowledgeError("CODE_SAVE_GRANT_INVALID")

    def _evidence(
        self, analysis: dict[str, Any], result: dict[str, Any], scope: dict[str, Any]
    ) -> dict[str, Any]:
        rows = self.db.execute(
            f"SELECT * FROM {self.t('code_evidence')} WHERE analysis_id=? AND validated_at IS NOT NULL",
            (analysis["id"],),
        )
        evidence = {row["id"]: row for row in rows}
        used = set()
        claim_ids = set()
        paths = scope.get("paths")
        if not isinstance(paths, list) or not paths or not all(isinstance(p, str) for p in paths):
            raise CodeKnowledgeError("CODE_SCOPE_INVALID")
        for claim in result["claims"]:
            if not isinstance(claim, dict) or set(claim) != {
                "claim_id",
                "conclusion",
                "conditions",
                "evidence_ids",
            }:
                raise CodeKnowledgeError("CODE_CLAIM_INVALID")
            if (
                not isinstance(claim["claim_id"], str)
                or not claim["claim_id"]
                or claim["claim_id"] in claim_ids
                or not isinstance(claim["conclusion"], str)
                or not claim["conclusion"].strip()
                or len(claim["conclusion"]) > 16000
                or not isinstance(claim["conditions"], dict)
            ):
                raise CodeKnowledgeError("CODE_CLAIM_INVALID")
            claim_ids.add(claim["claim_id"])
            refs = claim["evidence_ids"]
            if (
                not isinstance(refs, list)
                or not refs
                or not all(isinstance(e, str) and e in evidence for e in refs)
                or len(set(refs)) != len(refs)
            ):
                raise CodeKnowledgeError("CODE_EVIDENCE_UNVERIFIED")
            if not any(evidence[e]["kind"] == "file_read" for e in refs):
                raise CodeKnowledgeError("CODE_FILE_EVIDENCE_REQUIRED")
            used.update(refs)
        for identifier in used:
            item = evidence[identifier]
            if item["kind"] == "file_read" and (
                item["svn_revision"] != analysis["requested_revision"]
                or not path_in_scope(item["relative_path"], paths)
            ):
                raise CodeKnowledgeError("CODE_EVIDENCE_SCOPE_MISMATCH")
        return {identifier: evidence[identifier] for identifier in used}

    def _persist(
        self,
        context: CodeAnalysisContext,
        analysis: dict[str, Any],
        question: str,
        scope: dict[str, Any],
        result: dict[str, Any],
        evidence: dict[str, Any],
    ) -> str:
        identity = answer_identity(question, result["conditions"], scope, context.environment_id)
        document_id = stable_id(
            "code-answer", context.source_id, str(context.revision), identity["identity_hash"]
        )
        if result.get("document_id", document_id) != document_id:
            raise CodeKnowledgeError("CODE_ANSWER_IDENTITY_MISMATCH")
        stamp = timestamp(database_now(self.db))
        insert(
            self.db,
            "document",
            dict(
                id=document_id,
                source_id=context.source_id,
                source_object_type="code_answer",
                external_id=f"{context.revision}:{identity['identity_hash']}",
                external_number=f"r{context.revision}",
                document_kind="code_answer",
                lifecycle_state="pending",
                created_at=stamp,
                last_seen_at=stamp,
            ),
            conflict="ON CONFLICT(id) DO NOTHING",
        )
        suffix = " FOR UPDATE" if self.db.engine == "postgres" else ""
        document = self.db.execute_one(
            f"SELECT * FROM {self.t('document')} WHERE id=?{suffix}", (document_id,)
        )
        assert document is not None
        insert(
            self.db,
            "code_answer",
            dict(
                document_id=document_id,
                source_id=context.source_id,
                svn_revision=context.revision,
                created_at=stamp,
                **identity,
            ),
            conflict="ON CONFLICT(document_id) DO NOTHING",
        )
        saved_identity = self.db.execute_one(
            f"SELECT * FROM {self.t('code_answer')} WHERE document_id=?", (document_id,)
        )
        assert saved_identity is not None
        if (
            saved_identity["source_id"] != context.source_id
            or saved_identity["svn_revision"] != context.revision
            or any(
                json_value(saved_identity[k]) != v
                if k.endswith("_json")
                else saved_identity[k] != v
                for k, v in identity.items()
            )
        ):
            raise CodeKnowledgeError("CODE_ANSWER_IDENTITY_MISMATCH")
        claims = [
            {
                **claim,
                "evidence_ids": sorted(evidence[e]["evidence_hash"] for e in claim["evidence_ids"]),
            }
            for claim in result["claims"]
        ]
        content_hash = digest(
            [
                result["title"],
                result["answer"],
                identity,
                claims,
                result["coverage"],
                result["unknowns"],
            ]
        )
        previous = self.db.execute_one(
            f"SELECT id,content_hash,revision_no FROM {self.t('document_revision')} WHERE id=?",
            (document["current_revision_id"],),
        )
        if (
            previous
            and previous["content_hash"] == content_hash
            and document["lifecycle_state"] == "active"
        ):
            self._include(context.knowledge_base_id, document_id, previous["id"], stamp)
            return str(previous["id"])
        if previous and result.get("expected_current_revision_id") != previous["id"]:
            raise CodeKnowledgeError("CODE_ANSWER_REVISION_CONFLICT")
        revision_id = self._new_revision(
            context,
            analysis,
            document_id,
            result,
            content_hash,
            stamp,
            (previous["revision_no"] + 1) if previous else 1,
        )
        self.db.execute(
            f"UPDATE {self.t('document')} SET current_revision_id=?,lifecycle_state='active',last_seen_at=? WHERE id=?",
            (revision_id, stamp, document_id),
        )
        self._include(context.knowledge_base_id, document_id, revision_id, stamp)
        if previous:
            self._enqueue_members(document_id, previous["id"], "remove", stamp)
        self._enqueue_members(document_id, revision_id, "upsert", stamp)
        return revision_id

    def _new_revision(
        self,
        context: CodeAnalysisContext,
        analysis: dict[str, Any],
        document_id: str,
        result: dict[str, Any],
        content_hash: str,
        stamp: str,
        number: int,
    ) -> str:
        revision_id = stable_id("code-answer-revision", analysis["id"])
        insert(
            self.db,
            "document_revision",
            dict(
                id=revision_id,
                document_id=document_id,
                revision_no=number,
                import_run_id=None,
                origin_kind="code_analysis",
                code_analysis_id=analysis["id"],
                title=result["title"],
                body_text=result["answer"],
                source_project_id=None,
                source_project_name=None,
                source_snapshot={
                    "source_id": context.source_id,
                    "svn_revision": context.revision,
                    "analysis_id": analysis["id"],
                },
                attributes={},
                completeness={"support_status": "supported"},
                normalizer_version=CODE_ANSWER_CONTRACT,
                content_hash=content_hash,
                ingested_at=stamp,
            ),
        )
        insert(
            self.db,
            "code_answer_revision",
            dict(
                revision_id=revision_id,
                document_id=document_id,
                claims_json=result["claims"],
                coverage_json=result["coverage"],
                unknowns_json=result["unknowns"],
                validation_version=CODE_ANSWER_CONTRACT,
                validated_at=stamp,
            ),
        )
        return revision_id

    def _include(self, base_id: str, document_id: str, revision_id: str, stamp: str) -> None:
        previous = self.db.execute_one(
            f"SELECT state FROM {self.t('knowledge_base_document')} WHERE knowledge_base_id=? AND document_id=?",
            (base_id, document_id),
        )
        insert(
            self.db,
            "knowledge_base_document",
            dict(
                knowledge_base_id=base_id,
                document_id=document_id,
                state="included",
                created_at=stamp,
            ),
            conflict="ON CONFLICT(knowledge_base_id,document_id) DO UPDATE SET state='included'",
        )
        self._enqueue_members(
            document_id,
            revision_id,
            "upsert",
            stamp,
            base_id=base_id,
            restart=bool(previous and previous["state"] != "included"),
        )

    def _enqueue_members(
        self,
        document_id: str,
        revision_id: str,
        action: str,
        stamp: str,
        *,
        base_id: str | None = None,
        restart: bool = False,
    ) -> None:
        args = [document_id]
        suffix = ""
        if base_id is not None:
            suffix = " AND m.knowledge_base_id=?"
            args.append(base_id)
        indexes = self.db.execute(
            f"SELECT i.* FROM {self.t('vector_index')} i JOIN {self.t('knowledge_base_document')} m ON m.knowledge_base_id=i.knowledge_base_id WHERE m.document_id=? AND m.state='included' AND i.incremental=1 AND i.state='READY'"
            + suffix,
            tuple(args),
        )
        from app.modules.knowledge.infrastructure.code_index_store import CodeIndexStore

        tasks = CodeIndexStore(self.db)
        for index in indexes:
            tasks.enqueue(
                index,
                document_id,
                revision_id,
                action,
                restart=restart or action == "remove",
            )

    def _saved(self, analysis: dict[str, Any]) -> dict[str, Any]:
        index_state = "not_applicable"
        document_id = None
        if analysis["saved_revision_id"]:
            revision = self.db.execute_one(
                f"SELECT document_id FROM {self.t('code_answer_revision')} WHERE revision_id=?",
                (analysis["saved_revision_id"],),
            )
            document_id = revision["document_id"] if revision else None
            task = self.db.execute_one(
                f"SELECT t.state FROM {self.t('code_index_task')} t "
                f"JOIN {self.t('retrieval_revision')} r ON r.index_id=t.index_id "
                "WHERE r.id=? AND t.revision_id=? AND t.action='upsert'",
                (analysis["config_revision_id"], analysis["saved_revision_id"]),
            )
            index_state = "ready" if task and task["state"] == "succeeded" else "pending"
        return {
            "analysis_id": analysis["id"],
            "document_id": document_id,
            "revision_id": analysis["saved_revision_id"],
            "svn_revision": analysis["requested_revision"],
            "support_status": "supported"
            if analysis["state"] == "completed"
            else analysis["state"],
            "saved": True,
            "index_state": index_state,
        }
