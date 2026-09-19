"""知识管理的静态装配；客户端仅在显式验证时创建并关闭。"""

from contextlib import ExitStack
from typing import Any

from app.modules.audit.application.audit_service import AuditService
from app.modules.permission.application.permission_service import PermissionService
from app.modules.identity.application.principal_jwt import PrincipalTokenIssuer
from app.modules.knowledge.application.source_service import SourceBindingService
from app.modules.knowledge.application.resource_service import KnowledgeResourceService
from app.modules.knowledge.domain.governance import KnowledgeGovernanceError
from app.modules.knowledge.infrastructure.governance_repository import GovernanceStore
from app.modules.knowledge.infrastructure.vector_repository import VectorRepository
from app.modules.knowledge.infrastructure.vector_clients import EmbeddingClient, QdrantClient
from app.modules.knowledge.infrastructure.ones_verifier import OnesSourceVerifier
from app.shared.database import Database


class KnowledgeServices:
    def __init__(
        self,
        database: Database,
        permissions: PermissionService,
        audit: AuditService,
        issuer: PrincipalTokenIssuer | None,
        *,
        instance_code: str,
        provider_origin: str,
    ) -> None:
        self.database, self.permissions, self.audit = database, permissions, audit
        self.issuer, self.instance_code, self.provider_origin = (
            issuer,
            instance_code,
            provider_origin,
        )

    def sources(self) -> SourceBindingService:
        verifier = None
        if self.provider_origin:
            try:
                verifier = OnesSourceVerifier(
                    self.database,
                    self.issuer,
                    instance_code=self.instance_code,
                    provider_origin=self.provider_origin,
                )
            except KnowledgeGovernanceError:
                pass  # 未启用知识环境不会因此产生新的启动依赖。
        return SourceBindingService(
            GovernanceStore(self.database), self.permissions, self.audit, verifier
        )

    def resources(self) -> KnowledgeResourceService:
        return KnowledgeResourceService(self.sources(), VectorRepository(self.database))

    def verify_resource(self, **arguments: Any) -> dict[str, Any]:
        with ExitStack() as cleanup:
            embedding = EmbeddingClient()
            cleanup.callback(embedding.http.close)
            qdrant = QdrantClient()
            cleanup.callback(qdrant.http.close)
            service = KnowledgeResourceService(
                self.sources(), VectorRepository(self.database), embedding=embedding, qdrant=qdrant
            )
            return service.verify_draft(**arguments)
