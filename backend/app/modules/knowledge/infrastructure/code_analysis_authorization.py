"""Current human/app/tool authorization, rechecked by both API and SVN worker."""

from app.modules.audit.application.audit_service import AuditService
from app.modules.authorization_center.application.service import BusinessAuthorizationService
from app.modules.authorization_center.infrastructure.repository import AuthorizationCenterRepository
from app.modules.identity.infrastructure.repository import IdentityRepository
from app.modules.job.infrastructure.repositories import AuditRepository
from app.modules.knowledge.domain.code_answers import CodeAnalysisContext, code_authorization_hash
from app.modules.knowledge.domain.code_contracts import CodeKnowledgeError
from app.modules.knowledge.infrastructure.job_access import KnowledgeJobGate
from app.modules.mcp_tool_runtime.job_snapshot import JobMcpToolSnapshotService
from app.shared.database import Database


class CodeAnalysisAuthorization:
    def __init__(self, database: Database) -> None:
        authorization = BusinessAuthorizationService(
            AuthorizationCenterRepository(database),
            IdentityRepository(database),
            audit_service=AuditService(AuditRepository(database)),
        )
        self.gate = KnowledgeJobGate(database, JobMcpToolSnapshotService(database), authorization)

    def __call__(self, context: CodeAnalysisContext) -> None:
        access = self.gate.resolve(job_id=context.job_id, actor_id=context.actor_id)
        if (
            context.knowledge_base_id not in access.knowledge_base_ids
            or code_authorization_hash(access) != context.authorization_hash
        ):
            raise CodeKnowledgeError("CODE_AUTHORIZATION_CHANGED")
