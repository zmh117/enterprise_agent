"""知识读取的当前 Principal 与本人来源；不解析任何 ONES 凭据。"""

import json
from typing import Any
from app.modules.knowledge.application.retrieval_budget import RetrievalBudget

from app.modules.identity.application.principal_jwt import PrincipalTokenVerifier
from app.modules.knowledge.domain.governance import (
    KnowledgeGovernanceError,
    checked_identifier,
    strict_object,
)
from app.modules.knowledge.domain.models import KnowledgeJobAccess
from app.modules.knowledge.infrastructure.job_access import KnowledgeJobGate, KNOWLEDGE_TOOLS
from app.shared.database import Database


from app.modules.knowledge.domain.models import OnesKnowledgeIdentity


def current_ones_identity(database: Database, actor_id: str) -> OnesKnowledgeIdentity:
    rows = database.execute(
        "select id,external_subject_id,tenant_code,metadata_json from user_external_identity "
        "where user_id=? and provider='ones' and status='enabled' order by id",
        (actor_id,),
    )
    try:
        if len(rows) != 1:
            raise ValueError
        row = rows[0]
        metadata = json.loads(row["metadata_json"], object_pairs_hook=strict_object)
        team = checked_identifier(metadata["default_team_id"])
        if not isinstance(metadata["team_uuids"], list) or metadata["team_uuids"].count(team) != 1:
            raise ValueError
        return OnesKnowledgeIdentity(
            checked_identifier(row["id"]),
            checked_identifier(row["external_subject_id"]),
            checked_identifier(row["tenant_code"]),
            team,
        )
    except (ValueError, TypeError, KeyError, RecursionError, KnowledgeGovernanceError):
        raise KnowledgeGovernanceError("knowledge_source_identity_invalid") from None


class KnowledgePrincipalAccess:
    def __init__(self, verifier: PrincipalTokenVerifier, gate: KnowledgeJobGate) -> None:
        if verifier.expected_audience != "knowledge-mcp":
            raise ValueError("Knowledge reader requires its own Principal audience")
        self.verifier = verifier
        self.gate = gate

    def authenticate(self, token: str, tool: str) -> KnowledgeJobAccess:
        if tool not in KNOWLEDGE_TOOLS:
            raise KnowledgeGovernanceError("knowledge_job_denied")
        claims = self.verifier.verify_for_running_job(
            token,
            self.gate.database,
            self.gate.snapshots,
            required_scope=f"mcp:knowledge-mcp:{tool}:invoke",
        )
        return self.gate.resolve(job_id=claims["job_id"], actor_id=claims["sub"])

    def identity(self, actor_id: str) -> OnesKnowledgeIdentity:
        return current_ones_identity(self.gate.database, actor_id)

    def budget(self, job_id: str, *, deadline_ms: int | None = None) -> RetrievalBudget:
        return job_budget(self.gate.database, job_id, deadline_ms=deadline_ms)


def job_budget(
    database: Database, job_id: str, *, deadline_ms: int | None = None
) -> RetrievalBudget:
    def running_job() -> dict[str, Any]:
        row = database.execute_one(
            "select retry_count,locked_at,execution_policy_json from agent_job where id=? and status='RUNNING'",
            (job_id,),
        )
        if not row:
            raise KnowledgeGovernanceError("knowledge_job_denied")
        return row

    return RetrievalBudget(running_job, deadline_ms=deadline_ms)
