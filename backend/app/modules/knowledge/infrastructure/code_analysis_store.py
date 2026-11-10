"""Shared readers/exclusive SVN writers coordinated in short PostgreSQL transactions."""

from datetime import timedelta
from collections.abc import Callable
from app.shared.database import Database
from app.modules.knowledge.infrastructure.code_analysis_authorization import (
    CodeAnalysisAuthorization,
)
from typing import Any

from app.modules.agent.infrastructure.runtime_pool_store import database_now, timestamp
from app.modules.knowledge.infrastructure.code_environment import require_environment
from app.modules.knowledge.domain.code_answers import CodeAnalysisContext, svn_revision, utc_time
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.domain.identity import stable_id
from app.modules.knowledge.infrastructure.code_checkout_store import CodeCheckoutStore
from app.modules.knowledge.infrastructure.storage import insert


class CodeAnalysisStore(CodeCheckoutStore):
    def __init__(
        self, database: Database, *, authorize: Callable[[CodeAnalysisContext], None] | None = None
    ) -> None:
        super().__init__(database)
        self.authorize_context = (
            authorize if authorize is not None else CodeAnalysisAuthorization(database)
        )

    def _owner(self, context: CodeAnalysisContext, *, live: bool = True) -> dict[str, Any]:
        suffix = " FOR UPDATE" if self.db.engine == "postgres" else ""
        job = self.db.execute_one(
            "SELECT status FROM agent_job WHERE id=?" + suffix, (context.job_id,)
        )
        invocation = self.db.execute_one(
            "SELECT * FROM agent_runtime_invocation WHERE job_id=? AND invocation_id=?",
            (context.job_id, context.invocation_id),
        )
        if (
            not invocation
            or not job
            or invocation["instance_id"] != context.owner_instance_id
            or invocation["app_user_id"] != context.actor_id
        ):
            raise CodeKnowledgeError("CODE_EXECUTION_MISMATCH")
        if live:
            self.authorize_context(context)
            current = database_now(self.db)
            if (
                job["status"] != "RUNNING"
                or invocation["state"] != "RUNNING"
                or invocation["cancel_requested_at"] is not None
                or invocation["execution_quiesced_at"] is not None
                or utc_time(context.deadline_at) > utc_time(invocation["execution_deadline_at"])
                or current
                >= min(utc_time(context.deadline_at), utc_time(invocation["lease_until"]))
            ):
                raise CodeKnowledgeError("CODE_EXECUTION_ENDED")
        return invocation

    def _configuration(self, context: CodeAnalysisContext) -> None:
        require_environment(self.db, context.config_revision_id, context.environment_id)
        suffix = (
            " FOR SHARE OF p"
            if self.db.engine == "postgres" and self.db.current_unit_of_work is not None
            else ""
        )
        row = self.db.execute_one(
            f"SELECT c.source_id,c.checkout_id FROM {self.t('code_resource_config')} c "
            f"JOIN {self.t('retrieval_revision')} r ON r.id=c.revision_id "
            f"JOIN {self.t('retrieval_resource')} p ON p.id=r.resource_id "
            "WHERE c.revision_id=? AND p.knowledge_base_id=? AND p.published_revision_id=c.revision_id AND p.status='enabled'"
            + suffix,
            (context.config_revision_id, context.knowledge_base_id),
        )
        if (
            not row
            or row["source_id"] != context.source_id
            or row["checkout_id"] != context.checkout_id
        ):
            raise CodeKnowledgeError("CODE_CONFIGURATION_CHANGED")

    def _bound(self, context: CodeAnalysisContext, analysis: dict[str, Any]) -> None:
        fields = (
            "job_id",
            "invocation_id",
            "owner_instance_id",
            "knowledge_base_id",
            "config_revision_id",
            "source_id",
            "checkout_id",
            "authorization_hash",
            "question_hash",
            "exact_search_id",
            "environment_id",
        )
        if (
            any(analysis[k] != getattr(context, k) for k in fields)
            or analysis["requested_revision"] != context.revision
            or utc_time(analysis["deadline_at"]) != utc_time(context.deadline_at)
        ):
            raise CodeKnowledgeError("CODE_ANALYSIS_MISMATCH")

    def begin(self, context: CodeAnalysisContext, request_key: str) -> dict[str, Any]:
        svn_revision(context.revision)
        key = stable_id("analysis-request", context.job_id, request_key)
        with self.db.unit_of_work():
            self._owner(context)
            self._configuration(context)
            checkout = self.row("code_checkout", context.checkout_id, lock=True)
            old = self.db.execute_one(
                f"SELECT * FROM {self.t('code_analysis')} WHERE request_key=?", (key,)
            )
            if old:
                if old["request_hash"] != context.fingerprint():
                    raise CodeKnowledgeError("CODE_IDEMPOTENCY_CONFLICT")
                return old
            self._admit(context, checkout)
            return self._create(context, checkout, key)

    def _admit(self, context: CodeAnalysisContext, checkout: dict[str, Any]) -> None:
        if checkout["source_id"] != context.source_id or checkout["state"] in {
            "invalid",
            "retired",
            "preparing",
        }:
            raise CodeKnowledgeError("CODE_CHECKOUT_UNAVAILABLE")
        if checkout["writer_operation_id"] is not None:
            raise CodeKnowledgeError("WORKSPACE_BUSY")
        if self.db.execute_one(
            f"SELECT id FROM {self.t('code_analysis')} WHERE job_id=? AND closed_at IS NULL LIMIT 1",
            (context.job_id,),
        ):
            raise CodeKnowledgeError("CODE_ANALYSIS_ALREADY_ACTIVE")
        if checkout["verified_revision"] != context.revision and self.db.execute_one(
            f"SELECT id FROM {self.t('code_analysis')} WHERE checkout_id=? AND read_acquired_at IS NOT NULL AND read_released_at IS NULL LIMIT 1",
            (checkout["id"],),
        ):
            raise CodeKnowledgeError("WORKSPACE_BUSY")

    def _create(
        self, context: CodeAnalysisContext, checkout: dict[str, Any], key: str
    ) -> dict[str, Any]:
        current = database_now(self.db)
        stamp = timestamp(current)
        writing = checkout["verified_revision"] != context.revision
        generation = checkout["generation"] + int(writing)
        identifier = stable_id("analysis", key)
        operation_id = stable_id("source-admission", key)
        values = dict(context.__dict__)
        values.pop("revision")
        values.update(
            id=identifier,
            requested_revision=context.revision,
            request_key=key,
            request_hash=context.fingerprint(),
            state="preparing",
            generation=generation,
            created_at=stamp,
            updated_at=stamp,
        )
        values.pop("actor_id")
        if not writing:
            values.update(
                read_acquired_at=stamp,
                lease_until=timestamp(
                    min(current + timedelta(seconds=30), utc_time(context.deadline_at))
                ),
            )
        insert(self.db, "code_analysis", values)
        insert(
            self.db,
            "code_svn_operation",
            dict(
                id=operation_id,
                source_id=context.source_id,
                checkout_id=checkout["id"],
                analysis_id=identifier,
                job_id=context.job_id,
                invocation_id=context.invocation_id,
                actor_id=context.actor_id,
                config_revision_id=context.config_revision_id,
                operation_kind="update" if writing else "info",
                request_key=key,
                request_hash=context.fingerprint(),
                state="queued",
                target_revision=context.revision,
                checkout_generation=generation,
                deadline_at=context.deadline_at,
                created_at=stamp,
                updated_at=stamp,
            ),
        )
        if writing:
            self.db.execute(
                f"UPDATE {self.t('code_checkout')} SET writer_operation_id=?,generation=?,updated_at=? WHERE id=?",
                (operation_id, generation, stamp, checkout["id"]),
            )
        return self.row("code_analysis", identifier)

    def confirm_reading(
        self,
        context: CodeAnalysisContext,
        operation_id: str,
        *,
        owner: str,
        claim: int,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Worker calls only after real SVN validation and child-process quiescence."""
        with self.db.unit_of_work():
            self._owner(context)
            self._configuration(context)
            checkout = self.row("code_checkout", context.checkout_id, lock=True)
            operation = self.row("code_svn_operation", operation_id, lock=True)
            analysis = self.row("code_analysis", operation["analysis_id"], lock=True)
            self._bound(context, analysis)
            if (
                operation["state"] != "running"
                or operation["owner_instance_id"] != owner
                or operation["claim_version"] != claim
                or operation["lease_until"] is None
                or utc_time(operation["lease_until"]) <= database_now(self.db)
                or utc_time(operation["deadline_at"]) <= database_now(self.db)
            ):
                raise CodeKnowledgeError("CODE_OPERATION_LEASE_LOST")
            if (
                checkout["generation"] != analysis["generation"]
                or operation["checkout_generation"] != analysis["generation"]
            ):
                raise CodeKnowledgeError("CODE_CHECKOUT_CHANGED")
            if (
                checkout["writer_operation_id"] not in (None, operation_id)
                or analysis["state"] != "preparing"
            ):
                raise CodeKnowledgeError("CODE_ANALYSIS_ENDED")
            current = database_now(self.db)
            stamp = timestamp(current)
            lease = timestamp(min(current + timedelta(seconds=30), utc_time(context.deadline_at)))
            self.db.execute(
                f"UPDATE {self.t('code_analysis')} SET state='reading',read_acquired_at=coalesce(read_acquired_at,?),lease_until=?,updated_at=? WHERE id=?",
                (stamp, lease, stamp, analysis["id"]),
            )
            self.db.execute(
                f"UPDATE {self.t('code_checkout')} SET state='ready',verified_revision=?,verified_at=?,writer_operation_id=NULL,updated_at=? WHERE id=?",
                (context.revision, stamp, stamp, checkout["id"]),
            )
            self.db.execute(
                f"UPDATE {self.t('code_svn_operation')} SET state='succeeded',quiesced_at=?,finished_at=?,updated_at=? WHERE id=?",
                (stamp, stamp, stamp, operation_id),
            )
            if metadata is not None:
                from app.modules.knowledge.domain.normalization import canonical_json, digest

                self.db.execute(
                    f"UPDATE {self.t('code_svn_operation')} SET result_json=?,result_hash=? WHERE id=?",
                    (canonical_json(metadata), digest(metadata), operation_id),
                )
            return self.row("code_analysis", analysis["id"])

    def require_reader(self, context: CodeAnalysisContext, analysis_id: str) -> dict[str, Any]:
        with self.db.unit_of_work():
            self._owner(context)
            self._configuration(context)
            checkout = self.row("code_checkout", context.checkout_id, lock=True)
            analysis = self.row("code_analysis", analysis_id)
            self._bound(context, analysis)
            if (
                analysis["state"] != "reading"
                or analysis["read_revoked_at"] is not None
                or analysis["read_released_at"] is not None
                or analysis["lease_until"] is None
                or utc_time(analysis["lease_until"]) <= database_now(self.db)
                or checkout["state"] != "ready"
                or checkout["writer_operation_id"] is not None
                or checkout["generation"] != analysis["generation"]
                or checkout["verified_revision"] != context.revision
            ):
                raise CodeKnowledgeError("CODE_READ_GRANT_EXPIRED")
            return analysis

    def revoke(self, context: CodeAnalysisContext, analysis_id: str) -> None:
        with self.db.unit_of_work():
            self._owner(context, live=False)
            self.row("code_checkout", context.checkout_id, lock=True)
            analysis = self.row("code_analysis", analysis_id, lock=True)
            self._bound(context, analysis)
            self.db.execute(
                f"UPDATE {self.t('code_analysis')} SET read_revoked_at=coalesce(read_revoked_at,?),updated_at=? WHERE id=?",
                (timestamp(database_now(self.db)), timestamp(database_now(self.db)), analysis_id),
            )

    def release_stopped(self, context: CodeAnalysisContext, analysis_id: str) -> None:
        """Recovery releases only an invocation with durable actual-stop evidence."""
        with self.db.unit_of_work():
            invocation = self._owner(context, live=False)
            checkout = self.row("code_checkout", context.checkout_id, lock=True)
            analysis = self.row("code_analysis", analysis_id, lock=True)
            self._bound(context, analysis)
            if analysis["closed_at"] is not None:
                return
            if (
                invocation["execution_quiesced_at"] is None
                or checkout["writer_operation_id"] is not None
            ):
                raise CodeKnowledgeError("CODE_EXECUTION_NOT_QUIESCED")
            active = self.db.execute_one(
                f"SELECT id FROM {self.t('code_svn_operation')} WHERE analysis_id=? AND state='running' AND quiesced_at IS NULL LIMIT 1",
                (analysis_id,),
            )
            if active:
                raise CodeKnowledgeError("CODE_EXECUTION_NOT_QUIESCED")
            stamp = timestamp(database_now(self.db))
            self.db.execute(
                f"UPDATE {self.t('code_svn_operation')} SET state='cancelled',quiesced_at=?,finished_at=?,updated_at=? WHERE analysis_id=? AND state='queued'",
                (stamp, stamp, stamp, analysis_id),
            )
            self.db.execute(
                f"UPDATE {self.t('code_analysis')} SET state='cancelled',read_revoked_at=coalesce(read_revoked_at,?),reads_quiesced_at=?,read_released_at=CASE WHEN read_acquired_at IS NULL THEN NULL ELSE coalesce(read_released_at,?) END,closed_at=?,updated_at=? WHERE id=?",
                (stamp, stamp, stamp, stamp, stamp, analysis_id),
            )
