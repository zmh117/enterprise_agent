"""Worker-side live operation gate; no principal or payload is accepted from the model."""

from typing import Any
from collections.abc import Callable

from app.modules.agent.infrastructure.runtime_pool_store import database_now
from app.modules.knowledge.domain.code_answers import CodeAnalysisContext, utc_time
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.infrastructure.code_analysis_store import CodeAnalysisStore
from app.modules.knowledge.domain.normalization import digest
from app.modules.knowledge.infrastructure.code_checkout_jobs import CodeCheckoutJobs
from app.shared.database import Database


class CodeResultAuthorizer(CodeAnalysisStore):
    def __init__(
        self,
        database: Database,
        management: CodeCheckoutJobs | None = None,
        *,
        authorize: Callable[[CodeAnalysisContext], None] | None = None,
    ):
        super().__init__(database, authorize=authorize)
        self.management = management

    def authorize(self, operation_id: str, claim: int) -> dict[str, Any]:
        operation = self.row("code_svn_operation", operation_id)
        if operation["analysis_id"] is None:
            return self._management(operation, claim)
        if (
            operation["state"] != "succeeded"
            or operation["claim_version"] != claim
            or operation["quiesced_at"] is None
            or operation["result_hash"] is None
            or operation["analysis_id"] is None
            or operation["operation_kind"] not in {"info", "log", "diff", "blame"}
            or utc_time(operation["deadline_at"]) <= database_now(self.db)
        ):
            raise CodeKnowledgeError("CODE_RESULT_DENIED")
        analysis = self.row("code_analysis", operation["analysis_id"])
        context = CodeAnalysisContext(
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
        reader = self.require_reader(context, analysis["id"])
        if (
            operation["checkout_generation"] != reader["generation"]
            or operation["job_id"] != reader["job_id"]
            or operation["invocation_id"] != reader["invocation_id"]
            or operation["source_id"] != reader["source_id"]
        ):
            raise CodeKnowledgeError("CODE_RESULT_DENIED")
        return dict(
            result_hash=operation["result_hash"],
            authorization_hash=reader["authorization_hash"],
            operation_identity=digest(
                [
                    operation_id,
                    claim,
                    reader["id"],
                    reader["generation"],
                    reader["config_revision_id"],
                    reader["owner_instance_id"],
                ]
            ),
        )

    def _management(self, operation: dict[str, Any], claim: int) -> dict[str, Any]:
        if (
            self.management is None
            or operation["state"] != "succeeded"
            or operation["claim_version"] != claim
            or operation["operation_kind"] != "browse"
            or operation["quiesced_at"] is None
            or operation["source_id"] is None
            or operation["result_hash"] is None
            or utc_time(operation["deadline_at"]) <= database_now(self.db)
        ):
            raise CodeKnowledgeError("CODE_RESULT_DENIED")
        self.management.require_management(operation)
        return dict(
            result_hash=operation["result_hash"],
            operation_identity=digest(
                [
                    operation["id"],
                    claim,
                    operation["actor_id"],
                    operation["config_revision_id"],
                    operation["source_id"],
                    operation["request_hash"],
                ]
            ),
        )
