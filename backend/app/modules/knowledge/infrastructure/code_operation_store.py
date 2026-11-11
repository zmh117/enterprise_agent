"""Persistent SVN operation admission and ownership, distinct from transient responses."""

from datetime import timedelta
from typing import Any

from app.modules.agent.infrastructure.runtime_pool_store import database_now, timestamp
from app.modules.knowledge.domain.code_answers import CodeAnalysisContext, utc_time
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.code_svn_requests import history_request
from app.modules.knowledge.domain.identity import stable_id
from app.modules.knowledge.domain.normalization import canonical_json, digest
from app.modules.knowledge.infrastructure.code_analysis_store import CodeAnalysisStore
from app.modules.knowledge.infrastructure.code_checkout_store import json_value
from app.modules.knowledge.infrastructure.storage import insert


class CodeOperationStore(CodeAnalysisStore):
    def submit_history(
        self,
        context: CodeAnalysisContext,
        analysis_id: str,
        *,
        kind: str,
        request: dict[str, Any],
        request_key: str,
        deadline_at: str | None = None,
    ) -> dict[str, Any]:
        with self.db.unit_of_work():
            analysis = self.require_reader(context, analysis_id)
            config = self.db.execute_one(
                f"SELECT allowed_paths_json FROM {self.t('code_resource_config')} WHERE revision_id=?",
                (context.config_revision_id,),
            )
            assert config is not None
            value = history_request(
                kind,
                request,
                upper=context.revision,
                paths=json_value(config["allowed_paths_json"]),
            )
            key = stable_id("code-history-request", context.job_id, request_key)
            fingerprint = digest([context.fingerprint(), analysis_id, kind, value])
            old = self.db.execute_one(
                f"SELECT * FROM {self.t('code_svn_operation')} WHERE request_key=?", (key,)
            )
            if old:
                if old["request_hash"] != fingerprint:
                    raise CodeKnowledgeError("CODE_IDEMPOTENCY_CONFLICT")
                return old
            active = self.db.execute_one(
                f"SELECT count(*) AS n FROM {self.t('code_svn_operation')} WHERE job_id=? AND state IN ('queued','running')",
                (context.job_id,),
            )
            if active and active["n"] >= 4:
                raise CodeKnowledgeError("CODE_OPERATION_BUSY")
            stamp = timestamp(database_now(self.db))
            identifier = stable_id("code-history-operation", key)
            insert(
                self.db,
                "code_svn_operation",
                dict(
                    id=identifier,
                    source_id=context.source_id,
                    checkout_id=context.checkout_id,
                    analysis_id=analysis_id,
                    job_id=context.job_id,
                    invocation_id=context.invocation_id,
                    actor_id=context.actor_id,
                    config_revision_id=context.config_revision_id,
                    operation_kind=kind,
                    request_key=key,
                    request_hash=fingerprint,
                    state="queued",
                    target_revision=value.get("revision", context.revision),
                    from_revision=value.get("start"),
                    to_revision=value.get("end"),
                    peg_revision=value["peg"],
                    request_json=value,
                    checkout_generation=analysis["generation"],
                    deadline_at=timestamp(
                        min(
                            database_now(self.db) + timedelta(seconds=60),
                            utc_time(context.deadline_at),
                            utc_time(deadline_at or context.deadline_at),
                        )
                    ),
                    created_at=stamp,
                    updated_at=stamp,
                ),
            )
            return self.row("code_svn_operation", identifier)

    def claim(self, operation_id: str, *, owner: str) -> dict[str, Any]:
        # The registered checkout row serializes all claims with analysis admission.
        observed = self.row("code_svn_operation", operation_id)
        with self.db.unit_of_work():
            checkout = self.row("code_checkout", observed["checkout_id"], lock=True)
            operation = self.row("code_svn_operation", operation_id, lock=True)
            current = database_now(self.db)
            if operation["state"] != "queued" or utc_time(operation["deadline_at"]) <= current:
                raise CodeKnowledgeError("CODE_OPERATION_NOT_CLAIMABLE")
            if checkout["generation"] != operation["checkout_generation"]:
                raise CodeKnowledgeError("CODE_CHECKOUT_CHANGED")
            # Never reclaim running work based only on an expired lease.
            self.db.execute(
                f"UPDATE {self.t('code_svn_operation')} SET state='running',owner_instance_id=?,claim_version=claim_version+1,lease_until=?,started_at=?,updated_at=? WHERE id=?",
                (
                    owner,
                    timestamp(
                        min(current + timedelta(seconds=30), utc_time(operation["deadline_at"]))
                    ),
                    timestamp(current),
                    timestamp(current),
                    operation_id,
                ),
            )
            return self.row("code_svn_operation", operation_id)

    def check_claim(self, operation_id: str, *, owner: str, claim: int) -> dict[str, Any]:
        operation = self.row("code_svn_operation", operation_id)
        if (
            operation["state"] != "running"
            or operation["owner_instance_id"] != owner
            or operation["claim_version"] != claim
        ):
            raise CodeKnowledgeError("CODE_OPERATION_LEASE_LOST")
        current = database_now(self.db)
        if utc_time(operation["deadline_at"]) <= current:
            raise CodeKnowledgeError("CODE_OPERATION_EXPIRED")
        if operation["lease_until"] is None or utc_time(operation["lease_until"]) <= current:
            raise CodeKnowledgeError("CODE_OPERATION_LEASE_LOST")
        return operation

    def complete_history(
        self,
        context: CodeAnalysisContext,
        operation_id: str,
        *,
        owner: str,
        claim: int,
        result_hash: str,
        metadata: dict[str, int | bool],
    ) -> dict[str, Any]:
        # Caller has waited for its SVN child to exit and installed the bounded in-memory result.
        if set(metadata) - {"count", "partial", "has_more", "bytes"} or any(
            type(v) not in (int, bool) for v in metadata.values()
        ):
            raise CodeKnowledgeError("CODE_OPERATION_METADATA_INVALID")
        if len(result_hash) != 64 or any(c not in "0123456789abcdef" for c in result_hash):
            raise CodeKnowledgeError("CODE_OPERATION_METADATA_INVALID")
        observed = self.row("code_svn_operation", operation_id)
        with self.db.unit_of_work():
            self.require_reader(context, observed["analysis_id"])
            operation = self.check_claim(operation_id, owner=owner, claim=claim)
            if (
                operation["operation_kind"] not in {"info", "log", "diff", "blame"}
                or operation["job_id"] != context.job_id
            ):
                raise CodeKnowledgeError("CODE_OPERATION_MISMATCH")
            if operation["result_hash"] is not None and operation["result_hash"] != result_hash:
                raise CodeKnowledgeError("CODE_HISTORY_RESULT_CHANGED")
            stamp = timestamp(database_now(self.db))
            self.db.execute(
                f"UPDATE {self.t('code_svn_operation')} SET state='succeeded',result_json=?,result_hash=?,quiesced_at=?,finished_at=?,updated_at=? WHERE id=?",
                (canonical_json(metadata), result_hash, stamp, stamp, stamp, operation_id),
            )
            return self.row("code_svn_operation", operation_id)

    def replay_history(self, context: CodeAnalysisContext, operation_id: str) -> dict[str, Any]:
        observed = self.row("code_svn_operation", operation_id)
        with self.db.unit_of_work():
            self.require_reader(context, observed["analysis_id"])
            operation = self.row("code_svn_operation", operation_id, lock=True)
            if (
                operation["operation_kind"] not in {"info", "log", "diff", "blame"}
                or (
                    operation["operation_kind"] == "info"
                    and not json_value(operation["request_json"]).get("target")
                )
                or operation["job_id"] != context.job_id
                or operation["result_hash"] is None
                or utc_time(operation["deadline_at"]) <= database_now(self.db)
            ):
                raise CodeKnowledgeError("CODE_OPERATION_REPLAY_DENIED")
            if operation["state"] == "succeeded":
                self.db.execute(
                    f"UPDATE {self.t('code_svn_operation')} SET state='queued',owner_instance_id=NULL,lease_until=NULL,quiesced_at=NULL,started_at=NULL,finished_at=NULL,updated_at=? WHERE id=?",
                    (timestamp(database_now(self.db)), operation_id),
                )
            elif operation["state"] not in {"queued", "running"}:
                raise CodeKnowledgeError("CODE_OPERATION_REPLAY_DENIED")
            return self.row("code_svn_operation", operation_id)

    def context_for(self, operation: dict[str, Any]) -> CodeAnalysisContext:
        analysis = self.row("code_analysis", operation["analysis_id"])
        return CodeAnalysisContext(
            job_id=analysis["job_id"],
            invocation_id=analysis["invocation_id"],
            owner_instance_id=analysis["owner_instance_id"],
            actor_id=operation["actor_id"],
            knowledge_base_id=analysis["knowledge_base_id"],
            config_revision_id=analysis["config_revision_id"],
            source_id=analysis["source_id"],
            checkout_id=analysis["checkout_id"],
            environment_id=analysis["environment_id"],
            revision=analysis["requested_revision"],
            exact_search_id=analysis["exact_search_id"],
            question_hash=analysis["question_hash"],
            authorization_hash=analysis["authorization_hash"],
            deadline_at=utc_time(analysis["deadline_at"]).isoformat(),
        )

    def heartbeat(
        self, context: CodeAnalysisContext, operation_id: str, *, owner: str, claim: int
    ) -> None:
        with self.db.unit_of_work():
            self._owner(context)
            self._configuration(context)
            checkout = self.row("code_checkout", context.checkout_id, lock=True)
            operation = self.check_claim(operation_id, owner=owner, claim=claim)
            analysis = self.row("code_analysis", operation["analysis_id"], lock=True)
            self._bound(context, analysis)
            if (
                checkout["generation"] != operation["checkout_generation"]
                or analysis["read_revoked_at"] is not None
            ):
                raise CodeKnowledgeError("CODE_OPERATION_LEASE_LOST")
            if operation["operation_kind"] == "update":
                if (
                    checkout["writer_operation_id"] != operation_id
                    or analysis["state"] != "preparing"
                ):
                    raise CodeKnowledgeError("CODE_OPERATION_LEASE_LOST")
            elif (
                analysis["state"] not in {"preparing", "reading"}
                or analysis["read_released_at"] is not None
            ):
                raise CodeKnowledgeError("CODE_OPERATION_LEASE_LOST")
            current = database_now(self.db)
            lease = timestamp(
                min(current + timedelta(seconds=30), utc_time(operation["deadline_at"]))
            )
            self.db.execute(
                f"UPDATE {self.t('code_svn_operation')} SET lease_until=?,updated_at=? WHERE id=?",
                (lease, timestamp(current), operation_id),
            )
            if analysis["read_acquired_at"] is not None:
                if analysis["lease_until"] is None or utc_time(analysis["lease_until"]) <= current:
                    raise CodeKnowledgeError("CODE_READ_GRANT_EXPIRED")
                self.db.execute(
                    f"UPDATE {self.t('code_analysis')} SET lease_until=?,updated_at=? WHERE id=?",
                    (lease, timestamp(current), analysis["id"]),
                )

    def stopped(self, operation_id: str, *, owner: str, claim: int, error_code: str) -> None:
        """Only the executing worker calls after its child has exited, including failures.

        An expired lease alone never invokes this path. Recovery of a disappeared
        owner must obtain a separate actual-stop proof before releasing its claim.
        """
        observed = self.row("code_svn_operation", operation_id)
        with self.db.unit_of_work():
            checkout = self.row("code_checkout", observed["checkout_id"], lock=True)
            operation = self.row("code_svn_operation", operation_id, lock=True)
            if (
                operation["state"] != "running"
                or operation["owner_instance_id"] != owner
                or operation["claim_version"] != claim
            ):
                raise CodeKnowledgeError("CODE_OPERATION_LEASE_LOST")
            stamp = timestamp(database_now(self.db))
            self.db.execute(
                f"UPDATE {self.t('code_svn_operation')} SET state='failed',error_code=?,quiesced_at=?,finished_at=?,updated_at=? WHERE id=?",
                (error_code, stamp, stamp, stamp, operation_id),
            )
            if checkout["writer_operation_id"] == operation_id:
                self.db.execute(
                    f"UPDATE {self.t('code_checkout')} SET state='invalid',invalid_reason=?,writer_operation_id=NULL,updated_at=? WHERE id=?",
                    (error_code, stamp, checkout["id"]),
                )
            analysis = self.row("code_analysis", operation["analysis_id"], lock=True)
            if analysis["state"] == "preparing":
                # No Runtime grant was issued for this admission attempt.
                self.db.execute(
                    f"UPDATE {self.t('code_analysis')} SET state='failed',error_code=?,read_revoked_at=?,reads_quiesced_at=?,read_released_at=CASE WHEN read_acquired_at IS NULL THEN NULL ELSE coalesce(read_released_at,?) END,closed_at=?,updated_at=? WHERE id=?",
                    (error_code, stamp, stamp, stamp, stamp, stamp, analysis["id"]),
                )

    def expire_queued(self, operation_id: str) -> bool:
        observed = self.row("code_svn_operation", operation_id)
        with self.db.unit_of_work():
            checkout = self.row("code_checkout", observed["checkout_id"], lock=True)
            operation = self.row("code_svn_operation", operation_id, lock=True)
            if operation["state"] != "queued" or utc_time(operation["deadline_at"]) > database_now(
                self.db
            ):
                return False
            if operation["started_at"] is not None or operation["owner_instance_id"] is not None:
                raise CodeKnowledgeError("CODE_EXECUTION_NOT_QUIESCED")
            stamp = timestamp(database_now(self.db))
            self.db.execute(
                f"UPDATE {self.t('code_svn_operation')} SET state='cancelled',error_code='CODE_OPERATION_EXPIRED',quiesced_at=?,finished_at=?,updated_at=? WHERE id=?",
                (stamp, stamp, stamp, operation_id),
            )
            if checkout["writer_operation_id"] == operation_id:
                # This claim never launched SVN; its verified old version survives.
                self.db.execute(
                    f"UPDATE {self.t('code_checkout')} SET writer_operation_id=NULL,updated_at=? WHERE id=?",
                    (stamp, checkout["id"]),
                )
            analysis = self.row("code_analysis", operation["analysis_id"], lock=True)
            if analysis["state"] == "preparing":
                self.db.execute(
                    f"UPDATE {self.t('code_analysis')} SET state='cancelled',error_code='CODE_OPERATION_EXPIRED',read_revoked_at=?,reads_quiesced_at=?,read_released_at=CASE WHEN read_acquired_at IS NULL THEN NULL ELSE coalesce(read_released_at,?) END,closed_at=?,updated_at=? WHERE id=?",
                    (stamp, stamp, stamp, stamp, stamp, analysis["id"]),
                )
            return True
