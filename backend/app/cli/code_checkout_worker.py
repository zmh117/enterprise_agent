"""Administrative authorization shared by managed SVN operations."""

from app.modules.audit.application.audit_service import AuditService
from app.modules.identity.application.authorization import AuthorizationEvaluator
from app.modules.identity.infrastructure import IdentityRepository
from app.modules.job.infrastructure.repositories import AuditRepository, ConfigurationRepository
from app.modules.permission.application.permission_service import PermissionService
from app.modules.knowledge.application.source_service import KnowledgeAdministration
from app.modules.knowledge.infrastructure.governance_repository import GovernanceStore
from app.shared.database import Database


def administration(db: Database) -> KnowledgeAdministration:
    audit = AuditService(AuditRepository(db))
    permissions = PermissionService(
        ConfigurationRepository(db),
        authorization_evaluator=AuthorizationEvaluator(IdentityRepository(db), audit),
    )
    return KnowledgeAdministration(GovernanceStore(db), permissions, audit)
