"""只装配知识读取和审计；不创建平台 Container、私钥签发器或 ONES 凭据仓储。"""

from contextlib import ExitStack
import os

from app.modules.audit.application.audit_service import AuditService
from app.modules.authorization_center.application.service import BusinessAuthorizationService
from app.modules.authorization_center.infrastructure.repository import AuthorizationCenterRepository
from app.modules.identity.application.principal_jwt import PrincipalJwks, PrincipalTokenVerifier
from app.modules.identity.application.service_principal import ServicePrincipalTokenClient
from app.modules.identity.infrastructure.repository import IdentityRepository
from app.modules.job.infrastructure.repositories import AuditRepository
from app.modules.knowledge.application.directory import KnowledgeDirectory
from app.modules.knowledge.application.resource_service import KnowledgeResourceReader
from app.modules.knowledge.application.search import KnowledgeSearch
from app.modules.knowledge.infrastructure.governance_repository import GovernanceStore
from app.modules.knowledge.infrastructure.job_access import KnowledgeJobGate
from app.modules.knowledge.infrastructure.ones_verifier import ones_target_hash
from app.modules.knowledge.infrastructure.reader_access import KnowledgePrincipalAccess
from app.modules.knowledge.infrastructure.readability_client import KnowledgeReadabilityClient
from app.modules.knowledge.infrastructure.vector_clients import EmbeddingClient, QdrantClient
from app.modules.knowledge.infrastructure.vector_repository import VectorRepository
from app.modules.mcp_audit import McpAuditCoordinator
from app.modules.mcp_tool_runtime.job_snapshot import JobMcpToolSnapshotService
from app.shared.database import Database, default_migrations_dir
from app.shared.migrations import SchemaHeadValidator
from app.shared.mcp_server_policy import KNOWLEDGE_MCP_SERVER_CODE
from services.knowledge_mcp_server.app import KnowledgeSecurityMiddleware, create_app
from services.knowledge_mcp_server.auth import KnowledgeMcpAuth
from services.knowledge_mcp_server.tools import KnowledgeMcpTools
from services.knowledge_mcp_server.database_policy import assert_reader_role


def build_tools(
    database: Database,
    public_keys: PrincipalJwks,
    *,
    bootstrap_file: str,
    instance_code: str,
    provider_origin: str,
    cleanup: ExitStack,
) -> KnowledgeMcpTools:
    audit = AuditService(AuditRepository(database))
    authorization = BusinessAuthorizationService(
        AuthorizationCenterRepository(database), IdentityRepository(database), audit_service=audit
    )
    access = KnowledgePrincipalAccess(
        PrincipalTokenVerifier(
            public_keys, expected_audience=KNOWLEDGE_MCP_SERVER_CODE, audit_service=audit
        ),
        KnowledgeJobGate(database, JobMcpToolSnapshotService(database), authorization),
    )
    resources = KnowledgeResourceReader(
        GovernanceStore(database),
        VectorRepository(database),
        instance_code=instance_code,
        target_hash=ones_target_hash(instance_code, provider_origin),
    )
    embedding = EmbeddingClient()
    cleanup.callback(embedding.http.close)
    qdrant = QdrantClient()
    cleanup.callback(qdrant.http.close)
    identity = ServicePrincipalTokenClient(
        base_url="http://api-server:8000",
        allowed_hosts=("api-server",),
        bootstrap_credential_file=bootstrap_file,
    )
    return KnowledgeMcpTools(
        KnowledgeMcpAuth(database, access),
        KnowledgeDirectory(access, resources, audit),
        KnowledgeSearch(
            access, resources, embedding, qdrant, KnowledgeReadabilityClient(identity), audit
        ),
        McpAuditCoordinator(database, max_payload_bytes=16 * 1024, audit_service=audit),
    )


def build_app() -> KnowledgeSecurityMiddleware:
    cleanup = ExitStack()
    try:
        # 不调用平台 load_settings：知识读取端不加载主密钥、签名私钥、模型 Key 或种子配置。
        required = (
            "DATABASE_DSN",
            "PRINCIPAL_JWKS_FILE",
            "KNOWLEDGE_BOOTSTRAP_TOKEN_FILE",
            "ONES_IDENTITY_INSTANCE_CODE",
            "ONES_MCP_PROVIDER_BASE_URL",
        )
        if any(not os.environ.get(name, "").strip() for name in required):
            raise ValueError
        database = Database(
            os.environ["DATABASE_DSN"], pool_min_size=0, pool_max_size=4, pool_timeout_seconds=3
        )
        cleanup.callback(database.close)
        assert_reader_role(database)
        tools = build_tools(
            database,
            PrincipalJwks.from_file(os.environ["PRINCIPAL_JWKS_FILE"]),
            bootstrap_file=os.environ["KNOWLEDGE_BOOTSTRAP_TOKEN_FILE"],
            instance_code=os.environ["ONES_IDENTITY_INSTANCE_CODE"],
            provider_origin=os.environ["ONES_MCP_PROVIDER_BASE_URL"],
            cleanup=cleanup,
        )

        def ready() -> None:
            SchemaHeadValidator(database, default_migrations_dir()).require_current()
            tools.audit.assert_ready(retention_cleanup=False)

        return create_app(tools, ready=ready, close=cleanup.close)
    except Exception:
        cleanup.close()
        raise ValueError("知识 MCP 启动配置无效，请检查受管配置与公开 JWKS") from None
